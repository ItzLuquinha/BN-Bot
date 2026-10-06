import logging
import discord
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from discord.ext import commands
from app.config import get_settings
from app.core.db import session_factory
from app.core.time import utc_now
from app.models import Guild, Member
from app.repositories.analytics import record_message
from app.repositories.guilds import ensure_guild, ensure_user, ensure_member
from app.services.cooldowns import check_and_set
from app.services.levels import add_xp

logger = logging.getLogger("bn_bot.discord")


class BNBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.members = True
        intents.message_content = True
        intents.messages = True
        intents.voice_states = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self) -> None:
        from app.discord.cogs.utility import UtilityCog
        from app.discord.cogs.economy import EconomyCog
        from app.discord.cogs.progression import ProgressionCog
        from app.discord.cogs.moderation import ModerationCog
        from app.discord.cogs.community import CommunityCog
        from app.discord.cogs.automod import AutoModCog, add_to_tree as add_automod_to_tree
        from app.discord.cogs.admin import AdminCog, add_to_tree
        from app.discord.cogs.antiraid import AntiRaidCog, add_to_tree as add_antiraid_to_tree
        from app.tasks.worker import Worker

        await self.add_cog(UtilityCog(self))
        await self.add_cog(EconomyCog(self))
        await self.add_cog(ProgressionCog(self))
        await self.add_cog(ModerationCog(self))
        await self.add_cog(CommunityCog(self))
        await self.add_cog(AutoModCog(self))
        await self.add_cog(AdminCog(self))
        await self.add_cog(AntiRaidCog(self))
        add_to_tree(self)
        add_automod_to_tree(self)
        add_antiraid_to_tree(self)
        self.worker = Worker(self)
        synced = await self.tree.sync()
        logger.info("slash commands synchronized count=%s environment=%s", len(synced), get_settings().app_env)
        settings = get_settings()
        if settings.app_env != "production" and settings.discord_guild_id:
            guild_object = discord.Object(id=settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild_object)
            guild_synced = await self.tree.sync(guild=guild_object)
            logger.info("development guild commands synchronized during setup guild=%s count=%s", settings.discord_guild_id, len(guild_synced))

    async def on_ready(self) -> None:
        settings = get_settings()
        if settings.app_env != "production" and not getattr(self, "_development_guild_sync_complete", False):
            target_ids = [settings.discord_guild_id] if settings.discord_guild_id else [guild.id for guild in self.guilds]
            sync_success = True
            for guild_id in sorted(set(value for value in target_ids if value)):
                guild_object = discord.Object(id=guild_id)
                try:
                    self.tree.copy_global_to(guild=guild_object)
                    synced = await self.tree.sync(guild=guild_object)
                    logger.info("development guild commands synchronized guild=%s count=%s", guild_id, len(synced))
                except discord.HTTPException:
                    sync_success = False
                    logger.exception("development guild command sync failed guild=%s", guild_id)
            self._development_guild_sync_complete = sync_success
        logger.info("logged in as %s", self.user)

    async def close(self) -> None:
        if hasattr(self, "worker"):
            self.worker.close()
        await super().close()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        async with session_factory() as session:
            await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)
            await session.commit()
        settings = get_settings()
        if settings.app_env != "production":
            try:
                guild_object = discord.Object(id=guild.id)
                self.tree.copy_global_to(guild=guild_object)
                await self.tree.sync(guild=guild_object)
            except discord.HTTPException:
                logger.exception("development guild command sync failed guild=%s", guild.id)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        async with session_factory() as session:
            stored = await session.get(Guild, guild.id)
            if stored is not None:
                stored.active = False
                stored.updated_at = utc_now()
                await session.commit()

    async def on_member_join(self, member: discord.Member) -> None:
        async with session_factory() as session:
            await ensure_guild(session, member.guild.id, member.guild.name, member.guild.owner_id, member.guild.icon.url if member.guild.icon else None)
            await ensure_user(session, member.id, str(member), member.display_name, member.display_avatar.url)
            await ensure_member(session, member.guild.id, member.id, member.joined_at)
            await session.commit()
        antiraid = self.get_cog("AntiRaidCog")
        if antiraid is not None:
            try:
                await antiraid.on_member_join_event(member)
            except Exception:
                logger.exception("antiraid join handling failed guild=%s user=%s", member.guild.id, member.id)

    async def on_member_remove(self, member: discord.Member) -> None:
        async with session_factory() as session:
            row = await session.scalar(
                select(Member).where(Member.guild_id == member.guild.id, Member.user_id == member.id)
            )
            if row is not None:
                current = utc_now()
                row.left_at = current
                row.updated_at = current
                await session.commit()

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        automod = self.get_cog("AutoModCog")
        if automod is not None:
            handled = await automod.on_message_event(message)
            if handled:
                return
        try:
            async with session_factory() as session:
                guild = message.guild
                await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)
                await ensure_user(session, message.author.id, message.author.name, message.author.display_name, message.author.display_avatar.url)
                await ensure_member(session, guild.id, message.author.id, message.author.joined_at)
                bucket = message.created_at.replace(minute=0, second=0, microsecond=0)
                await record_message(session, guild.id, message.author.id, message.channel.id, message.id, len(message.content), bucket)
                if await check_and_set(f"bn:xp:{guild.id}:{message.author.id}", 60) is None:
                    await add_xp(session, guild.id, message.author.id, 15)
                await session.commit()
        except SQLAlchemyError:
            logger.exception("message persistence failed guild=%s user=%s", message.guild.id, message.author.id)
        await self.process_commands(message)

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
        original = error.original if isinstance(error, discord.app_commands.CommandInvokeError) else error
        if isinstance(original, discord.app_commands.errors.MissingPermissions):
            message = "Você não possui a permissão necessária para executar este comando."
        elif isinstance(original, discord.Forbidden):
            message = "O BN Bot não possui as permissões necessárias neste servidor ou canal."
        elif isinstance(original, discord.NotFound):
            message = "O recurso do Discord não foi encontrado."
        elif isinstance(original, discord.app_commands.errors.TransformerError):
            message = "Um dos parâmetros informados é inválido."
        elif isinstance(original, discord.app_commands.errors.CommandSignatureMismatch):
            message = "A assinatura deste comando estava desatualizada no Discord. O BN Bot está sincronizando os comandos; tente novamente em alguns segundos."
        elif isinstance(original, discord.HTTPException):
            message = "O Discord recusou esta resposta. Tente o comando novamente."
        elif isinstance(original, SQLAlchemyError):
            message = "Ocorreu um erro ao acessar o banco de dados. Tente novamente."
        else:
            from app.core.exceptions import CooldownActive, InsufficientFunds, NotFound, ValidationFailure
            if isinstance(original, CooldownActive):
                message = f"Aguarde {original.seconds}s antes de tentar novamente."
            elif isinstance(original, InsufficientFunds):
                message = "Saldo insuficiente para concluir a operação."
            elif isinstance(original, NotFound):
                message = "O recurso solicitado não foi encontrado."
            elif isinstance(original, ValidationFailure):
                message = str(original) or "Os dados informados são inválidos."
            elif isinstance(original, ValueError):
                mapping = {
                    "invalid transfer": "A transferência é inválida.",
                    "quantity must be positive": "A quantidade deve ser maior que zero.",
                    "amount must be positive": "O valor deve ser maior que zero.",
                    "not enough items": "Você não possui itens suficientes.",
                    "stack limit exceeded": "A quantidade ultrapassa o limite do item.",
                    "insufficient stock": "O estoque disponível não é suficiente.",
                }
                message = mapping.get(str(original), "Os dados informados não podem ser processados.")
            else:
                message = "Não foi possível concluir este comando."
        if interaction.response.is_done():
            try:
                await interaction.followup.send(message, ephemeral=True)
            except discord.HTTPException:
                logger.exception("failed to send command error followup")
        else:
            await interaction.response.send_message(message, ephemeral=True)
        if isinstance(original, BaseException):
            logger.error("application command failure: %s", type(original).__name__, exc_info=(type(original), original, original.__traceback__))
        else:
            logger.error("application command failure: %r", original)
