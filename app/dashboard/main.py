from pathlib import Path
from datetime import datetime, timezone
from typing import Any
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json
import secrets
from app.core.redis import redis_client
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware
from app.config import get_settings
from app.core.db import get_session, session_factory
from app.core.security import new_state
from app.repositories.analytics import overview
from app.services.analytics import activity_series, top_channels
from app.services.automod import ACTIONS, RULE_TYPES, validate_rule_config
from app.models import AuditLog, AutoModListEntry, AutoModRule, Guild, GuildSettings, Member, EconomyAccount, Experience, Reputation, Ticket, TicketEvent, Suggestion, Report, Giveaway, GiveawayEntry, Poll, PollVote

settings = get_settings()
app = FastAPI(title="BN Bot Dashboard")
app.add_middleware(SessionMiddleware, secret_key=settings.app_secret_key, https_only=settings.app_env == "production", same_site="lax", session_cookie="bn_session")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

class GuildSettingsInput(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)
    locale: str = Field(min_length=2, max_length=16)

class AutoModStatusInput(BaseModel):
    enabled: bool
    blacklist_action: str = Field(default="delete", min_length=1, max_length=20)

class AutoModRuleInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    rule_type: str = Field(min_length=1, max_length=40)
    action: str = Field(default="delete", min_length=1, max_length=20)
    enabled: bool = True
    priority: int = Field(default=0, ge=-10000, le=10000)
    channel_ids: list[int] = Field(default_factory=list, max_length=100)
    role_ids: list[int] = Field(default_factory=list, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)

class AutoModRulePatch(BaseModel):
    action: str | None = Field(default=None, min_length=1, max_length=20)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=-10000, le=10000)
    channel_ids: list[int] | None = Field(default=None, max_length=100)
    role_ids: list[int] | None = Field(default=None, max_length=100)
    config: dict[str, Any] | None = None

class AutoModListInput(BaseModel):
    list_type: str = Field(min_length=1, max_length=20)
    entry_type: str = Field(min_length=1, max_length=20)
    value: str = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, max_length=500)

