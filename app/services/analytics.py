from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import MemberActivity, ChannelActivity

async def activity_series(session: AsyncSession, guild_id: int, metric: str, days: int) -> list[dict[str, int | str]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await session.execute(select(MemberActivity.bucket_start, func.sum(MemberActivity.value)).where(MemberActivity.guild_id == guild_id, MemberActivity.metric == metric, MemberActivity.bucket_start >= since).group_by(MemberActivity.bucket_start).order_by(MemberActivity.bucket_start.asc()))
    return [{"bucket": bucket.isoformat(), "value": int(value)} for bucket, value in result.all()]

async def top_channels(session: AsyncSession, guild_id: int, metric: str, limit: int = 10, days: int | None = None) -> list[dict[str, int | str]]:
    filters = [ChannelActivity.guild_id == guild_id, ChannelActivity.metric == metric]
    if days is not None:
        filters.append(ChannelActivity.bucket_start >= datetime.now(timezone.utc) - timedelta(days=days))
    result = await session.execute(select(ChannelActivity.channel_id, func.sum(ChannelActivity.value).label("total")).where(*filters).group_by(ChannelActivity.channel_id).order_by(func.sum(ChannelActivity.value).desc()).limit(limit))
    return [{"channel_id": int(channel_id), "value": int(total)} for channel_id, total in result.all()]
