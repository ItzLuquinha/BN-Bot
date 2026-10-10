import secrets
from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import cast, func, literal, or_, select, union_all, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import SystemRole
from api.database import get_db
from api.dependencies import get_current_user, require_guild_manager, require_system_moderator
from app.models import (
    AuditLog,
    AutoModEvent,
    AutoModListEntry,
    AutoModRule,
    Experience,
    Guild,
    GuildSettings,
    Member,
    ModerationLog,
    User,
)
from app.repositories.analytics import overview
from app.services.automod import ACTIONS, DEFAULT_RULES, RULE_TYPES, validate_rule_config

router = APIRouter()
SUPPORTED_LOCALES = {"pt-BR", "en-US"}


class GuildSettingsUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    locale: str | None = Field(default=None, min_length=2, max_length=16)
    economy_enabled: bool | None = None
    levels_enabled: bool | None = None
    analytics_enabled: bool | None = None
    automod_enabled: bool | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("timezone não pode ficar vazio")
        try:
            ZoneInfo(normalized)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("timezone deve ser um fuso horário IANA válido") from None
        return normalized

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized not in SUPPORTED_LOCALES:
            raise ValueError("locale deve ser pt-BR ou en-US")
        return normalized


class GuildStatusUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    reason: str | None = Field(default=None, max_length=500)


class AutoModRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    enabled: bool
    action: str = Field(min_length=1, max_length=20)
    priority: int = Field(ge=-10000, le=10000)
    channel_ids: list[int] = Field(default_factory=list, max_length=100)
    role_ids: list[int] = Field(default_factory=list, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)


class AutoModUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    blacklist_action: str = Field(default="delete", min_length=1, max_length=20)
    rules: list[AutoModRuleUpdate] | None = Field(default=None, max_length=200)


class AutoModRuleCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    rule_type: str = Field(min_length=1, max_length=40)
    action: str = Field(default="delete", min_length=1, max_length=20)
    enabled: bool = True
    priority: int = Field(default=0, ge=-10000, le=10000)
    channel_ids: list[int] = Field(default_factory=list, max_length=100)
    role_ids: list[int] = Field(default_factory=list, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)


class AutoModListCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    list_type: Literal["whitelist", "blacklist"]
    entry_type: Literal["user", "channel", "role", "word", "domain"]
    value: str = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, max_length=500)


def _guild_json(guild: Guild) -> dict[str, Any]:
    return {
        "id": str(guild.id),
        "name": guild.name,
        "icon_url": guild.icon_url,
        "owner_id": str(guild.owner_id) if guild.owner_id else None,
        "active": guild.active,
        "created_at": guild.created_at.isoformat() if guild.created_at else None,
        "updated_at": guild.updated_at.isoformat() if guild.updated_at else None,
    }


def _rule_json(rule: AutoModRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "action": rule.action,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "channel_ids": rule.channel_ids or [],
        "role_ids": rule.role_ids or [],
        "config": rule.config or {},
    }