async def discord_get(path: str, access_token: str) -> Any:
    async with httpx.AsyncClient(base_url="https://discord.com/api/v10", timeout=10) as client:
        response = await client.get(path, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Discord authentication session expired")
    if response.status_code == 403:
        raise HTTPException(status_code=403, detail="Discord denied access to this resource")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Discord authentication service unavailable")
    return response.json()

async def discord_token(code: str) -> dict[str, Any]:
    data = {"client_id": settings.discord_client_id, "client_secret": settings.discord_client_secret, "grant_type": "authorization_code", "code": code, "redirect_uri": settings.discord_redirect_uri}
    async with httpx.AsyncClient(base_url="https://discord.com/api/v10", timeout=10) as client:
        response = await client.post("/oauth2/token", data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if response.status_code >= 400:
        raise HTTPException(status_code=400, detail="OAuth2 authorization failed")
    return response.json()

async def get_dashboard_token(request: Request) -> str:
    session_id = request.session.get("dashboard_session")
    if not session_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    raw = await redis_client.get(f"bn:dashboard:session:{session_id}")
    if not raw:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Authentication session expired")
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        request.session.clear()
        raise HTTPException(status_code=401, detail="Authentication session expired")
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Authentication session expired")
    return token

async def session_guilds(request: Request) -> list[dict[str, Any]]:
    token = await get_dashboard_token(request)
    guilds = await discord_get("/users/@me/guilds", token)
    manageable = [g for g in guilds if int(g.get("permissions", 0)) & 32 or int(g.get("permissions", 0)) & 8 or bool(g.get("owner"))]
    if not manageable:
        return []
    async with session_factory() as session:
        active_ids = set((await session.execute(select(Guild.id).where(Guild.active.is_(True), Guild.id.in_([int(g["id"]) for g in manageable])))).scalars())
    return [g for g in manageable if int(g["id"]) in active_ids]

async def authorized_guild(request: Request, guild_id: int) -> dict[str, Any]:
    guilds = await session_guilds(request)
    guild = next((g for g in guilds if int(g["id"]) == guild_id), None)
    if guild is None:
        raise HTTPException(status_code=403, detail="Guild access denied")
    return guild

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if "csrf" not in request.session:
        request.session["csrf"] = new_state()
    return templates.TemplateResponse(request=request, name="index.html", context={"authenticated": bool(request.session.get("dashboard_session")), "csrf": request.session["csrf"]})

@app.get("/auth/login")
async def auth_login(request: Request):
    state = new_state()
    request.session["oauth_state"] = state
    query = urlencode({"client_id": settings.discord_client_id, "response_type": "code", "redirect_uri": settings.discord_redirect_uri, "scope": "identify guilds", "state": state})
    return RedirectResponse(f"https://discord.com/oauth2/authorize?{query}")

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str, state: str):
    if not state or state != request.session.pop("oauth_state", None):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    token = await discord_token(code)
    access_token = token.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Missing OAuth access token")
    user = await discord_get("/users/@me", access_token)
    guilds = await discord_get("/users/@me/guilds", access_token)
    allowed = [g for g in guilds if int(g.get("permissions", 0)) & 32 or int(g.get("permissions", 0)) & 8 or bool(g.get("owner"))]
    if not allowed:
        raise HTTPException(status_code=403, detail="Your Discord account cannot manage a guild supported by BN Bot")
    session_id = secrets.token_urlsafe(32)
    expires_in = int(token.get("expires_in", 3600))
    await redis_client.set(f"bn:dashboard:session:{session_id}", json.dumps({"access_token": access_token}), ex=expires_in)
    request.session["dashboard_session"] = session_id
    request.session["user"] = {"id": user["id"], "username": user.get("username"), "avatar": user.get("avatar")}
    return RedirectResponse("/")

@app.post("/auth/logout")
async def auth_logout(request: Request):
    form = await request.form()
    if form.get("csrf") != request.session.get("csrf"):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    session_id = request.session.get("dashboard_session")
    if session_id:
        await redis_client.delete(f"bn:dashboard:session:{session_id}")
    request.session.clear()
    return RedirectResponse("/", status_code=303)

@app.get("/api/me")
async def api_me(request: Request):
    await get_dashboard_token(request)
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

@app.get("/api/guilds")
async def api_guilds(request: Request):
    guilds = await session_guilds(request)
    return [{"id": g["id"], "name": g["name"], "icon": g.get("icon"), "owner": g.get("owner", False)} for g in guilds]

@app.get("/api/guilds/{guild_id}/overview")
async def api_overview(request: Request, guild_id: int, session: AsyncSession = Depends(get_session)):
    await authorized_guild(request, guild_id)
    return await overview(session, guild_id)

@app.get("/api/guilds/{guild_id}/activity")
async def api_activity(request: Request, guild_id: int, days: int = 7, session: AsyncSession = Depends(get_session)):
    await authorized_guild(request, guild_id)
    if days not in {1, 7, 30, 90}:
        raise HTTPException(status_code=400, detail="days must be 1, 7, 30 or 90")
    return {"messages": await activity_series(session, guild_id, "messages", days), "channels": await top_channels(session, guild_id, "messages", days=days)}

@app.get("/api/guilds/{guild_id}/members")
async def api_members(request: Request, guild_id: int, page: int = 1, page_size: int = 25, session: AsyncSession = Depends(get_session)):
    await authorized_guild(request, guild_id)
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    result = await session.execute(select(Member).where(Member.guild_id == guild_id, Member.left_at.is_(None)).order_by(Member.activity_score.desc()).offset((page - 1) * page_size).limit(page_size))
    rows = result.scalars().all()
    return [{"user_id": row.user_id, "messages": row.message_count, "voice_seconds": row.voice_seconds, "activity": row.activity_score} for row in rows]

@app.get("/api/guilds/{guild_id}/economy")
async def api_economy(request: Request, guild_id: int, session: AsyncSession = Depends(get_session)):
    await authorized_guild(request, guild_id)
    result = await session.execute(select(EconomyAccount.user_id, EconomyAccount.wallet, EconomyAccount.bank).where(EconomyAccount.guild_id == guild_id).order_by((EconomyAccount.wallet + EconomyAccount.bank).desc()).limit(25))
    return [{"user_id": user_id, "wallet": str(wallet), "bank": str(bank), "total": str(wallet + bank)} for user_id, wallet, bank in result.all()]

@app.get("/api/guilds/{guild_id}/levels")
async def api_levels(request: Request, guild_id: int, session: AsyncSession = Depends(get_session)):
    await authorized_guild(request, guild_id)
    result = await session.execute(select(Experience.user_id, Experience.level, Experience.total_xp).where(Experience.guild_id == guild_id).order_by(Experience.total_xp.desc()).limit(25))
    return [{"user_id": user_id, "level": level, "xp": xp} for user_id, level, xp in result.all()]

@app.get("/api/guilds/{guild_id}/settings")
async def api_settings(request: Request, guild_id: int, session: AsyncSession = Depends(get_session)):
    await authorized_guild(request, guild_id)
    settings_row = await session.get(GuildSettings, guild_id)
    if settings_row is None:
        raise HTTPException(status_code=404, detail="Guild settings not found")
    return {"timezone": settings_row.timezone, "locale": settings_row.locale}

@app.put("/api/guilds/{guild_id}/settings")
async def update_settings(request: Request, guild_id: int, payload: GuildSettingsInput, session: AsyncSession = Depends(get_session)):
    if request.headers.get("x-csrf-token") != request.session.get("csrf"):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    await authorized_guild(request, guild_id)
    settings_row = await session.get(GuildSettings, guild_id)
    if settings_row is None:
        raise HTTPException(status_code=404, detail="Guild settings not found")
    timezone_name = payload.timezone.strip()
    locale_name = payload.locale.strip()
    if not timezone_name or len(locale_name) < 2:
        raise HTTPException(status_code=422, detail="Timezone and locale are required")
    try:
        ZoneInfo(timezone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise HTTPException(status_code=422, detail="Invalid timezone") from None
    settings_row.timezone = timezone_name
    settings_row.locale = locale_name
    settings_row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return {"timezone": settings_row.timezone, "locale": settings_row.locale}




async def _dashboard_audit(request: Request, session: AsyncSession, guild_id: int, action: str, resource: str, before: dict[str, Any] | None = None, after: dict[str, Any] | None = None) -> None:
    user = request.session.get("user") or {}
    executor_id = int(user.get("id", 0))
    session.add(AuditLog(id=secrets.randbits(62), guild_id=guild_id, executor_id=executor_id, action=action, resource=resource, before_state=before, after_state=after, created_at=datetime.now(timezone.utc)))


async def _automod_rows(session: AsyncSession, guild_id: int) -> list[AutoModRule]:
    result = await session.execute(select(AutoModRule).where(AutoModRule.guild_id == guild_id).order_by(AutoModRule.priority.desc(), AutoModRule.id.asc()))
    return list(result.scalars())


def _automod_rule_json(row: AutoModRule) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "rule_type": row.rule_type, "action": row.action, "enabled": row.enabled, "priority": row.priority, "channel_ids": row.channel_ids or [], "role_ids": row.role_ids or [], "config": row.config or {}}


@app.get("/api/guilds/{guild_id}/automod")
async def api_automod(request: Request, guild_id: int, session: AsyncSession = Depends(get_session)):
    await authorized_guild(request, guild_id)
    settings_row = await session.get(GuildSettings, guild_id)
    if settings_row is None:
        raise HTTPException(status_code=404, detail="Guild settings not found")
    rules = await _automod_rows(session, guild_id)
    entries = list((await session.execute(select(AutoModListEntry).where(AutoModListEntry.guild_id == guild_id).order_by(AutoModListEntry.list_type.asc(), AutoModListEntry.entry_type.asc(), AutoModListEntry.value.asc()))).scalars())
    automod_config = dict((settings_row.config or {}).get("automod", {}))
    return {"enabled": settings_row.automod_enabled, "blacklist_action": automod_config.get("blacklist_action", "delete"), "rules": [_automod_rule_json(row) for row in rules], "lists": [{"id": row.id, "list_type": row.list_type, "entry_type": row.entry_type, "value": row.value, "reason": row.reason} for row in entries]}


@app.put("/api/guilds/{guild_id}/automod")
async def update_automod(request: Request, guild_id: int, payload: AutoModStatusInput, session: AsyncSession = Depends(get_session)):
    if request.headers.get("x-csrf-token") != request.session.get("csrf"):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    await authorized_guild(request, guild_id)
    if payload.blacklist_action not in ACTIONS - {"none"}:
        raise HTTPException(status_code=422, detail="Invalid blacklist action")
    settings_row = await session.get(GuildSettings, guild_id)
    if settings_row is None:
        raise HTTPException(status_code=404, detail="Guild settings not found")
    config = dict(settings_row.config or {})
    automod_config = dict(config.get("automod", {}))
    automod_config["blacklist_action"] = payload.blacklist_action
    config["automod"] = automod_config
    settings_row.config = config
    settings_row.automod_enabled = payload.enabled
    settings_row.updated_at = datetime.now(timezone.utc)
    await _dashboard_audit(request, session, guild_id, "automod.settings_update", "settings", None, {"enabled": payload.enabled, "blacklist_action": payload.blacklist_action})
    await session.commit()
    return {"enabled": settings_row.automod_enabled, "blacklist_action": payload.blacklist_action}


@app.post("/api/guilds/{guild_id}/automod/rules")
async def create_automod_rule(request: Request, guild_id: int, payload: AutoModRuleInput, session: AsyncSession = Depends(get_session)):
    if request.headers.get("x-csrf-token") != request.session.get("csrf"):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    await authorized_guild(request, guild_id)
    name = " ".join(payload.name.split())
    if not name:
        raise HTTPException(status_code=422, detail="Rule name cannot be empty")
    if len(name) > 120:
        raise HTTPException(status_code=422, detail="Rule name is too long")
    if payload.rule_type not in RULE_TYPES:
        raise HTTPException(status_code=422, detail="Invalid rule type")
    if payload.action not in ACTIONS:
        raise HTTPException(status_code=422, detail="Invalid action")
    errors = validate_rule_config(payload.rule_type, payload.config)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    existing = await session.execute(select(AutoModRule).where(AutoModRule.guild_id == guild_id, func.lower(AutoModRule.name) == name.casefold()))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="A rule with this name already exists")
    if any(value <= 0 for value in payload.channel_ids + payload.role_ids):
        raise HTTPException(status_code=422, detail="IDs must be positive")
    now = datetime.now(timezone.utc)
    row = AutoModRule(guild_id=guild_id, name=name, rule_type=payload.rule_type, action=payload.action, enabled=payload.enabled, priority=payload.priority, channel_ids=payload.channel_ids, role_ids=payload.role_ids, config=payload.config, created_at=now, updated_at=now)
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A rule with this name already exists") from None
    await _dashboard_audit(request, session, guild_id, "automod.rule_create", f"rule:{row.id}", None, _automod_rule_json(row))
    await session.commit()
    return _automod_rule_json(row)


