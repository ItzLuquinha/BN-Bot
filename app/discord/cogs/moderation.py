from __future__ import annotations
from datetime import datetime, timedelta
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
from app.services.rate_limits import command_rate_limit


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

    async def _create_warning(self, interaction: discord.Interaction, user: discord.Member, reason: str, expires_at=None, timed=False) -> None:
        target_error = self.target_error(interaction, user)
        if target_error:
            await respond(interaction, target_error, ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        reason = " ".join(reason.split())
        if not reason:
            await respond(interaction, "Informe um motivo para o warn.", ephemeral=True)
            return
        await defer(interaction)
        async with session_factory() as session:
            warning_id = await add_warning(session, guild.id, user.id, interaction.user.id, reason[:500], expires_at=expires_at)
            total = await count_active_warnings(session, guild.id, user.id)
        title = "BN / T-WARN" if timed else "BN / WARN"
        description = f"{user.mention} recebeu um T-Warn com expiração automática." if timed else f"{user.mention} recebeu um warn permanente."
        page = embed(title, description, "moderation")
        page.set_thumbnail(url=user.display_avatar.url)
        page.add_field(name="ID", value=f"`{warning_id}`", inline=True)
        page.add_field(name="Warns ativos", value=f"`{number(total)}`", inline=True)
        if expires_at is not None:
            page.add_field(name="Expira", value=discord.utils.format_dt(expires_at, "R"), inline=True)
        page.add_field(name="Motivo", value=reason[:1024], inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="warn", description="Aplica um warn permanente.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(user="Usuário que receberá o warn", reason="Motivo do warn")
    async def warn(self, interaction: discord.Interaction, user: discord.Member, reason: str) -> None:
        await self._create_warning(interaction, user, reason)

    @staticmethod
    def parse_twarn_duration(value: str) -> int:
        import re
        match = re.fullmatch(r"([0-9]{1,9})([smhdSMHD])", value.strip())
        if match is None:
            raise ValueError("A duração deve seguir o formato `30s`, `15m`, `2h` ou `7d`.")
        amount = int(match.group(1))
        unit = match.group(2).lower()
        multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        seconds = amount * multiplier
        if seconds < 1 or seconds > 365 * 86400:
            raise ValueError("A duração do T-Warn deve ficar entre 1 segundo e 365 dias.")
        return seconds

    @app_commands.command(name="t-warn", description="Aplica um warn temporário com duração no formato 30s, 15m, 2h ou 7d.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(user="Usuário que receberá o T-Warn", reason="Motivo do T-Warn", duration="Duração: S segundos, M minutos, H horas ou D dias")
    async def t_warn(self, interaction: discord.Interaction, user: discord.Member, reason: str, duration: str) -> None:
        try:
            seconds = self.parse_twarn_duration(duration)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        expires_at = utc_now() + timedelta(seconds=seconds)
        await self._create_warning(interaction, user, reason, expires_at=expires_at, timed=True)

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
            changed = await deactivate_warning(session, guild.id, target_id, interaction.user.id)
        if not changed:
            await respond(interaction, f"O warn `{target_id}` já está desativado.", ephemeral=True)
            return
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

    @staticmethod
    def parse_timeout_duration(value: str) -> int:
        raw = value.strip()
        if raw.isdigit():
            raw = f"{raw}m"
        seconds = ModerationCog.parse_twarn_duration(raw)
        if seconds > 28 * 86400:
            raise ValueError("A duração do timeout deve ficar entre 1 segundo e 28 dias.")
        return seconds

    @command_rate_limit("moderation-action", 3)
    @app_commands.command(name="timeout", description="Coloca um usuário em timeout por até 28 dias.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="Usuário que receberá o timeout", duration="Duração: 30s, 15m, 2h ou 7d", reason="Motivo do timeout")
    async def timeout(self, interaction: discord.Interaction, user: discord.Member, duration: str, reason: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        try:
            seconds = self.parse_timeout_duration(duration)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        await defer(interaction)
        target_error = self.target_error(interaction, user)
        if target_error:
            await respond(interaction, target_error, ephemeral=True)
            return
        clean_reason = " ".join(reason.split())[:500] if reason else None
        now = discord.utils.utcnow()
        expires_at = min(now + timedelta(seconds=seconds), now + timedelta(days=28) - timedelta(seconds=2))
        current = await self._edit_timeout(guild, user, expires_at, clean_reason)
        persisted = await self.persist_punishment(guild.id, current.id, interaction.user.id, "timeout", clean_reason, expires_at)
        page = embed("BN / TIMEOUT", f"{current.mention} recebeu um timeout.", "moderation")
        page.set_thumbnail(url=current.display_avatar.url)
        page.add_field(name="Usuário", value=current.mention, inline=True)
        page.add_field(name="Duração", value=f"`{duration.strip()}`", inline=True)
        page.add_field(name="Expira", value=discord.utils.format_dt(expires_at, "R"), inline=True)
        page.add_field(name="Registro", value=status_line("Auditoria", "salva" if persisted else "indisponível", "ok" if persisted else "warning"), inline=True)
        page.add_field(name="Motivo", value=clean_reason[:1024] if clean_reason else "Não informado", inline=False)
        await respond(interaction, embed=page)

    async def _edit_timeout(self, guild: discord.Guild, user: discord.Member, until: datetime | None, reason: str | None) -> discord.Member:
        await user.timeout(until, reason=reason)
        if until is None:
            user.timed_out_until = None
        else:
            user.timed_out_until = until
        return user

    async def _remove_timeout(self, interaction: discord.Interaction, user: discord.Member, kind: str, title: str, reason: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        target_error = self.target_error(interaction, user)
        if target_error:
            await respond(interaction, target_error, ephemeral=True)
            return
        clean_reason = " ".join(reason.split())[:500] if reason else None
        current = await self._edit_timeout(guild, user, None, clean_reason)
        persisted = await self.persist_punishment(guild.id, current.id, interaction.user.id, kind, clean_reason)
        page = embed(title, f"O timeout de {current.mention} foi removido.", "moderation")
        page.set_thumbnail(url=current.display_avatar.url)
        page.add_field(name="Usuário", value=current.mention, inline=True)
        page.add_field(name="Estado", value="sem timeout", inline=True)
        page.add_field(name="Registro", value=status_line("Auditoria", "salva" if persisted else "indisponível", "ok" if persisted else "warning"), inline=True)
        await respond(interaction, embed=page)

    @command_rate_limit("moderation-action", 3)
    @app_commands.command(name="untimeout", description="Remove o timeout de um usuário.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="Usuário que terá o timeout removido", reason="Motivo da remoção do timeout")
    async def untimeout(self, interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        await self._remove_timeout(interaction, user, "untimeout", "BN / UNTIMEOUT", reason)

    @command_rate_limit("moderation-action", 3)
    @app_commands.command(name="unmute", description="Remove o timeout de um usuário usando o comando unmute.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="Usuário que terá o timeout removido", reason="Motivo da remoção do timeout")
    async def unmute(self, interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        await self._remove_timeout(interaction, user, "unmute", "BN / UNMUTE", reason)

    @command_rate_limit("moderation-action", 3)
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

    @command_rate_limit("moderation-action", 3)
    @app_commands.command(name="ban", description="Bane um usuário do servidor.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, user: discord.User, reason: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        member = guild.get_member(user.id)
        if member is None:
            try:
                member = await guild.fetch_member(user.id)
            except discord.NotFound:
                member = None
            except discord.RateLimited as exc:
                wait = max(1, int(float(exc.retry_after) + 0.999))
                await respond(interaction, f"O Discord está limitando esta ação. Aguarde {wait}s e tente novamente.", ephemeral=True)
                return
            except discord.HTTPException:
                logger.exception("ban aborted because target hierarchy could not be verified guild=%s target=%s", guild.id, user.id)
                await respond(interaction, "Não foi possível verificar os cargos do alvo. Nenhum ban foi aplicado; tente novamente.", ephemeral=True)
                return
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
        page = embed("BN / BAN", f"**BANIMENTO EXECUTADO**\n{user.mention} não pode mais entrar neste servidor.", "moderation")
        page.set_thumbnail(url=user.display_avatar.url)
        page.add_field(name="Alvo", value=f"{user.mention}\n`{user.id}`", inline=True)
        page.add_field(name="Registro", value=status_line("Auditoria", "salva" if persisted else "indisponível", "ok" if persisted else "warning"), inline=True)
        page.add_field(name="Decisão", value="`BAN`", inline=True)
        page.add_field(name="Motivo", value=reason[:1024] if reason else "Não informado", inline=False)
        await respond(interaction, embed=page)

    @command_rate_limit("moderation-action", 3)
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
        try:
            await guild.fetch_ban(discord.Object(id=target_id))
        except discord.NotFound:
            await respond(interaction, f"O usuário `{target_id}` não está banido.", ephemeral=True)
            return
        except discord.RateLimited as exc:
            wait = max(1, int(float(exc.retry_after) + 0.999))
            await respond(interaction, f"O Discord está limitando esta ação. Aguarde {wait}s e tente novamente.", ephemeral=True)
            return
        except discord.HTTPException:
            logger.exception("unban aborted because ban status could not be verified guild=%s target=%s", guild.id, target_id)
            await respond(interaction, "Não foi possível confirmar o estado do ban. Nenhuma alteração foi feita; tente novamente.", ephemeral=True)
            return
        await guild.unban(discord.Object(id=target_id))
        persisted = await self.persist_punishment(guild.id, target_id, interaction.user.id, "unban", None)
        page = embed("BN / UNBAN", f"Ban removido de `{target_id}`.", "moderation")
        page.add_field(name="Registro", value=status_line("Auditoria", "salva" if persisted else "indisponível", "ok" if persisted else "warning"), inline=True)
        await respond(interaction, embed=page)

    @command_rate_limit("moderation-purge", 10)
    @app_commands.command(name="purge", description="Remove mensagens recentes do canal.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(amount="Quantidade máxima de mensagens a analisar/remover (1 a 1000)", user="Remover somente mensagens deste usuário")
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1000], user: discord.Member | None = None) -> None:
        channel = interaction.channel
        guild = interaction.guild
        assert guild is not None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await respond(interaction, "Este comando só pode ser usado em canais de texto.", ephemeral=True)
            return
        me = guild.me
        if me is None:
            await respond(interaction, "Não consegui confirmar as permissões do BN Bot neste canal.", ephemeral=True)
            return
        bot_permissions = channel.permissions_for(me)
        if not bot_permissions.view_channel or not bot_permissions.read_message_history:
            await respond(interaction, "O BN Bot precisa das permissões View Channel e Read Message History neste canal.", ephemeral=True)
            return
        if not bot_permissions.manage_messages:
            await respond(interaction, "O BN Bot precisa da permissão Manage Messages neste canal.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        check = lambda message: user is None or message.author.id == user.id
        try:
            deleted = await channel.purge(limit=int(amount), check=check, bulk=True, reason=f"BN Bot purge por {interaction.user}")
        except discord.RateLimited as exc:
            wait = max(1, int(float(exc.retry_after) + 0.999))
            logger.warning("purge rate limited guild=%s channel=%s amount=%s", guild.id, channel.id, amount)
            await interaction.followup.send(f"O Discord limitou a limpeza. Aguarde {wait}s antes de tentar novamente. Mensagens já removidas não serão restauradas.", ephemeral=True)
            return
        except discord.Forbidden:
            logger.exception("purge forbidden guild=%s channel=%s amount=%s", guild.id, channel.id, amount)
            await interaction.followup.send("O Discord recusou a limpeza. Confira as permissões do bot. Mensagens já removidas não serão restauradas.", ephemeral=True)
            return
        except discord.HTTPException:
            logger.exception("purge failed guild=%s channel=%s amount=%s", guild.id, channel.id, amount)
            await interaction.followup.send("Não foi possível concluir a limpeza. Mensagens já removidas não serão restauradas; tente novamente com uma quantidade menor.", ephemeral=True)
            return
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
