from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import GuildPermission


async def allowed(session: AsyncSession, guild_id: int, user_id: int, permission: str, role_ids: set[int] | None = None) -> bool:
    role_ids = role_ids or set()
    result = await session.execute(
        select(GuildPermission)
        .where(GuildPermission.guild_id == guild_id, GuildPermission.permission == permission)
        .order_by(GuildPermission.id.desc())
    )
    rules = list(result.scalars())
    user_rules = [r for r in rules if r.subject_type == "user" and r.subject_id == user_id]
    if user_rules:
        return user_rules[0].allowed
    role_rules = [r for r in rules if r.subject_type == "role" and r.subject_id in role_ids]
    if not role_rules:
        return False
    return role_rules[0].allowed