@app.patch("/api/guilds/{guild_id}/automod/rules/{rule_id}")
async def patch_automod_rule(request: Request, guild_id: int, rule_id: int, payload: AutoModRulePatch, session: AsyncSession = Depends(get_session)):
    if request.headers.get("x-csrf-token") != request.session.get("csrf"):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    await authorized_guild(request, guild_id)
    row = await session.get(AutoModRule, rule_id)
    if row is None or row.guild_id != guild_id:
        raise HTTPException(status_code=404, detail="Rule not found")
    if payload.action is not None:
        if payload.action not in ACTIONS:
            raise HTTPException(status_code=422, detail="Invalid action")
        row.action = payload.action
    if payload.config is not None:
        errors = validate_rule_config(row.rule_type, payload.config)
        if errors:
            raise HTTPException(status_code=422, detail="; ".join(errors))
        row.config = payload.config
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.priority is not None:
        row.priority = payload.priority
    if payload.channel_ids is not None:
        row.channel_ids = payload.channel_ids
    if payload.role_ids is not None:
        row.role_ids = payload.role_ids
    if any(value <= 0 for value in (row.channel_ids or []) + (row.role_ids or [])):
        raise HTTPException(status_code=422, detail="IDs must be positive")
    row.updated_at = datetime.now(timezone.utc)
    await _dashboard_audit(request, session, guild_id, "automod.rule_update", f"rule:{row.id}", None, _automod_rule_json(row))
    await session.commit()
    return _automod_rule_json(row)