def _settings_json(settings: GuildSettings) -> dict[str, Any]:
    return {
        "guild_id": str(settings.guild_id),
        "timezone": settings.timezone,
        "locale": settings.locale,
        "economy_enabled": settings.economy_enabled,
        "levels_enabled": settings.levels_enabled,
        "analytics_enabled": settings.analytics_enabled,
        "automod_enabled": settings.automod_enabled,
        "config": settings.config or {},
        "created_at": settings.created_at.isoformat() if settings.created_at else None,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


async def _write_audit(
    db: AsyncSession,
    guild_id: int,
    user: dict[str, Any],
    action: str,
    resource: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    db.add(AuditLog(
        id=secrets.randbits(62),
        guild_id=guild_id,
        executor_id=int(user["id"]),
        action=action,
        resource=resource[:120],
        before_state=before,
        after_state=after,
        created_at=datetime.now(timezone.utc),
    ))


@router.get("", summary="Listar servidores acessíveis ao usuário")
async def list_guilds(db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    if user.get("system_role") == SystemRole.ADMIN.value:
        query = select(Guild).where(Guild.active.is_(True))
    else:
        user_id = int(user["id"])
        manageable_ids = [int(guild_id) for guild_id in user.get("guilds", []) if str(guild_id).isdigit()]
        scope = [Guild.owner_id == user_id]
        if manageable_ids:
            scope.append(Guild.id.in_(manageable_ids))
        query = select(Guild).where(Guild.active.is_(True), or_(*scope))
    result = await db.execute(query.order_by(Guild.name.asc(), Guild.id.asc()))
    return [_guild_json(guild) for guild in result.scalars().all()]


@router.get("/{guild_id}", summary="Obter detalhes de um servidor")
async def get_guild(guild_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    guild = await db.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servidor não encontrado")
    return _guild_json(guild)


@router.get("/{guild_id}/overview", summary="Resumo de atividade do servidor")
async def get_guild_overview(guild_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    return await overview(db, guild_id)


@router.get("/{guild_id}/settings", summary="Obter configurações do servidor")
async def get_guild_settings(guild_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    settings = await db.get(GuildSettings, guild_id)
    if settings is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configurações deste servidor ainda não foram inicializadas")
    return _settings_json(settings)


@router.patch("/{guild_id}/settings", summary="Atualizar configurações do servidor")
async def update_guild_settings(
    guild_id: int,
    payload: GuildSettingsUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    settings = await db.get(GuildSettings, guild_id)
    if settings is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configurações deste servidor ainda não foram inicializadas")
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe ao menos uma configuração para atualizar")
    before = {field: getattr(settings, field) for field in changes}
    for field, value in changes.items():
        setattr(settings, field, value)
    settings.updated_at = datetime.now(timezone.utc)
    after = {field: getattr(settings, field) for field in changes}
    await _write_audit(db, guild_id, user, "guild.settings_update", "settings", before, after)
    await db.commit()
    await db.refresh(settings)
    return _settings_json(settings)


@router.get("/{guild_id}/members", summary="Listar membros e experiência")
async def list_members(
    guild_id: int,
    page: int = Query(default=1, ge=1, le=100000),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    base = select(Member, User, Experience).join(User, User.id == Member.user_id).outerjoin(
        Experience, (Experience.guild_id == Member.guild_id) & (Experience.user_id == Member.user_id)
    ).where(Member.guild_id == guild_id, Member.left_at.is_(None))
    count_result = await db.execute(select(func.count(Member.id)).where(Member.guild_id == guild_id, Member.left_at.is_(None)))
    total = int(count_result.scalar_one() or 0)
    result = await db.execute(base.order_by(Member.activity_score.desc(), Member.user_id.asc()).offset((page - 1) * page_size).limit(page_size))
    items = []
    for member, profile, experience in result.all():
        items.append({
            "user_id": str(member.user_id),
            "username": profile.username,
            "display_name": profile.display_name,
            "avatar_url": profile.avatar_url,
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
            "messages": member.message_count,
            "voice_seconds": member.voice_seconds,
            "activity": member.activity_score,
            "level": experience.level if experience else None,
            "xp": experience.total_xp if experience else None,
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{guild_id}/audit", summary="Listar logs de auditoria e moderação")
async def list_audit_logs(
    guild_id: int,
    page: int = Query(default=1, ge=1, le=100000),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    moderation = select(
        cast(ModerationLog.id, String).label("id"),
        ModerationLog.created_at.label("created_at"),
        ModerationLog.kind.label("kind"),
        cast(ModerationLog.actor_id, String).label("actor_id"),
        cast(ModerationLog.target_id, String).label("target_id"),
        ModerationLog.reason.label("reason"),
        literal("moderação").label("source"),
    ).where(ModerationLog.guild_id == guild_id)
    audit = select(
        cast(AuditLog.id, String).label("id"),
        AuditLog.created_at.label("created_at"),
        AuditLog.action.label("kind"),
        cast(AuditLog.executor_id, String).label("actor_id"),
        cast(AuditLog.resource, String).label("target_id"),
        literal(None, type_=String).label("reason"),
        literal("auditoria").label("source"),
    ).where(AuditLog.guild_id == guild_id)
    automod = select(
        cast(AutoModEvent.id, String).label("id"),
        AutoModEvent.created_at.label("created_at"),
        AutoModEvent.rule_type.label("kind"),
        literal(None, type_=String).label("actor_id"),
        cast(AutoModEvent.user_id, String).label("target_id"),
        AutoModEvent.reason.label("reason"),
        literal("automod").label("source"),
    ).where(AutoModEvent.guild_id == guild_id)
    events = union_all(moderation, audit, automod).subquery("guild_audit_events")
    total_result = await db.execute(select(func.count()).select_from(events))
    total = int(total_result.scalar_one() or 0)
    result = await db.execute(
        select(events)
        .order_by(events.c.created_at.desc(), events.c.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    for row in result.mappings().all():
        created_at = row["created_at"]
        items.append({
            "id": row["id"],
            "created_at": created_at.isoformat() if created_at else None,
            "kind": row["kind"],
            "actor_id": row["actor_id"],
            "target_id": row["target_id"],
            "reason": row["reason"],
            "source": row["source"],
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{guild_id}/automod", summary="Ler configuração real do AutoMod")
async def get_automod(guild_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    settings = await db.get(GuildSettings, guild_id)
    if settings is None:
        return {"configured": False, "rules": [], "lists": []}
    rules_result = await db.execute(select(AutoModRule).where(AutoModRule.guild_id == guild_id).order_by(AutoModRule.priority.desc(), AutoModRule.id.asc()))
    entries_result = await db.execute(select(AutoModListEntry).where(AutoModListEntry.guild_id == guild_id).order_by(AutoModListEntry.list_type.asc(), AutoModListEntry.entry_type.asc(), AutoModListEntry.value.asc()))
    automod_config = dict((settings.config or {}).get("automod", {}))
    entries = entries_result.scalars().all()
    return {
        "configured": True,
        "enabled": settings.automod_enabled,
        "blacklist_action": automod_config.get("blacklist_action", "delete"),
        "rules": [_rule_json(rule) for rule in rules_result.scalars().all()],
        "lists": [{"id": row.id, "list_type": row.list_type, "entry_type": row.entry_type, "value": row.value, "reason": row.reason} for row in entries],
    }


@router.post("/{guild_id}/automod/setup", summary="Criar regras iniciais sem remover regras existentes")
async def setup_automod(guild_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    guild = await db.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servidor não encontrado")
    now = datetime.now(timezone.utc)
    settings = await db.get(GuildSettings, guild_id)
    if settings is None:
        settings = GuildSettings(
            guild_id=guild_id,
            timezone="UTC",
            locale="pt-BR",
            economy_enabled=True,
            levels_enabled=True,
            analytics_enabled=True,
            automod_enabled=True,
            config={"automod": {"blacklist_action": "delete"}},
            created_at=now,
            updated_at=now,
        )
        db.add(settings)
    else:
        config = dict(settings.config or {})
        automod_config = dict(config.get("automod", {}))
        automod_config.setdefault("blacklist_action", "delete")
        config["automod"] = automod_config
        settings.config = config
        settings.automod_enabled = True
        settings.updated_at = now
    existing_result = await db.execute(select(AutoModRule.name).where(AutoModRule.guild_id == guild_id))
    existing_names = {str(name).casefold() for name in existing_result.scalars().all()}
    created = 0
    for definition in DEFAULT_RULES:
        name = str(definition["name"]).strip()
        if name.casefold() in existing_names:
            continue
        db.add(AutoModRule(
            guild_id=guild_id,
            name=name,
            rule_type=definition["rule_type"],
            action=definition["action"],
            enabled=True,
            priority=definition["priority"],
            channel_ids=[],
            role_ids=[],
            config=dict(definition["config"]),
            created_at=now,
            updated_at=now,
        ))
        created += 1
    await _write_audit(db, guild_id, user, "automod.setup", "rules", None, {"created": created})
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A configuração inicial foi alterada em paralelo. Atualize a tela e tente novamente.") from None
    return await get_automod(guild_id, db, user)


@router.put("/{guild_id}/automod", summary="Salvar AutoMod e regras atomicamente")
async def update_automod(
    guild_id: int,
    payload: AutoModUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    if payload.blacklist_action not in ACTIONS - {"none"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A ação da blacklist é inválida")
    if payload.rules is not None and len({rule.id for rule in payload.rules}) != len(payload.rules):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Há IDs de regras repetidos na solicitação")
    settings = await db.get(GuildSettings, guild_id)
    if settings is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inicialize o AutoMod antes de salvar configurações")
    current_config = dict(settings.config or {})
    automod_config = dict(current_config.get("automod", {}))
    previous = {"enabled": settings.automod_enabled, "blacklist_action": automod_config.get("blacklist_action", "delete")}
    new_rule_values: list[tuple[AutoModRule, AutoModRuleUpdate]] = []
    if payload.rules is not None:
        rule_ids = [rule.id for rule in payload.rules]
        rows_result = await db.execute(select(AutoModRule).where(AutoModRule.guild_id == guild_id, AutoModRule.id.in_(rule_ids)))
        rows_by_id = {row.id: row for row in rows_result.scalars().all()}
        if set(rows_by_id) != set(rule_ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uma ou mais regras não existem neste servidor")
        for update in payload.rules:
            row = rows_by_id[update.id]
            if update.action not in ACTIONS:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Ação inválida na regra {row.name}")
            if any(item <= 0 for item in update.channel_ids + update.role_ids):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="IDs de canais e cargos devem ser positivos")
            errors = validate_rule_config(row.rule_type, update.config)
            if errors:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Configuração inválida em {row.name}: {'; '.join(errors)}")
            new_rule_values.append((row, update))
    settings.automod_enabled = payload.enabled
    automod_config["blacklist_action"] = payload.blacklist_action
    current_config["automod"] = automod_config
    settings.config = current_config
    settings.updated_at = datetime.now(timezone.utc)
    for row, update in new_rule_values:
        row.enabled = update.enabled
        row.action = update.action
        row.priority = update.priority
        row.channel_ids = update.channel_ids
        row.role_ids = update.role_ids
        row.config = update.config
        row.updated_at = settings.updated_at
    after = {"enabled": payload.enabled, "blacklist_action": payload.blacklist_action, "updated_rules": [row.id for row, _ in new_rule_values]}
    await _write_audit(db, guild_id, user, "automod.settings_update", "settings", previous, after)
    await db.commit()
    return await get_automod(guild_id, db, user)


@router.post("/{guild_id}/automod/rules", summary="Criar uma regra AutoMod")
async def create_automod_rule(
    guild_id: int,
    payload: AutoModRuleCreateSchema,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    name = " ".join(payload.name.split())
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="O nome da regra não pode ficar vazio")
    if payload.rule_type not in RULE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Tipo de regra inválido")
    if payload.action not in ACTIONS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ação inválida")
    errors = validate_rule_config(payload.rule_type, payload.config)
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))
    if any(item <= 0 for item in payload.channel_ids + payload.role_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="IDs de canais e cargos devem ser positivos")
    existing = await db.scalar(select(AutoModRule.id).where(AutoModRule.guild_id == guild_id, func.lower(AutoModRule.name) == name.casefold()).limit(1))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma regra com este nome")
    now = datetime.now(timezone.utc)
    row = AutoModRule(guild_id=guild_id, name=name, rule_type=payload.rule_type, action=payload.action, enabled=payload.enabled, priority=payload.priority, channel_ids=payload.channel_ids, role_ids=payload.role_ids, config=payload.config, created_at=now, updated_at=now)
    db.add(row)
    try:
        await db.flush()
        await _write_audit(db, guild_id, user, "automod.rule_create", f"rule:{row.id}", None, _rule_json(row))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma regra com este nome") from None
    return _rule_json(row)


@router.patch("/{guild_id}/automod/rules/{rule_id}", summary="Atualizar uma regra AutoMod")
async def patch_automod_rule(
    guild_id: int,
    rule_id: int,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    allowed_fields = {"enabled", "action", "priority", "channel_ids", "role_ids", "config"}
    if not payload or set(payload) - allowed_fields:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Campos de atualização inválidos")
    row = await db.get(AutoModRule, rule_id)
    if row is None or row.guild_id != guild_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regra não encontrada neste servidor")
    update = AutoModRuleUpdate.model_validate({
        "id": rule_id,
        "enabled": payload.get("enabled", row.enabled),
        "action": payload.get("action", row.action),
        "priority": payload.get("priority", row.priority),
        "channel_ids": payload.get("channel_ids", row.channel_ids or []),
        "role_ids": payload.get("role_ids", row.role_ids or []),
        "config": payload.get("config", row.config or {}),
    })
    if update.action not in ACTIONS or any(item <= 0 for item in update.channel_ids + update.role_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ação ou IDs inválidos")
    errors = validate_rule_config(row.rule_type, update.config)
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))
    before = _rule_json(row)
    row.enabled = update.enabled
    row.action = update.action
    row.priority = update.priority
    row.channel_ids = update.channel_ids
    row.role_ids = update.role_ids
    row.config = update.config
    row.updated_at = datetime.now(timezone.utc)
    await _write_audit(db, guild_id, user, "automod.rule_update", f"rule:{rule_id}", before, _rule_json(row))
    await db.commit()
    return _rule_json(row)


@router.delete("/{guild_id}/automod/rules/{rule_id}", summary="Excluir uma regra AutoMod")
async def delete_automod_rule(guild_id: int, rule_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    row = await db.get(AutoModRule, rule_id)
    if row is None or row.guild_id != guild_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regra não encontrada neste servidor")
    await _write_audit(db, guild_id, user, "automod.rule_delete", f"rule:{rule_id}", _rule_json(row), None)
    await db.delete(row)
    await db.commit()
    return {"deleted": rule_id}


@router.post("/{guild_id}/automod/lists", summary="Adicionar entrada à whitelist ou blacklist")
async def create_automod_list(guild_id: int, payload: AutoModListCreateSchema, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    value = payload.value.casefold().strip() if payload.entry_type in {"word", "domain"} else payload.value.strip()
    if not value:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="O valor não pode ficar vazio")
    if payload.entry_type in {"user", "channel", "role"} and (not value.isdigit() or int(value) <= 0):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="O ID deve ser um número positivo")
    existing = await db.scalar(select(AutoModListEntry.id).where(AutoModListEntry.guild_id == guild_id, AutoModListEntry.list_type == payload.list_type, AutoModListEntry.entry_type == payload.entry_type, AutoModListEntry.value == value).limit(1))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta entrada já existe")
    now = datetime.now(timezone.utc)
    row = AutoModListEntry(guild_id=guild_id, list_type=payload.list_type, entry_type=payload.entry_type, value=value, reason=payload.reason, created_at=now, updated_at=now)
    db.add(row)
    try:
        await db.flush()
        await _write_audit(db, guild_id, user, "automod.list_add", f"{row.list_type}:{row.entry_type}", None, {"value": row.value, "reason": row.reason})
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta entrada já existe") from None
    return {"id": row.id, "list_type": row.list_type, "entry_type": row.entry_type, "value": row.value, "reason": row.reason}


@router.delete("/{guild_id}/automod/lists/{entry_id}", summary="Excluir entrada de lista AutoMod")
async def delete_automod_list(guild_id: int, entry_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    row = await db.get(AutoModListEntry, entry_id)
    if row is None or row.guild_id != guild_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrada não encontrada neste servidor")
    await _write_audit(db, guild_id, user, "automod.list_delete", f"{row.list_type}:{row.entry_type}", {"value": row.value}, None)
    await db.delete(row)
    await db.commit()
    return {"deleted": entry_id}


@router.get("/{guild_id}/status", summary="Consultar disponibilidade do servidor para a equipe")
async def get_guild_status(guild_id: int, db: AsyncSession = Depends(get_db), moderator: dict = Depends(require_system_moderator)):
    guild = await db.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servidor não encontrado")
    return {"guild_id": str(guild.id), "active": guild.active}


@router.patch("/{guild_id}/status", summary="Moderação global: ativar ou desativar servidor")
async def toggle_guild_status(
    guild_id: int,
    payload: GuildStatusUpdateSchema,
    db: AsyncSession = Depends(get_db),
    moderator: dict = Depends(require_system_moderator),
):
    guild = await db.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servidor não encontrado")
    previous_active = guild.active
    guild.active = payload.active
    guild.updated_at = datetime.now(timezone.utc)
    await _write_audit(db, guild_id, moderator, "guild.status_update", "guild", {"active": previous_active}, {"active": guild.active, "reason": payload.reason})
    await db.commit()
    await db.refresh(guild)
    return {"guild_id": str(guild.id), "active": guild.active, "updated_at": guild.updated_at.isoformat(), "action_by": moderator.get("username", moderator["id"]), "reason": payload.reason}


@router.get("/{guild_id}/economy", summary="Listar saldos de economia")
async def list_economy(guild_id: int, page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100), db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    from app.models import EconomyAccount

    count = await db.scalar(select(func.count(EconomyAccount.id)).where(EconomyAccount.guild_id == guild_id))
    result = await db.execute(select(EconomyAccount).where(EconomyAccount.guild_id == guild_id).order_by((EconomyAccount.wallet + EconomyAccount.bank).desc()).offset((page - 1) * page_size).limit(page_size))
    items = [{"user_id": str(row.user_id), "wallet": str(row.wallet), "bank": str(row.bank), "total": str(row.wallet + row.bank)} for row in result.scalars().all()]
    return {"items": items, "total": int(count or 0), "page": page, "page_size": page_size}


@router.get("/{guild_id}/levels", summary="Listar níveis e experiência")
async def list_levels(guild_id: int, page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100), db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    count = await db.scalar(select(func.count(Experience.id)).where(Experience.guild_id == guild_id))
    result = await db.execute(select(Experience).where(Experience.guild_id == guild_id).order_by(Experience.total_xp.desc()).offset((page - 1) * page_size).limit(page_size))
    items = [{"user_id": str(row.user_id), "level": row.level, "xp": row.total_xp} for row in result.scalars().all()]
    return {"items": items, "total": int(count or 0), "page": page, "page_size": page_size}


@router.get("/{guild_id}/moderation", summary="Listar casos de moderação")
async def list_moderation_cases(guild_id: int, page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100), db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    count = await db.scalar(select(func.count(ModerationLog.id)).where(ModerationLog.guild_id == guild_id))
    result = await db.execute(select(ModerationLog).where(ModerationLog.guild_id == guild_id).order_by(ModerationLog.created_at.desc(), ModerationLog.id.desc()).offset((page - 1) * page_size).limit(page_size))
    items = [{"id": str(row.id), "created_at": row.created_at.isoformat() if row.created_at else None, "kind": row.kind, "actor_id": str(row.actor_id), "target_id": str(row.target_id) if row.target_id is not None else None, "reason": row.reason, "data": row.data or {}} for row in result.scalars().all()]
    return {"items": items, "total": int(count or 0), "page": page, "page_size": page_size}
