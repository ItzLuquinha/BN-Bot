from decimal import Decimal
from datetime import date, timedelta
import secrets
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import CooldownActive
from app.core.time import local_now, utc_now
from app.models import GuildSettings, RewardClaim
from app.repositories.economy import add_wallet

async def claim_reward(session: AsyncSession, guild_id: int, user_id: int, kind: str, base_amount: Decimal) -> tuple[Decimal, int]:
    settings = await session.get(GuildSettings, guild_id)
    tz_name = settings.timezone if settings else "UTC"
    local = local_now(tz_name)
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
        raise CooldownActive(86400 if kind == "daily" else 604800)
    last = await session.execute(select(RewardClaim).where(RewardClaim.guild_id == guild_id, RewardClaim.user_id == user_id, RewardClaim.kind == kind).order_by(RewardClaim.claimed_at.desc()).limit(1).with_for_update())
    previous_claim = last.scalar_one_or_none()
    streak = previous_claim.streak + 1 if previous_claim and previous_claim.claim_key == previous_key else 1
    bonus_multiplier = min(Decimal("1") + Decimal(max(streak - 1, 0)) * Decimal("0.05"), Decimal("2.0"))
    amount = (base_amount * bonus_multiplier).quantize(Decimal("0.01"))
    session.add(RewardClaim(id=secrets.randbits(62), guild_id=guild_id, user_id=user_id, kind=kind, claim_key=claim_key, streak=streak, amount=amount, claimed_at=utc_now()))
    await add_wallet(session, guild_id, user_id, amount, kind, f"streak:{streak}")
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        raise CooldownActive(86400 if kind == "daily" else 604800) from exc
    return amount, streak
