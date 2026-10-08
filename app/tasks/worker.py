import logging
from datetime import timedelta
import discord
from discord.ext import tasks
from sqlalchemy import select
from app.core.db import session_factory
from app.core.time import utc_now
from app.models import Reminder, TemporaryRole, Warning

logger = logging.getLogger("bn_bot.tasks")


class Worker:
    def __init__(self, bot) -> None:
        self.bot = bot
        self.reminders.start()
        self.temporary_roles.start()
        self.antiraid.start()
        self.community.start()
        self.warnings.start()

    def close(self) -> None:
        self.reminders.cancel()
        self.temporary_roles.cancel()
        self.antiraid.cancel()
        self.community.cancel()
        self.warnings.cancel()

    @tasks.loop(seconds=15)
    async def reminders(self) -> None:
        try:
            async with session_factory() as session:
                result = await session.execute(select(Reminder).where(Reminder.sent_at.is_(None), Reminder.due_at <= utc_now()).limit(50).with_for_update(skip_locked=True))
                rows = list(result.scalars())
                for reminder in rows:
                    delivered = False
                    if reminder.delivery == "dm":
                        user = self.bot.get_user(reminder.user_id)
                        if user is None:
                            try:
                                user = await self.bot.fetch_user(reminder.user_id)
                            except Exception:
                                user = None
                        if user is not None:
                            try:
                                await user.send(reminder.message)
                                delivered = True
                            except Exception:
                                logger.exception("reminder DM delivery failed user=%s reminder=%s", reminder.user_id, reminder.id)
                    elif reminder.channel_id:
                        channel = self.bot.get_channel(reminder.channel_id)
                        if channel is None and reminder.guild_id:
                            guild = self.bot.get_guild(reminder.guild_id)
                            if guild is not None:
                                channel = guild.get_thread(reminder.channel_id)
                                if channel is None:
                                    try:
                                        channel = await guild.fetch_channel(reminder.channel_id)
                                    except Exception:
                                        channel = None
                        if channel is not None:
                            try:
                                await channel.send(
                                    f"<@{reminder.user_id}> {reminder.message}",
                                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                                )
                                delivered = True
                            except Exception:
                                logger.exception("reminder channel delivery failed channel=%s reminder=%s", reminder.channel_id, reminder.id)
                    if delivered:
                        reminder.sent_at = utc_now()
                await session.commit()
        except Exception:
            logger.exception("reminders worker iteration failed")

    @reminders.before_loop
    async def before_reminders(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def temporary_roles(self) -> None:
        try:
            async with session_factory() as session:
                result = await session.execute(select(TemporaryRole).where(TemporaryRole.expires_at <= utc_now()).limit(100).with_for_update(skip_locked=True))
                rows = list(result.scalars())
                for record in rows:
                    guild = self.bot.get_guild(record.guild_id)
                    delete_record = False
                    if guild is None:
                        logger.warning("temporary role cleanup deferred; guild unavailable guild=%s user=%s role=%s", record.guild_id, record.user_id, record.role_id)
                        continue
                    else:
                        member = guild.get_member(record.user_id)
                        if member is None:
                            try:
                                member = await guild.fetch_member(record.user_id)
                            except discord.NotFound:
                                member = None
                                delete_record = True
                            except discord.HTTPException:
                                logger.exception("temporary role member fetch failed guild=%s user=%s", record.guild_id, record.user_id)
                                continue
                        role = guild.get_role(record.role_id)
                        if member is None or role is None or role not in member.roles:
                            delete_record = True
                        else:
                            try:
                                await member.remove_roles(role, reason=record.reason)
                                delete_record = True
                            except discord.NotFound:
                                delete_record = True
                            except discord.HTTPException:
                                logger.exception("temporary role cleanup failed guild=%s user=%s", record.guild_id, record.user_id)
                    if delete_record:
                        await session.delete(record)
                await session.commit()
        except Exception:
            logger.exception("temporary roles worker iteration failed")

    @temporary_roles.before_loop
    async def before_temporary_roles(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def antiraid(self) -> None:
        try:
            cog = self.bot.get_cog("AntiRaidCog")
            if cog is not None:
                await cog.expire_lockdowns()
        except Exception:
            logger.exception("antiraid worker iteration failed")

    @antiraid.before_loop
    async def before_antiraid(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def community(self) -> None:
        try:
            cog = self.bot.get_cog("CommunityCog")
            if cog is not None:
                await cog.restore_views()
                await cog.expire_community()
        except Exception:
            logger.exception("community worker iteration failed")

    @community.before_loop
    async def before_community(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def warnings(self) -> None:
        try:
            async with session_factory() as session:
                result = await session.execute(
                    select(Warning)
                    .where(
                        Warning.active.is_(True),
                        Warning.expires_at.is_not(None),
                        Warning.expires_at <= utc_now(),
                    )
                    .limit(200)
                    .with_for_update(skip_locked=True)
                )
                rows = list(result.scalars())
                for warning in rows:
                    warning.active = False
                await session.commit()
        except Exception:
            logger.exception("timed warning cleanup iteration failed")

    @warnings.before_loop
    async def before_warnings(self) -> None:
        await self.bot.wait_until_ready()
