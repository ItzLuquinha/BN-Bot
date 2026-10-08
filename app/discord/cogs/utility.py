from __future__ import annotations
import logging
import secrets
import time
from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, desc, func
from app.core.db import session_factory
from app.services.diagnostics import run_diagnostics
from app.repositories.analytics import CATEGORY_LABELS, COMMAND_CATEGORIES, command_category
from app.models import AuditLog, CommandUsage, Reminder
from app.core.time import utc_now
from app.discord.theme import bar, embed, duration, number, ledger, status_line
from app.discord.app_contexts import user_installable
from app.services.permissions import required_permission_text

from app.services.rate_limits import command_rate_limit
logger = logging.getLogger("bn_bot.discord.utility")


CRITICAL_DIAGNOSTIC_NAMES = {
    "PostgreSQL",
    "Schema",
    "Migrations",
    "Sequences",
    "Constraints",
    "Foreign keys",
    "Economia",
    "XP",
    "Rewards",
    "AutoMod",
    "Anti-Raid",
    "Command matrix",
    "Comandos",
    "Interações",
    "Response contract",
    "Erros",
    "Dependências",
    "Discord commands",
    "Dashboard",
}


def diagnostic_severity(result: object) -> str:
    if getattr(result, "ok", False):
        return "OK"
    return "CRÍTICO" if getattr(result, "name", "") in CRITICAL_DIAGNOSTIC_NAMES else "ATENÇÃO"


ACCESS_COMMAND_ORDER = (
    "normal",
    "economia",
    "progressao",
    "moderacao",
    "comunidade",
    "seguranca",
    "administracao",
    "diversao",
)


def tutorial_access_lines(category: str) -> list[str]:
    names = list(COMMAND_CATEGORIES.get(category, set()))
    names.sort(key=lambda name: (" " not in name, name.casefold()))
    lines: list[str] = []
    for name in names:
        if name in {"admin", "automod", "antiraid", "giveaway", "poll"}:
            continue
        lines.append(f"`/{name}` · {required_permission_text(name)}")
    if category == "administracao":
        lines.insert(0, "`/admin ...` · Gerenciar Servidor")
    elif category == "seguranca":
        lines.insert(0, "`/automod ...` e `/antiraid ...` · Gerenciar Servidor")
    return lines