@app.delete("/api/guilds/{guild_id}/automod/rules/{rule_id}")
async def delete_automod_rule(request: Request, guild_id: int, rule_id: int, session: AsyncSession = Depends(get_session)):
    if request.headers.get("x-csrf-token") != request.session.get("csrf"):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    await authorized_guild(request, guild_id)
    row = await session.get(AutoModRule, rule_id)
    if row is None or row.guild_id != guild_id:
        raise HTTPException(status_code=404, detail="Rule not found")
    await session.delete(row)
    await _dashboard_audit(request, session, guild_id, "automod.rule_delete", f"rule:{rule_id}")
    await session.commit()
    return {"deleted": rule_id}


@app.post("/api/guilds/{guild_id}/automod/lists")
async def create_automod_list(request: Request, guild_id: int, payload: AutoModListInput, session: AsyncSession = Depends(get_session)):
    if request.headers.get("x-csrf-token") != request.session.get("csrf"):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    await authorized_guild(request, guild_id)
    if payload.list_type not in {"whitelist", "blacklist"} or payload.entry_type not in {"user", "channel", "role", "word", "domain"}:
        raise HTTPException(status_code=422, detail="Invalid list or entry type")
    value = payload.value.casefold() if payload.entry_type in {"word", "domain"} else payload.value.strip()
    if payload.entry_type in {"user", "channel", "role"} and (not value.isdigit() or int(value) <= 0):
        raise HTTPException(status_code=422, detail="ID value must be positive")
    existing = await session.execute(select(AutoModListEntry).where(AutoModListEntry.guild_id == guild_id, AutoModListEntry.list_type == payload.list_type, AutoModListEntry.entry_type == payload.entry_type, AutoModListEntry.value == value))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="List entry already exists")
    now = datetime.now(timezone.utc)
    row = AutoModListEntry(guild_id=guild_id, list_type=payload.list_type, entry_type=payload.entry_type, value=value, reason=payload.reason, created_at=now, updated_at=now)
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="List entry already exists") from None
    await _dashboard_audit(request, session, guild_id, "automod.list_add", f"{row.list_type}:{row.entry_type}:{row.value}", None, {"reason": row.reason})
    await session.commit()
    return {"id": row.id, "list_type": row.list_type, "entry_type": row.entry_type, "value": row.value, "reason": row.reason}


