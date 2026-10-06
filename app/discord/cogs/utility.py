from __future__ import annotations
import logging
import secrets
import time
from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands
from app.core.db import session_factory
from app.services.diagnostics import run_diagnostics
from app.models import AuditLog, Reminder
from app.core.time import utc_now
from app.discord.theme import bar, embed, duration, number, line_chunks, ledger, status_line

logger = logging.getLogger("bn_bot.discord.utility")


class HelpSelect(discord.ui.Select):
    def __init__(self, cog: "UtilityCog", categories: dict[str, list[str]]) -> None:
        self.cog = cog
        self.categories = categories
        options = [discord.SelectOption(label="Tudo", value="all", description="Visão geral de todos os comandos")]
        for key, lines in categories.items():
            options.append(discord.SelectOption(label=key, value=key, description=f"{len(lines)} comandos"))
        super().__init__(placeholder="Escolha uma área do BN Bot", options=options, custom_id="bn:help:category")

    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.values[0]
        lines = [line for category in self.categories.values() for line in category] if value == "all" else self.categories.get(value, [])
        title = "BN / COMANDOS" if value == "all" else f"BN / {value.upper()}"
        page = embed(title, "\n".join(lines[:24]) or "Nenhum comando registrado.", "system")
        total = max(len(lines), 1)
        page.add_field(name="Carga do módulo", value=f"{bar(len(lines), total, 12)}\n`{len(lines)}` comandos neste recorte", inline=False)
        page.add_field(name="Navegação", value="Use o seletor abaixo para trocar de área.", inline=False)
        await interaction.response.edit_message(embed=page, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, cog: "UtilityCog", categories: dict[str, list[str]]) -> None:
        super().__init__(timeout=180)
        self.message = None
        self.add_item(HelpSelect(cog, categories))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.started_at = time.monotonic()

    @app_commands.command(name="ping", description="Mostra a latência do BN Bot.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency = max(round(self.bot.latency * 1000), 0)
        page = embed("BN / PING", "Uma leitura rápida do caminho até o Gateway.", "system")
        page.add_field(name="Gateway", value=f"`{latency} ms`", inline=True)
        page.add_field(name="Estado", value=status_line("Conexão", "pronta" if self.bot.is_ready() else "indisponível", "ok" if self.bot.is_ready() else "error"), inline=True)
        quality = max(0, min(150, 150 - latency))
        page.add_field(name="Sinal", value=f"{bar(quality, 150, 12)}\n`{latency} ms` de latência", inline=False)
        await interaction.response.send_message(embed=page)

    @app_commands.command(name="uptime", description="Mostra o uptime do BN Bot.")
    async def uptime(self, interaction: discord.Interaction) -> None:
        total = int(time.monotonic() - self.started_at)
        page = embed("BN / UPTIME", "Tempo contínuo desde a última inicialização.", "system")
        page.add_field(name="Leitura", value=ledger([
            ("Ativo", duration(total)),
            ("Servidores", number(len(self.bot.guilds))),
            ("Gateway", "pronto" if self.bot.is_ready() else "aguardando"),
        ]), inline=False)
        page.add_field(name="Estado", value=status_line("Processo", "estável" if self.bot.is_ready() else "aguardando", "ok" if self.bot.is_ready() else "warning"), inline=False)
        await interaction.response.send_message(embed=page)

    @app_commands.command(name="botinfo", description="Mostra informações do BN Bot.")
    async def botinfo(self, interaction: discord.Interaction) -> None:
        page = embed("BN / IDENTIDADE", "Estado operacional e presença do BN Bot.", "system")
        page.add_field(name="Discord.py", value=f"`{discord.__version__}`", inline=True)
        page.add_field(name="Servidores", value=f"`{number(len(self.bot.guilds))}`", inline=True)
        page.add_field(name="Usuário", value=str(self.bot.user) if self.bot.user else "indisponível", inline=False)
        page.add_field(name="Gateway", value=f"`{round(self.bot.latency * 1000)} ms`", inline=True)
        page.add_field(name="Estado", value=status_line("Processo", "pronto" if self.bot.is_ready() else "aguardando", "ok" if self.bot.is_ready() else "warning"), inline=True)
        if self.bot.user:
            page.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=page)

    @app_commands.command(name="serverinfo", description="Mostra informações do servidor.")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None
        page = embed("BN / SERVIDOR", f"**{guild.name}** · inventário rápido deste servidor.", "system")
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        page.add_field(name="Membros", value=f"`{number(guild.member_count or 0)}`", inline=True)
        page.add_field(name="Canais", value=f"`{number(len(guild.channels))}`", inline=True)
        page.add_field(name="Cargos", value=f"`{number(max(len(guild.roles) - 1, 0))}`", inline=True)
        page.add_field(name="Estrutura", value=ledger([
            ("Texto", number(text_channels)),
            ("Voz", number(voice_channels)),
            ("Categorias", number(len(guild.categories))),
        ]), inline=False)
        page.add_field(name="Criado", value=discord.utils.format_dt(guild.created_at, "R"), inline=True)
        page.add_field(name="Dono", value=f"<@{guild.owner_id}>" if guild.owner_id else "indisponível", inline=True)
        page.add_field(name="ID", value=f"`{guild.id}`", inline=True)
        if guild.icon:
            page.set_thumbnail(url=guild.icon.url)
        await interaction.response.send_message(embed=page)

    @app_commands.command(name="userinfo", description="Mostra informações de um usuário.")
    @app_commands.guild_only()
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        page = embed("BN / PERFIL", f"**{target.display_name}**\n{target.mention}", "system")
        page.set_thumbnail(url=target.display_avatar.url)
        joined_at = target.joined_at if isinstance(target, discord.Member) else None
        page.add_field(name="Registro", value=ledger([
            ("ID", str(target.id)),
            ("Conta", discord.utils.format_dt(target.created_at, "R")),
            ("Servidor", discord.utils.format_dt(joined_at, "R") if joined_at else "Não disponível"),
        ]), inline=False)
        if isinstance(target, discord.Member):
            page.add_field(name="Presença", value=status_line("Tipo", "bot" if target.bot else "membro", "warning" if target.bot else "ok"), inline=True)
            page.add_field(name="Cargos", value=f"`{max(len(target.roles) - 1, 0)}`", inline=True)
            page.add_field(name="Posição", value=f"`{target.top_role.name}`" if target.top_role else "@everyone", inline=False)
        await interaction.response.send_message(embed=page)

    @app_commands.command(name="avatar", description="Mostra o avatar de um usuário.")
    async def avatar(self, interaction: discord.Interaction, user: discord.User | None = None) -> None:
        target = user or interaction.user
        page = embed("BN / AVATAR", f"**{target.display_name}** · imagem original do Discord.", "system")
        page.set_image(url=target.display_avatar.url)
        page.add_field(name="ID", value=f"`{target.id}`", inline=True)
        page.add_field(name="Formato", value="CDN do Discord", inline=True)
        await interaction.response.send_message(embed=page)

    @app_commands.command(name="remind", description="Agenda um lembrete para você.")
    @app_commands.guild_only()
    @app_commands.choices(delivery=[app_commands.Choice(name="Canal atual", value="channel"), app_commands.Choice(name="Mensagem direta", value="dm")])
    @app_commands.describe(duration_minutes="Tempo até o lembrete, em minutos", message="Texto do lembrete", delivery="Onde o lembrete será enviado")
    async def remind(self, interaction: discord.Interaction, duration_minutes: app_commands.Range[int, 1, 525600], message: str, delivery: str = "channel") -> None:
        guild = interaction.guild
        assert guild is not None
        text = " ".join(message.split())
        if not text:
            await interaction.response.send_message("O lembrete não pode estar vazio.", ephemeral=True)
            return
        channel_id = interaction.channel_id if delivery == "channel" else None
        channel = interaction.channel
        if delivery == "channel" and not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("O lembrete no canal precisa ser usado em um canal de texto ou thread.", ephemeral=True)
            return
        if delivery not in {"channel", "dm"}:
            await interaction.response.send_message("Forma de entrega inválida.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        due_at = utc_now() + timedelta(minutes=int(duration_minutes))
        async with session_factory() as session:
            row = Reminder(id=secrets.randbits(62), guild_id=guild.id, user_id=interaction.user.id, channel_id=channel_id, message=text[:2000], due_at=due_at, sent_at=None, delivery=delivery)
            session.add(row)
            await session.commit()
        page = embed("BN / LEMBRETE", row.message, "system")
        page.add_field(name="Entrega", value="Mensagem direta" if delivery == "dm" else f"Canal <#{channel_id}>", inline=True)
        page.add_field(name="Quando", value=discord.utils.format_dt(row.due_at, "R"), inline=True)
        page.add_field(name="ID", value=f"`{row.id}`", inline=False)
        await interaction.followup.send(embed=page, ephemeral=True)

    @app_commands.command(name="help", description="Lista somente os comandos implementados.")
    async def help(self, interaction: discord.Interaction) -> None:
        groups = {"Geral": [], "Economia": [], "Progressão": [], "Moderação": [], "Comunidade": [], "Segurança": [], "Admin": []}
        executable_commands = [command for command in self.bot.tree.walk_commands() if not getattr(command, "commands", None)]
        for command in sorted(executable_commands, key=lambda item: item.qualified_name):
            root = command.qualified_name.split(" ", 1)[0]
            if root in {"balance", "bank", "deposit", "withdraw", "pay", "daily", "weekly", "shop", "buy", "sell", "inventory", "jobs", "job", "work"}:
                category = "Economia"
            elif root in {"profile", "rep", "reps", "leaderboard"}:
                category = "Progressão"
            elif root in {"warn", "warns", "unwarn", "clearwarns", "timeout", "kick", "ban", "unban", "purge"}:
                category = "Moderação"
            elif root in {"ticket", "suggest", "suggestion-status", "report", "report-status", "giveaway", "poll", "community-config"}:
                category = "Comunidade"
            elif root in {"automod", "antiraid"}:
                category = "Segurança"
            elif root in {"admin"}:
                category = "Admin"
            else:
                category = "Geral"
            groups[category].append(f"`/{command.qualified_name}` · {command.description}")
        categories = {name: values for name, values in groups.items() if values}
        lines = [line for values in categories.values() for line in values]
        counts = " · ".join(f"{name} `{len(values)}`" for name, values in categories.items())
        page = embed("BN / COMANDOS", "Catálogo vivo do bot. Pense nele como o índice operacional do servidor.", "system")
        page.add_field(name=f"Painel · {len(lines)} comandos", value="\n".join(lines[:16]) or "Nenhum comando registrado.", inline=False)
        page.add_field(name="Mapa de módulos", value=ledger([(name, str(len(values))) for name, values in categories.items()]), inline=False)
        page.add_field(name="Navegação", value="Escolha um módulo abaixo para abrir sua lista sem sair da mensagem.", inline=False)
        view = HelpView(self, categories)
        await interaction.response.send_message(embed=page, view=view, ephemeral=True)
        try:
            view.message = await interaction.original_response()
        except discord.HTTPException:
            pass

    @app_commands.command(name="testall", description="Executa um diagnóstico não destrutivo do BN Bot.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def testall(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None
        started = time.monotonic()
        await interaction.response.defer(ephemeral=True, thinking=True)
        results = await run_diagnostics(self.bot, guild.id, interaction.user.id, interaction.channel_id)
        elapsed = time.monotonic() - started
        passed = sum(result.ok for result in results)
        failed = len(results) - passed
        failed_results = [result for result in results if not result.ok]
        chunks = [results[index:index + 8] for index in range(0, len(results), 8)]
        for index, chunk in enumerate(chunks):
            title = "BN / TESTALL" if index == 0 else f"BN / TESTALL · {index + 1}"
            description = f"**{passed} OK** · **{failed} falhas** · `{len(results)} testes` · `{elapsed:.2f}s`" if index == 0 else "Continuação do relatório técnico"
            page = embed(title, description, "system")
            for result in chunk:
                marker = "✓" if result.ok else "×"
                page.add_field(name=f"{marker} {result.name}", value=result.detail[:1024], inline=False)
            if index == 0:
                summary = " · ".join(result.name for result in failed_results[:6]) if failed_results else "Integridade geral confirmada."
                page.add_field(name="Leitura rápida", value=summary, inline=False)
                page.add_field(name="Saúde", value=f"{bar(passed, len(results), 16)}\n`{passed}/{len(results)}` verificações OK", inline=False)
            await interaction.followup.send(embed=page, ephemeral=True)
        try:
            async with session_factory() as session:
                session.add(AuditLog(id=secrets.randbits(62), guild_id=guild.id, executor_id=interaction.user.id, action="diagnostic.testall", resource="bot", before_state=None, after_state={"passed": passed, "failed": failed, "checks": len(results), "elapsed_seconds": round(elapsed, 3), "failed_checks": [result.name for result in failed_results[:20]]}, created_at=utc_now()))
                await session.commit()
        except Exception:
            logger.exception("testall audit persistence failed guild=%s", guild.id)
