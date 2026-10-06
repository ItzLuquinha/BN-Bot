from datetime import datetime, timezone
from sqlalchemy import select, func, desc
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Member, MessageLog, MemberActivity, ChannelActivity, EconomyAccount, Warning, Ticket, Report, Suggestion

async def overview(session: AsyncSession, guild_id: int) -> dict[str, int | float]:
    members = await session.scalar(select(func.count(Member.id)).where(Member.guild_id == guild_id, Member.left_at.is_(None)))
    messages = await session.scalar(select(func.count(MessageLog.id)).where(MessageLog.guild_id == guild_id))
    total_coins = await session.scalar(select(func.coalesce(func.sum(EconomyAccount.wallet + EconomyAccount.bank), 0)).where(EconomyAccount.guild_id == guild_id))
    warnings = await session.scalar(select(func.count(Warning.id)).where(Warning.guild_id == guild_id, Warning.active.is_(True)))
    tickets = await session.scalar(select(func.count(Ticket.id)).where(Ticket.guild_id == guild_id, Ticket.status == "open"))
    reports = await session.scalar(select(func.count(Report.id)).where(Report.guild_id == guild_id, Report.status == "open"))
    suggestions = await session.scalar(select(func.count(Suggestion.id)).where(Suggestion.guild_id == guild_id, Suggestion.status == "pending"))
    return {"members": int(members or 0), "messages": int(messages or 0), "economy": float(total_coins or 0), "warnings": int(warnings or 0), "tickets": int(tickets or 0), "reports": int(reports or 0), "pending_suggestions": int(suggestions or 0)}

async def record_message(session: AsyncSession, guild_id: int, user_id: int, channel_id: int, message_id: int, content_length: int, bucket_start: datetime) -> None:
    session.add(MessageLog(id=message_id, guild_id=guild_id, user_id=user_id, channel_id=channel_id, message_id=message_id, event="create", content_length=content_length, created_at=datetime.now(timezone.utc)))
    member = (await session.execute(select(Member).where(Member.guild_id == guild_id, Member.user_id == user_id).with_for_update())).scalar_one_or_none()
    if member:
        member.message_count += 1
        member.activity_score += 1
        member.updated_at = datetime.now(timezone.utc)
    member_activity_stmt = pg_insert(MemberActivity).values(guild_id=guild_id, user_id=user_id, bucket_start=bucket_start, metric="messages", value=1).on_conflict_do_update(index_elements=[MemberActivity.guild_id, MemberActivity.user_id, MemberActivity.bucket_start, MemberActivity.metric], set_={"value": MemberActivity.value + 1})
    await session.execute(member_activity_stmt)
    channel_activity_stmt = pg_insert(ChannelActivity).values(guild_id=guild_id, channel_id=channel_id, bucket_start=bucket_start, metric="messages", value=1).on_conflict_do_update(index_elements=[ChannelActivity.guild_id, ChannelActivity.channel_id, ChannelActivity.bucket_start, ChannelActivity.metric], set_={"value": ChannelActivity.value + 1})
    await session.execute(channel_activity_stmt)
