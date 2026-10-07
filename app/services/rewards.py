from decimal import Decimal
from datetime import date, datetime, time, timedelta, timezone
import secrets
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfoNotFoundError
import logging
from app.core.exceptions import CooldownActive
from app.core.time import local_now, utc_now
from app.models import GuildSettings, RewardClaim
from app.repositories.economy import add_wallet

logger = logging.getLogger("bn_bot.rewards")

def seconds_until_next_reward(kind: str, local: datetime) -> int:
    if kind == "daily":
        next_date = local.date() + timedelta(days=1)
    elif kind == "weekly":
        next_date = local.date() + timedelta(days=7 - local.weekday())
    else:
        raise ValueError("invalid reward kind")
    boundary = datetime.combine(next_date, time.min, tzinfo=local.tzinfo)
    seconds = int((boundary.astimezone(timezone.utc) - local.astimezone(timezone.utc)).total_seconds())
    return max(seconds, 1)

async def claim_reward(session: AsyncSession, guild_id: int, user_id: int, kind: str, base_amount: Decimal) -> tuple[Decimal, int]:
    if kind not in {"daily", "weekly"}:
        raise ValueError("invalid reward kind")
    settings = await session.get(GuildSettings, guild_id)
    tz_name = settings.timezone if settings else "UTC"
    try:
        local = local_now(tz_name)
    except ZoneInfoNotFoundError:
        logger.error("invalid guild timezone; falling back to UTC guild=%s timezone=%s", guild_id, tz_name)
        local = local_now("UTC")
    if kind == "daily":
        claim_key = local.date().isoformat()
        previous_key = (local.date() - timedelta(days=1)).isoformat()
    else:
        iso = local.isocalendar()
        claim_key = f"{iso.year}-W{iso.week:02d}"
        previous = local.date() - timedelta(days=7)
        previous_iso = previous.isocalendar()
        previous_key = f"{previous_iso.year}-W{previous_iso.week:02d}"
    existing = await session.execute(select(RewardClaim).where(RewardClaim.guild_id == guild_id, RewardClaim.user_id == user_id, RewardClaim.kind == kind, RewardClaim.claim_key == claim_key).with_for_update())
    if existing.scalar_one_or_none() is not None:
        raise CooldownActive(seconds_until_next_reward(kind, local))
    last = await session.execute(select(RewardClaim).where(RewardClaim.guild_id == guild_id, RewardClaim.user_id == user_id, RewardClaim.kind == kind).order_by(RewardClaim.claimed_at.desc()).limit(1).with_for_update())
    previous_claim = last.scalar_one_or_none()
    streak = previous_claim.streak + 1 if previous_claim and previous_claim.claim_key == previous_key else 1
    bonus_multiplier = min(Decimal("1") + Decimal(max(streak - 1, 0)) * Decimal("0.05"), Decimal("2.0"))
    amount = (base_amount * bonus_multiplier).quantize(Decimal("0.01"))
    try:
        async with session.begin_nested():
            session.add(RewardClaim(id=secrets.randbits(62), guild_id=guild_id, user_id=user_id, kind=kind, claim_key=claim_key, streak=streak, amount=amount, claimed_at=utc_now()))
            await session.flush()
            await add_wallet(session, guild_id, user_id, amount, kind, f"streak:{streak}")
    except IntegrityError as exc:
        raise CooldownActive(seconds_until_next_reward(kind, local)) from exc
    return amount, streak
