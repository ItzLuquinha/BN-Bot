from datetime import datetime, timezone
import secrets
from sqlalchemy import select, func, desc
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import CommandUsage, Member, MessageLog, MemberActivity, ChannelActivity, EconomyAccount, Warning, Ticket, Report, Suggestion

async def overview(session: AsyncSession, guild_id: int) -> dict[str, int | float]:
    members = await session.scalar(select(func.count(Member.id)).where(Member.guild_id == guild_id, Member.left_at.is_(None)))
    messages = await session.scalar(select(func.count(MessageLog.id)).where(MessageLog.guild_id == guild_id))
    total_coins = await session.scalar(select(func.coalesce(func.sum(EconomyAccount.wallet + EconomyAccount.bank), 0)).where(EconomyAccount.guild_id == guild_id))
    warnings = await session.scalar(select(func.count(Warning.id)).where(Warning.guild_id == guild_id, Warning.active.is_(True)))
    tickets = await session.scalar(select(func.count(Ticket.id)).where(Ticket.guild_id == guild_id, Ticket.status == "open"))
    reports = await session.scalar(select(func.count(Report.id)).where(Report.guild_id == guild_id, Report.status == "open"))
    suggestions = await session.scalar(select(func.count(Suggestion.id)).where(Suggestion.guild_id == guild_id, Suggestion.status == "pending"))
    return {"members": int(members or 0), "messages": int(messages or 0), "economy": float(total_coins or 0), "warnings": int(warnings or 0), "tickets": int(tickets or 0), "reports": int(reports or 0), "pending_suggestions": int(suggestions or 0)}


COMMAND_CATEGORIES = {
    "normal": {"ping", "uptime", "botinfo", "serverinfo", "userinfo", "avatar", "remind", "tutorial", "dashboard", "history", "donate"},
    "economia": {"balance", "bank", "deposit", "withdraw", "pay", "daily", "weekly", "shop", "buy", "sell", "inventory", "transactions", "jobs", "job", "work"},
    "progressao": {"profile", "rep", "reps", "leaderboard"},
    "moderacao": {"warn", "t-warn", "warns", "unwarn", "clearwarns", "timeout", "untimeout", "unmute", "kick", "ban", "unban", "purge"},
    "comunidade": {"ticket", "ticket-close", "ticket-reopen", "ticket-claim", "ticket-config", "suggest", "suggestion-status", "report", "report-status", "giveaway", "poll", "community-config"},
    "seguranca": {"automod", "antiraid"},
    "administracao": {"admin", "admin credit", "admin debit", "admin shop-add", "admin job-add", "admin job-remove", "admin rewards", "admin timezone"},
    "diversao": {"coinflip", "dice", "rps", "eightball", "kiss", "praise"},
}

CATEGORY_LABELS = {
    "normal": "Normais",
    "economia": "Economia",
    "progressao": "Progressão",
    "moderacao": "Moderação",
    "comunidade": "Comunidade",
    "seguranca": "Segurança",
    "administracao": "Administração",
    "diversao": "Diversão",
}


def command_category(command_name: str) -> str:
    normalized = command_name.strip().casefold()
    root = normalized.split(" ", 1)[0]
    for category, names in COMMAND_CATEGORIES.items():
        if normalized in names or root in names:
            return category
    return "normal"


async def record_command_usage(
    session: AsyncSession,
    user_id: int,
    guild_id: int | None,
    channel_id: int | None,
    command_name: str,
    success: bool,
    error_type: str | None = None,
) -> None:
    session.add(CommandUsage(
        id=secrets.randbits(62),
        guild_id=guild_id,
        user_id=user_id,
        channel_id=channel_id,
        command_name=command_name,
        category=command_category(command_name),
        success=success,
        error_type=error_type[:120] if error_type else None,
        used_at=datetime.now(timezone.utc),
    ))


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
