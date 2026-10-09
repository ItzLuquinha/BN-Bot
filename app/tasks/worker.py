import logging
from datetime import timedelta
import discord
from discord.ext import tasks
from sqlalchemy import or_, select
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
        now = utc_now()
        max_attempts = 5
        retry_delays = (60, 300, 900, 3600)
        try:
            async with session_factory() as session:
                result = await session.execute(
                    select(Reminder)
                    .where(
                        Reminder.sent_at.is_(None),
                        Reminder.due_at <= now,
                        Reminder.attempt_count < max_attempts,
                        or_(Reminder.next_attempt_at.is_(None), Reminder.next_attempt_at <= now),
                    )
                    .order_by(Reminder.due_at)
                    .limit(50)
                    .with_for_update(skip_locked=True)
                )
                rows = list(result.scalars())
                for reminder in rows:
                    delivered = False
                    permanent_failure = False
                    error_text: str | None = None
                    discord_retry_after: float | None = None

                    try:
                        if reminder.delivery == "dm":
                            user = self.bot.get_user(reminder.user_id)
                            if user is None:
                                user = await self.bot.fetch_user(reminder.user_id)
                            await user.send(reminder.message)
                            delivered = True
                        elif reminder.channel_id:
                            channel = self.bot.get_channel(reminder.channel_id)
                            if channel is None and reminder.guild_id:
                                guild = self.bot.get_guild(reminder.guild_id)
                                if guild is not None:
                                    channel = guild.get_thread(reminder.channel_id)
                                    if channel is None:
                                        channel = await guild.fetch_channel(reminder.channel_id)
                            if channel is None:
                                raise RuntimeError("reminder destination is not currently available")
                            await channel.send(
                                f"<@{reminder.user_id}> {reminder.message}",
                                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                            )
                            delivered = True
                        else:
                            raise ValueError("reminder has no valid delivery destination")
                    except discord.RateLimited as exc:
                        discord_retry_after = max(float(getattr(exc, "retry_after", 1.0)), 1.0)
                        error_text = f"RateLimited: retry_after={discord_retry_after:.2f}s"[:500]
                    except (discord.NotFound, discord.Forbidden, ValueError) as exc:
                        permanent_failure = True
                        error_text = f"{type(exc).__name__}: {exc}"[:500]
                    except Exception as exc:
                        error_text = f"{type(exc).__name__}: {exc}"[:500]

                    if delivered:
                        reminder.sent_at = utc_now()
                        reminder.next_attempt_at = None
                        reminder.last_error = None
                        logger.info("reminder delivered id=%s delivery=%s", reminder.id, reminder.delivery)
                        continue

                    reminder.attempt_count += 1
                    if permanent_failure:
                        reminder.attempt_count = max_attempts
                    reminder.last_error = error_text or "Delivery failed"
                    if reminder.attempt_count < max_attempts:
                        delay = retry_delays[min(reminder.attempt_count - 1, len(retry_delays) - 1)]
                        if discord_retry_after is not None:
                            delay = max(delay, int(discord_retry_after + 0.999))
                        reminder.next_attempt_at = utc_now() + timedelta(seconds=delay)
                        logger.warning(
                            "reminder delivery deferred id=%s attempt=%s/%s retry_seconds=%s error=%s",
                            reminder.id,
                            reminder.attempt_count,
                            max_attempts,
                            delay,
                            reminder.last_error,
                        )
                    else:
                        reminder.next_attempt_at = None
                        logger.error(
                            "reminder delivery abandoned id=%s attempts=%s error=%s",
                            reminder.id,
                            reminder.attempt_count,
                            reminder.last_error,
                        )
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
