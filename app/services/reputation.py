from datetime import timedelta
import secrets
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import CooldownActive
from app.core.time import utc_now
from app.services.cooldowns import check_and_set
from app.models import Reputation, ReputationEvent

async def give_reputation(session: AsyncSession, guild_id: int, giver_id: int, receiver_id: int, reason: str | None = None) -> int:
    if giver_id == receiver_id:
        raise ValueError("cannot give reputation to yourself")
    key = f"bn:rep:{guild_id}:{giver_id}"
    cooldown = await check_and_set(key, 86400)
    if cooldown:
        raise CooldownActive(cooldown)
    for user_id in sorted((giver_id, receiver_id)):
        result = await session.execute(select(Reputation).where(Reputation.guild_id == guild_id, Reputation.user_id == user_id).with_for_update())
        row = result.scalar_one_or_none()
        if row is None:
            row = Reputation(guild_id=guild_id, user_id=user_id, score=0)
            session.add(row)
        if user_id == receiver_id:
            row.score += 1
    session.add(ReputationEvent(id=secrets.randbits(62), guild_id=guild_id, giver_id=giver_id, receiver_id=receiver_id, amount=1, reason=reason, created_at=utc_now()))
    await session.commit()
    return 1
