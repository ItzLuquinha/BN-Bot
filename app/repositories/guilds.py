from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Guild, GuildSettings, User, Member

def now() -> datetime:
    return datetime.now(timezone.utc)

async def ensure_guild(session: AsyncSession, guild_id: int, name: str, owner_id: int | None = None, icon_url: str | None = None) -> Guild:
    guild = await session.get(Guild, guild_id)
    current = now()
    if guild is None:
        guild = Guild(id=guild_id, name=name, owner_id=owner_id, icon_url=icon_url, created_at=current, updated_at=current)
        session.add(guild)
    else:
        guild.name = name
        guild.owner_id = owner_id
        guild.icon_url = icon_url
        guild.active = True
        guild.updated_at = current
    settings = await session.get(GuildSettings, guild_id)
    if settings is None:
        settings = GuildSettings(guild_id=guild_id, created_at=current, updated_at=current)
        session.add(settings)
    await session.flush()
    return guild

async def ensure_user(session: AsyncSession, user_id: int, username: str, display_name: str, avatar_url: str | None = None, banner_url: str | None = None, bot: bool = False) -> User:
    user = await session.get(User, user_id)
    current = now()
    if user is None:
        user = User(id=user_id, username=username, display_name=display_name, avatar_url=avatar_url, banner_url=banner_url, bot=bot, created_at=current, updated_at=current)
        session.add(user)
    else:
        user.username = username
        user.display_name = display_name
        user.avatar_url = avatar_url
        user.banner_url = banner_url
        user.bot = bot
        user.updated_at = current
    await session.flush()
    return user

async def ensure_member(session: AsyncSession, guild_id: int, user_id: int, joined_at: datetime | None) -> Member:
    result = await session.execute(select(Member).where(Member.guild_id == guild_id, Member.user_id == user_id))
    member = result.scalar_one_or_none()
    current = now()
    if member is None:
        member = Member(guild_id=guild_id, user_id=user_id, joined_at=joined_at, created_at=current, updated_at=current)
        session.add(member)
    elif joined_at is not None:
        member.joined_at = joined_at
        member.left_at = None
        member.updated_at = current
    await session.flush()
    return member