class TutorialSelect(discord.ui.Select):
    def __init__(self, categories: dict[str, dict[str, object]]) -> None:
        self.categories = categories
        options = [discord.SelectOption(label="Comece aqui", value="intro", description="Como usar o BN Bot sem perder tempo")]
        for key, data in categories.items():
            options.append(discord.SelectOption(label=str(data["label"]), value=key, description=str(data["hint"])[:100]))
        super().__init__(placeholder="Escolha uma área do tutorial", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.values[0]
        if value == "intro":
            title = "BN / TUTORIAL"
            description = "Use este painel como um mapa do servidor. Cada área explica quando usar os comandos e qual fluxo seguir."
            page = embed(title, description, "system")
            page.add_field(name="Primeiro contato", value="`/profile` mostra sua progressão. `/serverinfo` lê a estrutura. `/tutorial` abre este guia novamente.", inline=False)
            page.add_field(name="Para a equipe", value="Comece por **Moderação**, depois **Segurança** e **Administração**. Os comandos de staff já bloqueiam quem não tem a permissão necessária.", inline=False)
            page.add_field(name="Regra prática", value="Use `/warn` para um aviso permanente e `/t-warn` para um aviso com duração como `30m`, `2h` ou `7d`.", inline=False)
        else:
            data = self.categories.get(value, {})
            page = embed(f"BN / {str(data.get('label', value)).upper()}", str(data.get("description", "")), str(data.get("section", "system")))
            if value == "administracao":
                page.remove_image()
                if interaction.client.user is not None:
                    page.set_thumbnail(url=interaction.client.user.display_avatar.url)
            for name, body in data.get("steps", []):
                page.add_field(name=name, value=body, inline=False)
            access_lines = tutorial_access_lines(value)
            if access_lines:
                chunks = [access_lines[index:index + 12] for index in range(0, len(access_lines), 12)]
                for index, chunk in enumerate(chunks, start=1):
                    suffix = f" · {index}/{len(chunks)}" if len(chunks) > 1 else ""
                    page.add_field(name=f"Acesso aos comandos{suffix}", value="\n".join(chunk)[:1024], inline=False)
        await interaction.response.edit_message(embed=page, view=self.view)


class TutorialView(discord.ui.View):
    def __init__(self, categories: dict[str, dict[str, object]]) -> None:
        super().__init__(timeout=300)
        self.message = None
        self.add_item(TutorialSelect(categories))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class TestallErrorsView(discord.ui.View):
    def __init__(self, owner_id: int, errors: list[object]) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.errors = errors
        self.page_index = 0
        self.page_size = 8
        self._refresh()

    def _refresh(self) -> None:
        total = max(1, (len(self.errors) + self.page_size - 1) // self.page_size)
        self.previous_button.disabled = self.page_index == 0
        self.next_button.disabled = self.page_index >= total - 1
        self.page_button.label = f"{self.page_index + 1} / {total}"

    def _page(self) -> discord.Embed:
        start = self.page_index * self.page_size
        chunk = self.errors[start:start + self.page_size]
        critical = sum(diagnostic_severity(result) == "CRÍTICO" for result in self.errors)
        warnings = len(self.errors) - critical
        page = embed("BN / TESTALL · ERROS", f"Falhas encontradas · `{len(self.errors)}` no total · `{critical}` críticos · `{warnings}` atenção", "moderation")
        for result in chunk:
            severity = diagnostic_severity(result)
            page.add_field(name=f"{severity} · {getattr(result, 'name', 'desconhecido')}", value=str(getattr(result, 'detail', 'sem detalhes'))[:1024], inline=False)
        page.set_footer(text=f"BN Bot · erros · página {self.page_index + 1}/{max(1, (len(self.errors) + self.page_size - 1) // self.page_size)}")
        return page

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Este relatório pertence a outra pessoa.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary, row=0)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page_index = max(0, self.page_index - 1)
        self._refresh()
        await interaction.response.edit_message(embed=self._page(), view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, row=0, disabled=True)
    async def page_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()

    @discord.ui.button(label="Próxima", style=discord.ButtonStyle.secondary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        total = max(1, (len(self.errors) + self.page_size - 1) // self.page_size)
        self.page_index = min(total - 1, self.page_index + 1)
        self._refresh()
        await interaction.response.edit_message(embed=self._page(), view=self)


class TestallView(discord.ui.View):
    def __init__(self, owner_id: int, pages: list[discord.Embed], failed_results: list[object]) -> None:
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.pages = pages
        self.failed_results = failed_results
        self.critical_errors = [result for result in failed_results if diagnostic_severity(result) == "CRÍTICO"]
        self.warning_errors = [result for result in failed_results if diagnostic_severity(result) == "ATENÇÃO"]
        self.page_index = 0
        self._refresh()

    def _refresh(self) -> None:
        total = len(self.pages)
        self.first_button.disabled = self.page_index == 0
        self.previous_button.disabled = self.page_index == 0
        self.page_button.label = f"{self.page_index + 1} / {total}"
        self.next_button.disabled = self.page_index >= total - 1
        self.last_button.disabled = self.page_index >= total - 1
        self.errors_button.disabled = not self.failed_results
        self.errors_button.label = f"Ver erros ({len(self.failed_results)})" if self.failed_results else "Sem erros"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Este relatório pertence a outra pessoa.", ephemeral=True)
            return False
        return True

    async def _go(self, interaction: discord.Interaction, index: int) -> None:
        self.page_index = max(0, min(index, len(self.pages) - 1))
        self._refresh()
        await interaction.response.edit_message(embed=self.pages[self.page_index], view=self)

    @discord.ui.button(label="Primeira", style=discord.ButtonStyle.secondary, row=0)
    async def first_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go(interaction, 0)

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary, row=0)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go(interaction, self.page_index - 1)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, row=0, disabled=True)
    async def page_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()

    @discord.ui.button(label="Próxima", style=discord.ButtonStyle.secondary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go(interaction, self.page_index + 1)

    @discord.ui.button(label="Última", style=discord.ButtonStyle.secondary, row=0)
    async def last_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go(interaction, len(self.pages) - 1)

    @discord.ui.button(label="Ver erros", style=discord.ButtonStyle.danger, row=1)
    async def errors_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        error_view = TestallErrorsView(self.owner_id, self.failed_results)
        await interaction.response.send_message(embed=error_view._page(), view=error_view, ephemeral=True)


class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.started_at = time.monotonic()

    @user_installable
    @app_commands.command(name="donate", description="Apoie o Rian e o vix pelo PayPal.")
    async def donate(self, interaction: discord.Interaction) -> None:
        page = embed("BN / APOIE RIAN & VIX", "Se você quiser apoiar o BN Bot e os projetos de Rian & Vix, use o botão abaixo.", "community")
        page.add_field(name="PayPal", value="`@RianBraga`", inline=True)
        page.add_field(name="Destino", value="Apoio aos projetos e à manutenção do BN Bot.", inline=True)
        view = discord.ui.View(timeout=300)
        view.add_item(discord.ui.Button(label="Apoiar via PayPal", style=discord.ButtonStyle.link, url="https://paypal.me/RianBraga"))
        await interaction.response.send_message(embed=page, view=view)

    @user_installable
    @app_commands.command(name="ping", description="Mostra a latência do BN Bot.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency = max(round(self.bot.latency * 1000), 0)
        page = embed("BN / PING", "Uma leitura rápida do caminho até o Gateway.", "system")
        page.add_field(name="Gateway", value=f"`{latency} ms`", inline=True)
        page.add_field(name="Estado", value=status_line("Conexão", "pronta" if self.bot.is_ready() else "indisponível", "ok" if self.bot.is_ready() else "error"), inline=True)
        quality = max(0, min(150, 150 - latency))
        page.add_field(name="Sinal", value=f"{bar(quality, 150, 12)}\n`{latency} ms` de latência", inline=False)
        await interaction.response.send_message(embed=page)

    @user_installable
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

    @user_installable
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

    @user_installable
    @app_commands.command(name="avatar", description="Mostra o avatar de um usuário.")
    async def avatar(self, interaction: discord.Interaction, user: discord.User | None = None) -> None:
        target = user or interaction.user
        page = embed("BN / AVATAR", f"**{target.display_name}** · imagem original do Discord.", "system")
        page.set_image(url=target.display_avatar.url)
        page.add_field(name="ID", value=f"`{target.id}`", inline=True)
        page.add_field(name="Formato", value="CDN do Discord", inline=True)
        await interaction.response.send_message(embed=page)

    @command_rate_limit("remind", 10)
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
        if len(text) > 2000:
            await interaction.response.send_message("O lembrete pode ter no máximo 2000 caracteres.", ephemeral=True)
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
            active_reminders = await session.scalar(
                select(func.count(Reminder.id)).where(
                    Reminder.guild_id == guild.id,
                    Reminder.user_id == interaction.user.id,
                    Reminder.sent_at.is_(None),
                )
            )
            if int(active_reminders or 0) >= 20:
                await respond(interaction, "Você já possui 20 lembretes ativos. Aguarde alguns serem enviados antes de criar outros.", ephemeral=True)
                return
            row = Reminder(id=secrets.randbits(62), guild_id=guild.id, user_id=interaction.user.id, channel_id=channel_id, message=text[:2000], due_at=due_at, sent_at=None, delivery=delivery)
            session.add(row)
            await session.commit()
        page = embed("BN / LEMBRETE", row.message, "system")
        page.add_field(name="Entrega", value="Mensagem direta" if delivery == "dm" else f"Canal <#{channel_id}>", inline=True)
        page.add_field(name="Quando", value=discord.utils.format_dt(row.due_at, "R"), inline=True)
        page.add_field(name="ID", value=f"`{row.id}`", inline=False)
        await interaction.followup.send(embed=page, ephemeral=True)

    @user_installable
    @app_commands.command(name="tutorial", description="Abre o tutorial visual do BN Bot para membros e staff.")
    async def tutorial(self, interaction: discord.Interaction) -> None:
        categories: dict[str, dict[str, object]] = {
            "normal": {
                "label": "Comandos normais", "hint": "Base do dia a dia", "section": "system",
                "description": "O conjunto que todo membro costuma usar.",
                "steps": [
                    ("Consulta rápida", "`/profile`, `/userinfo`, `/avatar`, `/serverinfo` e `/botinfo` respondem perguntas sem alterar nada."),
                    ("Tempo e utilidade", "`/ping` mostra a latência. `/uptime` mostra há quanto tempo o bot está rodando. `/remind` agenda um lembrete."),
                ],
            },
            "economia": {
                "label": "Economia", "hint": "Moedas, loja e trabalho", "section": "economy",
                "description": "É aqui que ficam carteira, banco, loja e empregos.",
                "steps": [
                    ("Dinheiro", "`/balance`, `/bank`, `/deposit`, `/withdraw` e `/pay` controlam as carteiras."),
                    ("Trabalho", "`/job` abre a escolha de emprego. `/work` executa o turno. `/jobs` mostra as vagas disponíveis."),
                    ("Loja", "`/shop` lista o catálogo. `/buy`, `/sell` e `/inventory` cuidam das compras e do inventário."),
                ],
            },
            "progressao": {
                "label": "Progressão", "hint": "XP, níveis e reputação", "section": "progression",
                "description": "Acompanhe crescimento, ranking e reputação.",
                "steps": [
                    ("Perfil", "`/profile` reúne progresso, economia e reputação do membro."),
                    ("Reputação", "`/rep` concede reputação. `/reps` consulta a pontuação. `/leaderboard` compara os membros."),
                ],
            },
            "moderacao": {
                "label": "Moderação", "hint": "Warn, T-Warn e punições", "section": "moderation",
                "description": "Fluxo de resposta para a equipe de moderação.",
                "steps": [
                    ("Avisos", "`/warn` cria um warn permanente. `/t-warn` aceita duração no formato `30s`, `15m`, `2h` ou `7d`."),
                    ("Histórico", "`/warns` lista os avisos. `/unwarn` desativa um registro. `/clearwarns` limpa os warns ativos."),
                    ("Ações", "`/timeout`, `/untimeout`, `/unmute`, `/kick`, `/ban`, `/unban` e `/purge` cuidam das ações imediatas de moderação."),
                ],
            },
            "comunidade": {
                "label": "Comunidade", "hint": "Tickets, ideias e eventos", "section": "community",
                "description": "Ferramentas para manter a comunidade organizada e participativa.",
                "steps": [
                    ("Atendimento", "`/ticket` abre suporte. Os comandos `ticket-close`, `ticket-reopen`, `ticket-claim` e `ticket-config` cuidam do ciclo do ticket."),
                    ("Feedback", "`/suggest` envia ideias. `/report` registra denúncias. O staff acompanha os status nos comandos correspondentes."),
                    ("Eventos", "`/giveaway` e `/poll` organizam sorteios e votações."),
                ],
            },
            "seguranca": {
                "label": "Segurança", "hint": "AutoMod e Anti-Raid", "section": "security",
                "description": "Proteção automática do servidor.",
                "steps": [
                    ("AutoMod", "Use `/automod setup`, `/automod rules` e os comandos de listas para bloquear comportamentos indesejados."),
                    ("Anti-Raid", "`/antiraid setup`, `/antiraid configure`, `/antiraid status` e `/antiraid unlock` cobrem a resposta a entradas suspeitas."),
                ],
            },
            "administracao": {
                "label": "Administração", "hint": "Configuração do servidor", "section": "admin",
                "description": "Área para quem gerencia a economia e a configuração do BN Bot.",
                "steps": [
                    ("Economia administrativa", "`/admin credit`, `/admin debit` e `/admin shop-add` alteram recursos do servidor."),
                    ("Empregos", "`/admin job-add` cria um emprego sem exigir chave manual. `/admin job-remove` encontra o emprego por autocomplete e pede confirmação antes de apagar."),
                    ("Servidor", "`/admin timezone` define o fuso horário usado pelo bot."),
                ],
            },
            "diversao": {
                "label": "Diversão", "hint": "Jogos e comandos sociais", "section": "fun",
                "description": "Comandos sociais e pequenas brincadeiras.",
                "steps": [
                    ("Jogos", "`/coinflip`, `/dice` e `/eightball` são instantâneos. `/rps` abre uma partida com botões."),
                    ("Social", "`/kiss @usuário` manda um beijo com seu GIF próprio. `/praise` faz a homenagem configurada para os três membros do BN."),
                ],
            },
        }
        page = embed("BN / TUTORIAL", "Um guia de verdade, separado por função. Escolha uma área no menu e siga o fluxo certo para cada tipo de comando.", "system")
        page.add_field(name="Por onde começar", value="Membro: **Comandos normais** e **Economia**.\nStaff: **Moderação**, **Segurança** e **Administração**.", inline=False)
        page.add_field(name="Detalhe importante", value="Os comandos de staff respeitam as permissões do servidor; o tutorial não cria acesso por conta própria.", inline=False)
        view = TutorialView(categories)
        await interaction.response.send_message(embed=page, view=view, ephemeral=True)
        try:
            view.message = await interaction.original_response()
        except discord.HTTPException:
            pass


    @command_rate_limit("history", 5)
    @app_commands.command(name="history", description="Mostra os últimos comandos usados no servidor, separados por categoria.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(category=[
        app_commands.Choice(name="Todos", value="all"),
        app_commands.Choice(name="Normais", value="normal"),
        app_commands.Choice(name="Economia", value="economia"),
        app_commands.Choice(name="Progressão", value="progressao"),
        app_commands.Choice(name="Moderação", value="moderacao"),
        app_commands.Choice(name="Comunidade", value="comunidade"),
        app_commands.Choice(name="Segurança", value="seguranca"),
        app_commands.Choice(name="Administração", value="administracao"),
        app_commands.Choice(name="Diversão", value="diversao"),
    ])
    @app_commands.describe(limit="Quantidade de registros", category="Filtre por categoria")
    async def history(self, interaction: discord.Interaction, limit: app_commands.Range[int, 5, 50] = 25, category: str = "all") -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            stmt = select(CommandUsage).where(CommandUsage.guild_id == guild.id).order_by(desc(CommandUsage.used_at)).limit(int(limit))
            if category != "all":
                stmt = select(CommandUsage).where(CommandUsage.guild_id == guild.id, CommandUsage.category == category).order_by(desc(CommandUsage.used_at)).limit(int(limit))
            rows = list((await session.execute(stmt)).scalars().all())
        page = embed("BN / HISTÓRICO DE COMANDOS", "Leitura dos últimos comandos usados neste servidor.", "system")
        if not rows:
            page.add_field(name="Sem registros", value="Ainda não há uso de comandos registrado para este filtro.", inline=False)
        else:
            grouped: dict[str, list[str]] = {}
            for row in rows:
                member = guild.get_member(row.user_id)
                actor = member.mention if member else f"<@{row.user_id}>"
                state = "OK" if row.success else f"ERRO: {row.error_type or 'desconhecido'}"
                timestamp = discord.utils.format_dt(row.used_at, "R")
                grouped.setdefault(row.category, []).append(f"{timestamp} · {actor} · `/{row.command_name}` · {state}")
            order = ("administracao", "moderacao", "seguranca", "comunidade", "economia", "progressao", "diversao", "normal")
            for key in order:
                lines = grouped.get(key)
                if not lines:
                    continue
                label = CATEGORY_LABELS.get(key, key.title())
                page.add_field(name=f"{label} · {len(lines)}", value="\n".join(lines)[:1024], inline=False)
            page.add_field(name="Filtro", value="Todos" if category == "all" else CATEGORY_LABELS.get(category, category), inline=True)
            page.add_field(name="Registros", value=f"`{len(rows)}`", inline=True)
        await respond(interaction, embed=page, ephemeral=True)

    @command_rate_limit("testall", 30)
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
        critical_failures = [result for result in failed_results if diagnostic_severity(result) == "CRÍTICO"]
        warning_failures = [result for result in failed_results if diagnostic_severity(result) == "ATENÇÃO"]
        per_page = 8
        pages: list[discord.Embed] = []
        chunks = [results[index:index + per_page] for index in range(0, len(results), per_page)]
        page_count = len(chunks)
        for index, chunk in enumerate(chunks):
            if index == 0:
                description = f"**{passed} OK** · **{failed} falhas** · `{len(results)} testes` · `{elapsed:.2f}s`"
            else:
                description = f"Página {index + 1} de {page_count} · relatório técnico"
            page = embed("BN / TESTALL", description, "system")
            for result in chunk:
                marker = diagnostic_severity(result)
                page.add_field(name=f"{marker} · {result.name}", value=result.detail[:1024], inline=False)
            if index == 0:
                summary = " · ".join(result.name for result in failed_results[:6]) if failed_results else "Integridade geral confirmada."
                page.add_field(name="Leitura rápida", value=summary, inline=False)
                page.add_field(name="Severidade", value=f"Críticos: `{len(critical_failures)}`\nAtenção: `{len(warning_failures)}`", inline=True)
                page.add_field(name="Saúde", value=f"{bar(passed, len(results), 16)}\n`{passed}/{len(results)}` verificações OK", inline=True)
            page.set_footer(text=f"BN Bot · sistema · página {index + 1}/{page_count}")
            pages.append(page)
        view = TestallView(interaction.user.id, pages, failed_results)
        await interaction.edit_original_response(embed=pages[0], view=view)
        try:
            async with session_factory() as session:
                session.add(AuditLog(id=secrets.randbits(62), guild_id=guild.id, executor_id=interaction.user.id, action="diagnostic.testall", resource="bot", before_state=None, after_state={"passed": passed, "failed": failed, "checks": len(results), "elapsed_seconds": round(elapsed, 3), "failed_checks": [result.name for result in failed_results[:20]]}, created_at=utc_now()))
                await session.commit()
        except Exception:
            logger.exception("testall audit persistence failed guild=%s", guild.id)