@app.delete("/api/guilds/{guild_id}/automod/lists/{entry_id}")
async def delete_automod_list(request: Request, guild_id: int, entry_id: int, session: AsyncSession = Depends(get_session)):
    if request.headers.get("x-csrf-token") != request.session.get("csrf"):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    await authorized_guild(request, guild_id)
    row = await session.get(AutoModListEntry, entry_id)
    if row is None or row.guild_id != guild_id:
        raise HTTPException(status_code=404, detail="List entry not found")
    await session.delete(row)
    await _dashboard_audit(request, session, guild_id, "automod.list_remove", f"{row.list_type}:{row.entry_type}:{row.value}")
    await session.commit()
    return {"deleted": entry_id}


class CommunityStatusInput(BaseModel):
    status: str = Field(min_length=1, max_length=30)
    note: str | None = Field(default=None, max_length=2000)


@app.get("/api/guilds/{guild_id}/community")
async def api_community(request: Request, guild_id: int, session: AsyncSession = Depends(get_session)):
    await authorized_guild(request, guild_id)
    tickets = list((await session.execute(select(Ticket).where(Ticket.guild_id == guild_id).order_by(Ticket.created_at.desc()).limit(100))).scalars())
    suggestions = list((await session.execute(select(Suggestion).where(Suggestion.guild_id == guild_id).order_by(Suggestion.created_at.desc()).limit(100))).scalars())
    reports = list((await session.execute(select(Report).where(Report.guild_id == guild_id).order_by(Report.created_at.desc()).limit(100))).scalars())
    giveaways = list((await session.execute(select(Giveaway).where(Giveaway.guild_id == guild_id).order_by(Giveaway.ends_at.desc()).limit(100))).scalars())
    polls = list((await session.execute(select(Poll).where(Poll.guild_id == guild_id).order_by(Poll.ends_at.desc()).limit(100))).scalars())
    giveaway_counts = {int(giveaway_id): int(count) for giveaway_id, count in (await session.execute(select(GiveawayEntry.giveaway_id, func.count(GiveawayEntry.id)).where(GiveawayEntry.giveaway_id.in_([row.id for row in giveaways]) if giveaways else False).group_by(GiveawayEntry.giveaway_id))).all()}
    poll_counts = {int(poll_id): int(count) for poll_id, count in (await session.execute(select(PollVote.poll_id, func.count(PollVote.id)).where(PollVote.poll_id.in_([row.id for row in polls]) if polls else False).group_by(PollVote.poll_id))).all()}
    return {
        "tickets": [{"id": row.id, "channel_id": row.channel_id, "opener_id": row.opener_id, "assignee_id": row.assignee_id, "category": row.category, "priority": row.priority, "status": row.status, "reason": row.reason, "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()} for row in tickets],
        "suggestions": [{"id": row.id, "author_id": row.author_id, "channel_id": row.channel_id, "content": row.content, "status": row.status, "upvotes": row.upvotes, "downvotes": row.downvotes, "staff_note": row.staff_note, "created_at": row.created_at.isoformat()} for row in suggestions],
        "reports": [{"id": row.id, "reporter_id": row.reporter_id, "reported_id": row.reported_id, "reason": row.reason, "evidence": row.evidence, "status": row.status, "resolver_id": row.resolver_id, "resolution": row.resolution, "created_at": row.created_at.isoformat()} for row in reports],
        "giveaways": [{"id": row.id, "channel_id": row.channel_id, "prize": row.prize, "winners": row.winners, "ends_at": row.ends_at.isoformat(), "requirements": row.requirements or {}, "status": row.status, "message_id": row.message_id, "entrants": giveaway_counts.get(row.id, 0)} for row in giveaways],
        "polls": [{"id": row.id, "channel_id": row.channel_id, "question": row.question, "options": row.options, "ends_at": row.ends_at.isoformat(), "status": row.status, "message_id": row.message_id, "votes": poll_counts.get(row.id, 0)} for row in polls],
    }


@app.patch("/api/guilds/{guild_id}/suggestions/{suggestion_id}")
async def dashboard_suggestion_status(request: Request, guild_id: int, suggestion_id: int, payload: CommunityStatusInput, session: AsyncSession = Depends(get_session)):
    if request.headers.get("x-csrf-token") != request.session.get("csrf"):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    await authorized_guild(request, guild_id)
    row = await session.get(Suggestion, suggestion_id)
    if row is None or row.guild_id != guild_id:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if payload.status not in {"pending", "analysis", "approved", "rejected", "implemented"}:
        raise HTTPException(status_code=422, detail="Invalid suggestion status")
    before = {"status": row.status, "staff_note": row.staff_note}
    row.status = payload.status
    row.staff_note = payload.note
    row.updated_at = datetime.now(timezone.utc)
    await _dashboard_audit(request, session, guild_id, "suggestion.status_update", f"suggestion:{suggestion_id}", before, {"status": row.status, "staff_note": row.staff_note})
    await session.commit()
    return {"id": row.id, "status": row.status, "staff_note": row.staff_note}


@app.patch("/api/guilds/{guild_id}/reports/{report_id}")
async def dashboard_report_status(request: Request, guild_id: int, report_id: int, payload: CommunityStatusInput, session: AsyncSession = Depends(get_session)):
    if request.headers.get("x-csrf-token") != request.session.get("csrf"):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    await authorized_guild(request, guild_id)
    row = await session.get(Report, report_id)
    if row is None or row.guild_id != guild_id:
        raise HTTPException(status_code=404, detail="Report not found")
    if payload.status not in {"open", "investigating", "resolved", "rejected"}:
        raise HTTPException(status_code=422, detail="Invalid report status")
    before = {"status": row.status, "resolver_id": row.resolver_id, "resolution": row.resolution}
    row.status = payload.status
    row.resolver_id = int((request.session.get("user") or {}).get("id", 0))
    row.resolution = payload.note
    row.updated_at = datetime.now(timezone.utc)
    await _dashboard_audit(request, session, guild_id, "report.status_update", f"report:{report_id}", before, {"status": row.status, "resolver_id": row.resolver_id, "resolution": row.resolution})
    await session.commit()
    return {"id": row.id, "status": row.status, "resolver_id": row.resolver_id, "resolution": row.resolution}


@app.patch("/api/guilds/{guild_id}/tickets/{ticket_id}")
async def dashboard_ticket_status(request: Request, guild_id: int, ticket_id: int, payload: CommunityStatusInput, session: AsyncSession = Depends(get_session)):
    if request.headers.get("x-csrf-token") != request.session.get("csrf"):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    await authorized_guild(request, guild_id)
    row = await session.get(Ticket, ticket_id)
    if row is None or row.guild_id != guild_id:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if payload.status not in {"open", "closed"}:
        raise HTTPException(status_code=422, detail="Invalid ticket status")
    before = {"status": row.status, "assignee_id": row.assignee_id}
    row.status = payload.status
    row.assignee_id = int((request.session.get("user") or {}).get("id", 0)) if payload.status == "closed" else row.assignee_id
    row.updated_at = datetime.now(timezone.utc)
    session.add(TicketEvent(id=secrets.randbits(62), ticket_id=row.id, actor_id=int((request.session.get("user") or {}).get("id", 0)), event_type=payload.status, data={"source": "dashboard", "note": payload.note}, created_at=datetime.now(timezone.utc)))
    await _dashboard_audit(request, session, guild_id, "ticket.status_update", f"ticket:{ticket_id}", before, {"status": row.status, "assignee_id": row.assignee_id})
    await session.commit()
    return {"id": row.id, "status": row.status, "assignee_id": row.assignee_id}
