from __future__ import annotations
from datetime import timedelta
import logging
import secrets
import discord
from discord import app_commands
from discord.ext import commands
from app.core.db import session_factory
from app.core.interactions import defer, respond
from app.services.moderation import add_warning, list_warnings, deactivate_warning, record_punishment, count_active_warnings
from app.models import ModerationLog
from app.core.time import utc_now
from app.core.validation import parse_snowflake
from app.discord.theme import embed, number, status_line


logger = logging.getLogger("bn_bot.discord.moderation")


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def persist_punishment(self, guild_id: int, user_id: int, moderator_id: int, kind: str, reason: str | None, expires_at=None, data: dict | None = None) -> bool:
        try:
            async with session_factory() as session:
                await record_punishment(session, guild_id, user_id, moderator_id, kind, reason, expires_at, data)
            return True
        except Exception:
            logger.exception("punishment persistence failed guild=%s user=%s kind=%s", guild_id, user_id, kind)
            return False

    @staticmethod
    def target_error(interaction: discord.Interaction, user: discord.Member) -> str | None:
        guild = interaction.guild
        actor = interaction.user if isinstance(interaction.user, discord.Member) else None
        if guild is None or actor is None:
            return "Contexto de servidor inválido."
        if user.id == actor.id:
            return "Você não pode aplicar esta ação em si mesmo."
        if user.id == guild.owner_id:
            return "O dono do servidor não pode ser alvo desta ação."
        if actor.id != guild.owner_id and user.top_role >= actor.top_role:
            return "Você não pode moderar alguém com cargo igual ou superior ao seu."
        me = guild.me
        if me is None or user.top_role >= me.top_role:
            return "O maior cargo do BN Bot precisa estar acima do cargo do alvo."
        return None

    async def send_action(self, interaction: discord.Interaction, title: str, description: str, target: discord.Member, kind: str, expires_at=None, reason: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        page = embed(title, description, "moderation")
        page.set_thumbnail(url=target.display_avatar.url)
        page.add_field(name="Usuário", value=target.mention, inline=True)
        page.add_field(name="ID", value=f"`{target.id}`", inline=True)
        page.add_field(name="Motivo", value=reason[:1024] if reason else "Não informado", inline=False)
        if expires_at is not None:
            page.add_field(name="Expira", value=discord.utils.format_dt(expires_at, "R"), inline=True)
        await respond(interaction, embed=page)

    @app_commands.command(name="warn", description="Aplica um warn.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warn(self, interaction: discord.Interaction, user: discord.Member, reason: str) -> None:
        reason = " ".join(reason.split())
        if not reason:
            await respond(interaction, "Informe um motivo para o warn.", ephemeral=True)
            return
        target_error = self.target_error(interaction, user)
        if target_error:
            await respond(interaction, target_error, ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        async with session_factory() as session:
            warning_id = await add_warning(session, guild.id, user.id, interaction.user.id, reason[:500])
            total = await count_active_warnings(session, guild.id, user.id)
        page = embed("BN / WARN", f"{user.mention} recebeu um warn.", "moderation")
        page.set_thumbnail(url=user.display_avatar.url)
        page.add_field(name="ID", value=f"`{warning_id}`", inline=True)
        page.add_field(name="Warns ativos", value=f"`{number(total)}`", inline=True)
        page.add_field(name="Motivo", value=reason[:1024], inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="warns", description="Lista warns de um usuário.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warns(self, interaction: discord.Interaction, user: discord.Member) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        async with session_factory() as session:
            rows = await list_warnings(session, guild.id, user.id)
        page = embed("BN / WARNS", f"Histórico de **{user.display_name}**.", "moderation")
        if not rows:
            page.add_field(name="Histórico vazio", value="Este usuário não possui warns registrados.", inline=False)
        else:
            lines = []
            for row in rows[:15]:
                state = "ativo" if row.active else "inativo"
                lines.append(f"`{row.id}` · **{state}** · {row.reason[:90]}")
            page.add_field(name=f"Registros · {len(rows)}", value="\n".join(lines)[:1024], inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="unwarn", description="Desativa um warn pelo ID.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def unwarn(self, interaction: discord.Interaction, warning_id: str) -> None:
        await defer(interaction)
        try:
            target_id = parse_snowflake(warning_id)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        async with session_factory() as session:
            await deactivate_warning(session, guild.id, target_id, interaction.user.id)
        page = embed("BN / WARN DESATIVADO", f"Warn `{target_id}` foi desativado.", "moderation")
        await respond(interaction, embed=page)

    @app_commands.command(name="clearwarns", description="Desativa todos os warns de um usuário.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clearwarns(self, interaction: discord.Interaction, user: discord.Member) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        async with session_factory() as session:
            rows = await list_warnings(session, guild.id, user.id)
            active = [row for row in rows if row.active]
            for row in active:
                row.active = False
            if active:
                session.add(ModerationLog(id=secrets.randbits(62), guild_id=guild.id, actor_id=interaction.user.id, target_id=user.id, kind="clearwarns", reason=f"{len(active)} warns desativados", data={"warning_ids": [row.id for row in active]}, created_at=utc_now()))
            await session.commit()
        page = embed("BN / WARNS LIMPOS", f"Histórico ativo de {user.mention} foi limpo.", "moderation")
        page.add_field(name="Desativados", value=f"`{len(active)}`", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="timeout", description="Coloca um usuário em timeout por até 28 dias.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, user: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str | None = None) -> None:
        target_error = self.target_error(interaction, user)
        if target_error:
            await respond(interaction, target_error, ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        expires_at = interaction.created_at + timedelta(minutes=minutes)
        await user.timeout(timedelta(minutes=minutes), reason=reason[:500] if reason else None)
        persisted = await self.persist_punishment(guild.id, user.id, interaction.user.id, "timeout", reason[:500] if reason else None, expires_at)
        page = embed("BN / TIMEOUT", f"{user.mention} recebeu um timeout.", "moderation")
        page.set_thumbnail(url=user.display_avatar.url)
        page.add_field(name="Usuário", value=user.mention, inline=True)
        page.add_field(name="Expira", value=discord.utils.format_dt(expires_at, "R"), inline=True)
        page.add_field(name="Registro", value=status_line("Auditoria", "salva" if persisted else "indisponível", "ok" if persisted else "warning"), inline=True)
        page.add_field(name="Motivo", value=reason[:1024] if reason else "Não informado", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="kick", description="Expulsa um usuário.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        target_error = self.target_error(interaction, user)
        if target_error:
            await respond(interaction, target_error, ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        await user.kick(reason=reason[:500] if reason else None)
        persisted = await self.persist_punishment(guild.id, user.id, interaction.user.id, "kick", reason[:500] if reason else None)
        page = embed("BN / KICK", f"**{user.display_name}** foi expulso do servidor.", "moderation")
        page.add_field(name="Registro", value=status_line("Auditoria", "salva" if persisted else "indisponível", "ok" if persisted else "warning"), inline=True)
        page.add_field(name="Motivo", value=reason[:1024] if reason else "Não informado", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="ban", description="Bane um usuário do servidor.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, user: discord.User, reason: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        member = guild.get_member(user.id)
        if member is not None:
            target_error = self.target_error(interaction, member)
            if target_error:
                await respond(interaction, target_error, ephemeral=True)
                return
        if user.id == interaction.user.id or user.id == guild.owner_id:
            await respond(interaction, "Este usuário não pode ser alvo de ban.", ephemeral=True)
            return
        await defer(interaction)
        await guild.ban(user, reason=reason[:500] if reason else None)
        persisted = await self.persist_punishment(guild.id, user.id, interaction.user.id, "ban", reason[:500] if reason else None)
        page = embed("BN / BAN", f"**{user.display_name}** foi banido do servidor.", "moderation")
        page.add_field(name="Registro", value=status_line("Auditoria", "salva" if persisted else "indisponível", "ok" if persisted else "warning"), inline=True)
        page.add_field(name="Motivo", value=reason[:1024] if reason else "Não informado", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="unban", description="Remove o ban de um usuário pelo ID.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str) -> None:
        await defer(interaction)
        try:
            target_id = parse_snowflake(user_id)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        await guild.unban(discord.Object(id=target_id))
        persisted = await self.persist_punishment(guild.id, target_id, interaction.user.id, "unban", None)
        page = embed("BN / UNBAN", f"Ban removido de `{target_id}`.", "moderation")
        page.add_field(name="Registro", value=status_line("Auditoria", "salva" if persisted else "indisponível", "ok" if persisted else "warning"), inline=True)
        await respond(interaction, embed=page)

    @app_commands.command(name="purge", description="Remove mensagens recentes do canal.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(amount="Quantidade máxima de mensagens a remover", user="Remover somente mensagens deste usuário")
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1000], user: discord.Member | None = None) -> None:
        channel = interaction.channel
        guild = interaction.guild
        assert guild is not None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await respond(interaction, "Este comando só pode ser usado em canais de texto.", ephemeral=True)
            return
        me = guild.me
        if me is None or not channel.permissions_for(me).manage_messages:
            await respond(interaction, "O BN Bot precisa da permissão Manage Messages neste canal.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        check = lambda message: user is None or message.author.id == user.id
        deleted = await channel.purge(limit=int(amount), check=check, bulk=True, reason=f"BN Bot purge por {interaction.user}")
        audit_saved = True
        try:
            async with session_factory() as session:
                session.add(ModerationLog(id=secrets.randbits(62), guild_id=guild.id, actor_id=interaction.user.id, target_id=user.id if user else None, kind="purge", reason=f"{len(deleted)} mensagens removidas", data={"channel_id": channel.id, "amount_requested": int(amount), "amount_deleted": len(deleted), "filter_user_id": user.id if user else None}, created_at=utc_now()))
                await session.commit()
        except Exception:
            audit_saved = False
            logger.exception("purge audit persistence failed guild=%s channel=%s", guild.id, channel.id)
        page = embed("BN / PURGE", f"Limpeza concluída em {channel.mention}.", "moderation")
        page.add_field(name="Removidas", value=f"`{len(deleted)}`", inline=True)
        page.add_field(name="Solicitadas", value=f"`{int(amount)}`", inline=True)
        page.add_field(name="Filtro", value=user.mention if user else "Todas as mensagens", inline=True)
        page.add_field(name="Auditoria", value=status_line("Registro", "salvo" if audit_saved else "não salvo", "ok" if audit_saved else "warning"), inline=False)
        await interaction.followup.send(embed=page, ephemeral=True)
