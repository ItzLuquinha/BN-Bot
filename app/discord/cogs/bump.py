from __future__ import annotations
import logging
from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from app.core.db import session_factory
from app.core.interactions import defer, respond
from app.core.time import utc_now
from app.models import BumpSchedule
from app.repositories.guilds import ensure_guild
from app.services.bump import parse_interval
from app.services.rate_limits import command_rate_limit
from app.discord.theme import duration, embed

logger = logging.getLogger("bn_bot.discord.bump")

BUMP_ACTIONS = [
    app_commands.Choice(name="Ativar", value="enable"),
    app_commands.Choice(name="Desativar", value="disable"),
    app_commands.Choice(name="Ver status", value="status"),
]


class BumpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="bump", description="Configura lembretes automáticos para enviar /bump em um canal.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(action=BUMP_ACTIONS)
    @app_commands.describe(
        action="O que fazer com o lembrete automático",
        channel="Canal onde o BN Bot vai enviar /bump quando estiver ativado",
        interval="Intervalo entre as mensagens, por exemplo 30m, 2h ou 1d",
    )
    @command_rate_limit("admin-bump", 3)
    async def bump(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        channel: discord.TextChannel | None = None,
        interval: str | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        await defer(interaction)
        if action.value == "status":
            await self._status(interaction, guild.id)
            return
        if action.value == "disable":
            await self._disable(interaction, guild.id)
            return
        if channel is None:
            await respond(interaction, "Escolha o canal onde o BN Bot deve enviar `/bump`.", ephemeral=True)
            return
        if interval is None:
            await respond(interaction, "Defina o intervalo, por exemplo `30m`, `2h` ou `1d`.", ephemeral=True)
            return
        try:
            seconds = parse_interval(interval)
        except ValueError:
            await respond(interaction, "Intervalo inválido. Use valores entre 1 minuto e 30 dias, como `1m`, `30m`, `2h` ou `1d`.", ephemeral=True)
            return
        if channel.guild.id != guild.id:
            await respond(interaction, "O canal escolhido precisa pertencer a este servidor.", ephemeral=True)
            return
        bot_member = guild.me
        if bot_member is None:
            await respond(interaction, "Não consegui confirmar minhas permissões neste servidor.", ephemeral=True)
            return
        permissions = channel.permissions_for(bot_member)
        missing = []
        if not permissions.view_channel:
            missing.append("Ver Canal")
        if not permissions.send_messages:
            missing.append("Enviar Mensagens")
        if missing:
            await respond(interaction, f"Não consigo usar {channel.mention}. Permissões ausentes: {', '.join(missing)}.", ephemeral=True)
            return
        async with session_factory() as session:
            await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)
            row = await session.scalar(select(BumpSchedule).where(BumpSchedule.guild_id == guild.id).with_for_update())
            now = utc_now()
            next_run = now + timedelta(seconds=seconds)
            if row is None:
                row = BumpSchedule(
                    guild_id=guild.id,
                    channel_id=channel.id,
                    interval_seconds=seconds,
                    enabled=True,
                    next_run_at=next_run,
                    last_sent_at=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.channel_id = channel.id
                row.interval_seconds = seconds
                row.enabled = True
                row.next_run_at = next_run
                row.updated_at = now
            await session.commit()
        page = embed("BN / BUMP", "O lembrete automático foi ativado.", "admin")
        page.add_field(name="Canal", value=channel.mention, inline=True)
        page.add_field(name="Intervalo", value=f"`{duration(seconds)}`", inline=True)
        page.add_field(name="Próximo envio", value=f"<t:{int(next_run.timestamp())}:R>", inline=False)
        await respond(interaction, embed=page)

    async def _disable(self, interaction: discord.Interaction, guild_id: int) -> None:
        async with session_factory() as session:
            row = await session.scalar(select(BumpSchedule).where(BumpSchedule.guild_id == guild_id).with_for_update())
            if row is None or not row.enabled:
                await respond(interaction, "O lembrete automático de `/bump` já está desativado.", ephemeral=True)
                return
            row.enabled = False
            row.updated_at = utc_now()
            await session.commit()
        page = embed("BN / BUMP", "O lembrete automático foi desativado.", "admin")
        await respond(interaction, embed=page)

    async def _status(self, interaction: discord.Interaction, guild_id: int) -> None:
        async with session_factory() as session:
            row = await session.scalar(select(BumpSchedule).where(BumpSchedule.guild_id == guild_id))
        if row is None:
            page = embed("BN / BUMP", "Nenhum lembrete automático foi configurado.", "admin")
            await respond(interaction, embed=page)
            return
        channel = interaction.guild.get_channel(row.channel_id) if interaction.guild else None
        channel_text = channel.mention if channel is not None else f"`{row.channel_id}` · canal não encontrado"
        page = embed("BN / BUMP", "Status do lembrete automático.", "admin")
        page.add_field(name="Estado", value="Ativado" if row.enabled else "Desativado", inline=True)
        page.add_field(name="Canal", value=channel_text, inline=True)
        page.add_field(name="Intervalo", value=f"`{duration(row.interval_seconds)}`", inline=True)
        if row.enabled:
            page.add_field(name="Próximo envio", value=f"<t:{int(row.next_run_at.timestamp())}:R>", inline=False)
        if row.last_sent_at is not None:
            page.add_field(name="Último envio", value=f"<t:{int(row.last_sent_at.timestamp())}:R>", inline=False)
        await respond(interaction, embed=page)
