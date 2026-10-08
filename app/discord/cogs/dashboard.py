from __future__ import annotations

import inspect
import logging
import math
import re
import secrets
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import CooldownActive, InsufficientFunds, NotFound, ValidationFailure
from app.core.interactions import respond
from app.core.validation import parse_snowflake
from app.discord.theme import embed, ledger
from app.repositories.analytics import record_command_usage
from app.core.db import session_factory

from app.services.rate_limits import command_rate_limit
logger = logging.getLogger("bn_bot.dashboard")


CATEGORY_INFO = {
    "system": {"label": "Geral", "section": "system", "style": discord.ButtonStyle.secondary},
    "economy": {"label": "Economia", "section": "economy", "style": discord.ButtonStyle.success},
    "progression": {"label": "Progressão", "section": "progression", "style": discord.ButtonStyle.primary},
    "moderation": {"label": "Moderação", "section": "moderation", "style": discord.ButtonStyle.danger},
    "community": {"label": "Comunidade", "section": "community", "style": discord.ButtonStyle.primary},
    "security": {"label": "Segurança", "section": "security", "style": discord.ButtonStyle.danger},
    "admin": {"label": "Administração", "section": "admin", "style": discord.ButtonStyle.secondary},
    "fun": {"label": "Diversão", "section": "fun", "style": discord.ButtonStyle.success},
}

CATEGORY_RULES = {
    "economy": {"balance", "bank", "deposit", "withdraw", "pay", "daily", "weekly", "shop", "buy", "sell", "inventory", "transactions", "jobs", "job", "work"},
    "progression": {"profile", "rep", "reps", "leaderboard"},
    "moderation": {"warn", "t-warn", "warns", "unwarn", "clearwarns", "timeout", "untimeout", "unmute", "kick", "ban", "unban", "purge"},
    "community": {"ticket", "ticket-close", "ticket-reopen", "ticket-claim", "ticket-config", "suggest", "suggestion-status", "report", "report-status", "giveaway", "poll", "community-config"},
    "security": {"automod", "antiraid"},
    "admin": {"admin"},
    "fun": {"coinflip", "dice", "rps", "eightball", "kiss", "praise"},
}

CONFIRM_COMMANDS = {
    "ban",
    "kick",
    "timeout",
    "untimeout",
    "unmute",
    "purge",
    "unban",
    "clearwarns",
    "admin credit",
    "admin debit",
    "admin shop-add",
    "admin rewards",
    "admin job-add",
    "admin job-remove",
    "automod enable",
    "automod disable",
    "automod setup",
    "automod rule-add",
    "automod rule-update",
    "automod rule-delete",
    "automod list-action",
    "automod list-add",
    "automod list-remove",
    "antiraid setup",
    "antiraid enable",
    "antiraid disable",
    "antiraid configure",
    "antiraid unlock",
    "giveaway end",
    "giveaway reroll",
    "giveaway cancel",
    "poll end",
    "ticket-close",
    "warn", "t-warn", "unwarn", "clearwarns", "untimeout", "unmute",
    "deposit", "withdraw", "pay", "buy", "sell", "daily", "weekly", "job", "work", "rep",
    "ticket", "ticket-claim", "ticket-reopen", "ticket-config",
    "suggest", "suggestion-status", "report", "report-status", "community-config",
    "giveaway create", "poll create",
}



def command_mode(command: app_commands.Command[Any, Any, Any]) -> tuple[str, str]:
    if command.qualified_name in CONFIRM_COMMANDS:
        return "confirm", "Confirmação"
    if getattr(command, "parameters", None):
        return "form", "Formulário"
    return "direct", "Direto"


OPTION_PLACEHOLDERS = {
    3: "Texto",
    4: "Número inteiro",
    5: "true ou false",
    6: "@usuário ou ID",
    7: "#canal ou ID",
    8: "@cargo ou ID",
    9: "@membro/cargo ou ID",
    10: "Número",
    11: "Anexo",
}


def command_category(qualified_name: str) -> str:
    root = qualified_name.split(" ", 1)[0]
    for category, roots in CATEGORY_RULES.items():
        if root in roots:
            return category
    return "system"


def option_type_value(parameter: Any) -> int:
    value = getattr(getattr(parameter, "type", None), "value", getattr(parameter, "type", 0))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def annotation_text(command: app_commands.Command[Any, Any, Any], parameter_name: str) -> str:
    try:
        signature = inspect.signature(command.callback)
        parameter = signature.parameters.get(parameter_name)
        if parameter is None:
            return ""
        return str(parameter.annotation)
    except (TypeError, ValueError):
        return ""


def parameter_label(parameter: Any) -> str:
    return str(getattr(parameter, "display_name", None) or getattr(parameter, "name", "Parâmetro"))[:45]


def parameter_help(parameter: Any) -> str:
    description = str(getattr(parameter, "description", "") or "").strip()
    options = list(getattr(parameter, "choices", []) or [])
    if options:
        choice_text = ", ".join(str(choice.name) for choice in options[:8])
        description = f"{description} · opções: {choice_text}" if description else f"Opções: {choice_text}"
    if not description:
        description = OPTION_PLACEHOLDERS.get(option_type_value(parameter), "Valor")
    return description[:100]


def is_optional_empty(parameter: Any, raw: str) -> bool:
    return not raw.strip() and not bool(getattr(parameter, "required", False))


def default_value(parameter: Any) -> Any:
    value = getattr(parameter, "default", None)
    if value is discord.utils.MISSING:
        return None
    return value


def parse_bool(raw: str) -> bool:
    normalized = raw.strip().casefold()
    if normalized in {"true", "1", "sim", "s", "yes", "y"}:
        return True
    if normalized in {"false", "0", "não", "nao", "n", "no"}:
        return False
    raise ValueError("Informe sim/não ou true/false.")


def parse_numeric(parameter: Any, raw: str) -> int | float:
    kind = option_type_value(parameter)
    try:
        value: int | float = int(raw.strip()) if kind == 4 else float(raw.strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("Informe um número válido.") from exc
    if not math.isfinite(float(value)):
        raise ValueError("Informe um número finito.")
    minimum = getattr(parameter, "min_value", None)
    maximum = getattr(parameter, "max_value", None)
    if minimum is not None and value < minimum:
        raise ValueError(f"O valor mínimo é {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"O valor máximo é {maximum}.")
    return value


def parse_choice(parameter: Any, raw: str, expects_choice: bool = False) -> Any:
    choices = list(getattr(parameter, "choices", []) or [])
    if not choices:
        return raw
    normalized = raw.strip().casefold()
    for choice in choices:
        if normalized in {str(choice.name).casefold(), str(choice.value).casefold()}:
            return choice if expects_choice else choice.value
    allowed = ", ".join(str(choice.name) for choice in choices[:8])
    raise ValueError(f"Escolha uma opção válida: {allowed}.")


async def parse_discord_object(interaction: discord.Interaction, command: app_commands.Command[Any, Any, Any], parameter: Any, raw: str) -> Any:
    guild = interaction.guild
    if guild is None:
        raise ValueError("Este comando precisa ser usado em um servidor.")
    value = raw.strip()
    mention_match = re.fullmatch(r"<@!?([0-9]+)>|<#([0-9]+)>|<@&([0-9]+)>", value)
    if mention_match:
        value = next(group for group in mention_match.groups() if group is not None)
    try:
        object_id = parse_snowflake(value)
    except ValueError as exc:
        raise ValueError("Informe uma menção ou ID válido do Discord.") from exc
    annotation = annotation_text(command, parameter.name)
    if "discord.Role" in annotation:
        role = guild.get_role(object_id)
        if role is None:
            raise ValueError("Cargo não encontrado neste servidor.")
        return role
    if "Channel" in annotation:
        channel = guild.get_channel(object_id)
        if channel is None:
            raise ValueError("Canal não encontrado neste servidor.")
        allowed_types = list(getattr(parameter, "channel_types", []) or [])
        if allowed_types and not any(getattr(channel.type, "value", channel.type) == getattr(item, "value", item) for item in allowed_types):
            raise ValueError("Este canal não possui um tipo aceito pelo comando.")
        return channel
    if "discord.Member" in annotation:
        member = guild.get_member(object_id)
        if member is None:
            try:
                member = await guild.fetch_member(object_id)
            except (discord.NotFound, discord.HTTPException) as exc:
                raise ValueError("Membro não encontrado neste servidor.") from exc
        return member
    if "discord.User" in annotation:
        user = command.binding.bot.get_user(object_id) if getattr(command, "binding", None) and hasattr(command.binding, "bot") else None
        if user is None:
            user = interaction.client.get_user(object_id)
        if user is None:
            try:
                user = await interaction.client.fetch_user(object_id)
            except (discord.NotFound, discord.HTTPException) as exc:
                raise ValueError("Usuário não encontrado.") from exc
        return user
    member = guild.get_member(object_id)
    if member is not None:
        return member
    role = guild.get_role(object_id)
    if role is not None:
        return role
    raise ValueError("Usuário ou cargo não encontrado neste servidor.")


async def parse_parameter(interaction: discord.Interaction, command: app_commands.Command[Any, Any, Any], parameter: Any, raw: str) -> Any:
    if is_optional_empty(parameter, raw):
        return default_value(parameter)
    if not str(raw).strip() and getattr(parameter, "required", False):
        raise ValueError(f"O campo {parameter_label(parameter)} é obrigatório.")
    choices = getattr(parameter, "choices", None)
    if choices:
        expects_choice = "Choice" in annotation_text(command, parameter.name)
        return parse_choice(parameter, raw, expects_choice=expects_choice)
    kind = option_type_value(parameter)
    if kind == 3:
        value = raw.strip()
        minimum = getattr(parameter, "min_value", None)
        maximum = getattr(parameter, "max_value", None)
        if minimum is not None and len(value) < int(minimum):
            raise ValueError(f"O texto precisa ter pelo menos {int(minimum)} caracteres.")
        if maximum is not None and len(value) > int(maximum):
            raise ValueError(f"O texto precisa ter no máximo {int(maximum)} caracteres.")
        return value
    if kind in {4, 10}:
        return parse_numeric(parameter, raw)
    if kind == 5:
        return parse_bool(raw)
    if kind in {6, 7, 8, 9}:
        return await parse_discord_object(interaction, command, parameter, raw)
    if kind == 11:
        raise ValueError("Este dashboard não recebe anexos por modal para este comando.")
    raise ValueError(f"Tipo de parâmetro não suportado: {kind}.")


class DashboardView(discord.ui.View):
    def __init__(self, cog: "DashboardCog", owner_id: int, timeout: float = 600) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = owner_id
        self.message: discord.Message | discord.InteractionMessage | None = None
        self.interaction: discord.Interaction | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        try:
            await interaction.response.send_message("Este painel pertence a outro membro.", ephemeral=True)
        except discord.HTTPException:
            pass
        return False

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.interaction is not None and not self.interaction.is_expired():
            try:
                await self.interaction.edit_original_response(view=self)
                return
            except (discord.HTTPException, discord.NotFound, discord.Forbidden):
                pass
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.HTTPException, discord.NotFound, discord.Forbidden):
                pass


class DashboardHomeView(DashboardView):
    def __init__(self, cog: "DashboardCog", owner_id: int) -> None:
        super().__init__(cog, owner_id)
        for index, (category, info) in enumerate(CATEGORY_INFO.items()):
            row = 0 if index < 5 else 1
            button = discord.ui.Button(label=info["label"], style=info["style"], row=row, custom_id=f"bn:dashboard:{owner_id}:{category}")
            button.callback = self.make_category_callback(category)
            self.add_item(button)

    def make_category_callback(self, category: str):
        async def callback(interaction: discord.Interaction) -> None:
            await self.cog.show_category(interaction, self.owner_id, category, 0)
        return callback


class DashboardCategorySelect(discord.ui.Select):
    def __init__(self, cog: "DashboardCog", owner_id: int, selected_category: str) -> None:
        options = [
            discord.SelectOption(
                label=info["label"],
                value=category,
                description=f"Abrir {info["label"].lower()}",
                default=category == selected_category,
            )
            for category, info in CATEGORY_INFO.items()
        ]
        super().__init__(placeholder="Trocar de área", options=options, row=0)
        self.cog = cog
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.show_category(interaction, self.owner_id, self.values[0], 0)


class DashboardCategoryView(DashboardView):
    def __init__(self, cog: "DashboardCog", owner_id: int, category: str, commands_list: list[app_commands.Command[Any, Any, Any]], page: int) -> None:
        super().__init__(cog, owner_id)
        self.category = category
        self.commands_list = commands_list
        self.page = page
        per_page = 10
        start = page * per_page
        current = commands_list[start:start + per_page]
        info = CATEGORY_INFO[category]
        for index, command in enumerate(current):
            label = f"/{command.qualified_name}"[:80]
            button = discord.ui.Button(label=label, style=info["style"], row=1 + index // 5, custom_id=f"bn:dashboard:{owner_id}:run:{secrets.token_hex(6)}")
            button.callback = self.make_command_callback(command)
            self.add_item(button)
        self.add_item(DashboardCategorySelect(cog, owner_id, category))
        nav_row = 3
        home = discord.ui.Button(label="Início", style=discord.ButtonStyle.secondary, row=nav_row, custom_id=f"bn:dashboard:{owner_id}:home:{secrets.token_hex(4)}")
        home.callback = self.home_callback
        self.add_item(home)
        previous = discord.ui.Button(label="Anterior", style=discord.ButtonStyle.secondary, row=nav_row, disabled=page <= 0, custom_id=f"bn:dashboard:{owner_id}:prev:{secrets.token_hex(4)}")
        previous.callback = self.previous_callback
        self.add_item(previous)
        next_page = discord.ui.Button(label="Próxima", style=discord.ButtonStyle.secondary, row=nav_row, disabled=start + per_page >= len(commands_list), custom_id=f"bn:dashboard:{owner_id}:next:{secrets.token_hex(4)}")
        next_page.callback = self.next_callback
        self.add_item(next_page)
        close = discord.ui.Button(label="Fechar", style=discord.ButtonStyle.secondary, row=nav_row, custom_id=f"bn:dashboard:{owner_id}:close:{secrets.token_hex(4)}")
        close.callback = self.close_callback
        self.add_item(close)

    def make_command_callback(self, command: app_commands.Command[Any, Any, Any]):
        async def callback(interaction: discord.Interaction) -> None:
            await self.cog.start_command(interaction, self.owner_id, command)
        return callback

    async def home_callback(self, interaction: discord.Interaction) -> None:
        await self.cog.show_home(interaction, self.owner_id)

    async def previous_callback(self, interaction: discord.Interaction) -> None:
        await self.cog.show_category(interaction, self.owner_id, self.category, max(self.page - 1, 0))

    async def next_callback(self, interaction: discord.Interaction) -> None:
        await self.cog.show_category(interaction, self.owner_id, self.category, self.page + 1)

    async def close_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="Painel encerrado.", embed=None, view=None)


class DashboardConfirmView(DashboardView):
    def __init__(self, cog: "DashboardCog", owner_id: int, command: app_commands.Command[Any, Any, Any], values: dict[str, Any]) -> None:
        super().__init__(cog, owner_id, timeout=120)
        self.command = command
        self.values = values
        confirm = discord.ui.Button(label="Executar", style=discord.ButtonStyle.danger, custom_id=f"bn:dashboard:{owner_id}:confirm:{secrets.token_hex(6)}")
        cancel = discord.ui.Button(label="Cancelar", style=discord.ButtonStyle.secondary, custom_id=f"bn:dashboard:{owner_id}:cancel:{secrets.token_hex(6)}")
        confirm.callback = self.confirm_callback
        cancel.callback = self.cancel_callback
        self.add_item(confirm)
        self.add_item(cancel)

    async def confirm_callback(self, interaction: discord.Interaction) -> None:
        try:
            await self.cog.execute_command(interaction, self.command, self.values)
        finally:
            if not interaction.is_expired():
                try:
                    await interaction.edit_original_response(view=None)
                except (discord.HTTPException, discord.NotFound, discord.Forbidden):
                    pass

    async def cancel_callback(self, interaction: discord.Interaction) -> None:
        page = embed("Ação cancelada", f"`/{self.command.qualified_name}` não foi executado.", "system")
        await interaction.response.edit_message(embed=page, view=None)


class DashboardModal(discord.ui.Modal):
    def __init__(self, cog: "DashboardCog", owner_id: int, command: app_commands.Command[Any, Any, Any], parameters: list[Any], start: int, values: dict[str, Any]) -> None:
        super().__init__(title=f"/{command.qualified_name}"[:45], timeout=600)
        self.cog = cog
        self.owner_id = owner_id
        self.command = command
        self.parameters = parameters
        self.start = start
        self.values = values
        self.inputs: list[tuple[Any, discord.ui.TextInput]] = []
        for parameter in parameters[start:start + 5]:
            input_field = discord.ui.TextInput(
                label=parameter_label(parameter),
                placeholder=parameter_help(parameter)[:100],
                required=bool(getattr(parameter, "required", False)),
                default=self._default_text(parameter),
                max_length=min(int(getattr(parameter, "max_value", 4000) or 4000), 4000) if option_type_value(parameter) == 3 else 4000,
                style=discord.TextStyle.paragraph if option_type_value(parameter) == 3 else discord.TextStyle.short,
            )
            self.inputs.append((parameter, input_field))
            self.add_item(input_field)

    @staticmethod
    def _default_text(parameter: Any) -> Any:
        value = default_value(parameter)
        if value is None or value == "":
            return None
        if hasattr(value, "name") and hasattr(value, "value"):
            return str(value.name)
        return str(value)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            for parameter, input_field in self.inputs:
                self.values[parameter.name] = await parse_parameter(interaction, self.command, parameter, str(input_field.value))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        next_start = self.start + 5
        if next_start < len(self.parameters):
            await interaction.response.send_modal(DashboardModal(self.cog, self.owner_id, self.command, self.parameters, next_start, self.values))
            return
        await self.cog.confirm_or_execute(interaction, self.owner_id, self.command, self.values)


class DashboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @command_rate_limit("dashboard", 5)
    @app_commands.command(name="dashboard", description="Abre o painel interativo de comandos do BN Bot.")
    @app_commands.guild_only()
    async def dashboard(self, interaction: discord.Interaction) -> None:
        page = self.home_embed()
        view = DashboardHomeView(self, interaction.user.id)
        try:
            await interaction.response.send_message(
                embed=page,
                view=view,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            view.interaction = interaction
        except discord.HTTPException as exc:
            logger.exception(
                "dashboard initial response rejected status=%s code=%s text=%s",
                getattr(exc, "status", None),
                getattr(exc, "code", None),
                getattr(exc, "text", None),
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "O painel não pôde ser aberto. Tente novamente.",
                    ephemeral=True,
                )

    def commands_by_category(self) -> dict[str, list[app_commands.Command[Any, Any, Any]]]:
        result = {category: [] for category in CATEGORY_INFO}
        for command in self.bot.tree.walk_commands():
            if getattr(command, "commands", None):
                continue
            result[command_category(command.qualified_name)].append(command)
        for values in result.values():
            values.sort(key=lambda command: command.qualified_name)
        return result

    def home_embed(self) -> discord.Embed:
        grouped = self.commands_by_category()
        lines = [
            "Um painel visual para explorar e executar os comandos do BN Bot.",
            "Escolha uma área, abra uma página e clique no comando que você deseja usar.",
        ]
        total_commands = sum(len(values) for values in grouped.values())
        page = embed("BN Bot · PAINEL DE COMANDOS", "\n".join(lines), "system")
        if self.bot.user is not None:
            page.set_thumbnail(url=self.bot.user.display_avatar.url)
        active_categories = len([values for values in grouped.values() if values])
        direct = sum(1 for values in grouped.values() for command in values if command_mode(command)[0] == "direct")
        forms = sum(1 for values in grouped.values() for command in values if command_mode(command)[0] == "form")
        confirmations = sum(1 for values in grouped.values() for command in values if command_mode(command)[0] == "confirm")
        page.add_field(name="Catálogo", value=f"`{total_commands}` comandos · `{active_categories}` áreas", inline=True)
        page.add_field(name="Execução", value=f"`{direct}` diretos\n`{forms}` com formulário\n`{confirmations}` com confirmação", inline=True)
        page.add_field(name="Navegação", value="Entre nas áreas, percorra as páginas e abra qualquer comando sem sair do Discord.", inline=False)
        for category, info in CATEGORY_INFO.items():
            commands_list = grouped[category]
            preview = " · ".join(f"`/{command.qualified_name}`" for command in commands_list[:3]) or "nenhum"
            if len(commands_list) > 3:
                preview += f" · +{len(commands_list) - 3}"
            page.add_field(name=f"{info['label']} · {len(commands_list)}", value=preview, inline=False)
        page.add_field(name="Como funciona", value=ledger([
            ("Escolha", "abra uma categoria"),
            ("Comando", "clique no comando desejado"),
            ("Parâmetros", "preencha os campos apresentados"),
            ("Execução", "o próprio comando é chamado com as validações normais"),
        ]), inline=False)
        return page

    def category_embed(self, category: str, commands_list: list[app_commands.Command[Any, Any, Any]], page_number: int) -> discord.Embed:
        info = CATEGORY_INFO[category]
        per_page = 10
        page_count = max((len(commands_list) + per_page - 1) // per_page, 1)
        page = embed(f"BN Bot · {info['label']}", f"Página `{page_number + 1}/{page_count}` · escolha um comando para abrir sua execução.", info["section"])
        if self.bot.user is not None:
            page.set_thumbnail(url=self.bot.user.display_avatar.url)
        page.add_field(name="Legenda", value="Direto · formulário · confirmação", inline=False)
        current = commands_list[page_number * per_page:page_number * per_page + per_page]
        for index, command in enumerate(current, start=page_number * per_page + 1):
            parameters = list(getattr(command, "parameters", ()) or [])
            args = " · ".join(f"`{getattr(item, 'display_name', item.name)}`" for item in parameters[:6])
            if len(parameters) > 6:
                args += f" · +{len(parameters) - 6}"
            value = command.description or "Sem descrição."
            _, mode_label = command_mode(command)
            value = f"{mode_label}\n{value}"
            if args:
                value += f"\n{args}"
            page.add_field(name=f"{index:02d} · /{command.qualified_name}", value=value[:1024], inline=True)
        return page

    async def show_home(self, interaction: discord.Interaction, owner_id: int) -> None:
        page = self.home_embed()
        view = DashboardHomeView(self, owner_id)
        view.interaction = interaction
        view.message = interaction.message
        await interaction.response.edit_message(embed=page, view=view)

    async def show_category(self, interaction: discord.Interaction, owner_id: int, category: str, page_number: int) -> None:
        grouped = self.commands_by_category()
        commands_list = grouped.get(category, [])
        max_page = max((len(commands_list) - 1) // 10, 0)
        page_number = min(max(page_number, 0), max_page)
        page = self.category_embed(category, commands_list, page_number)
        view = DashboardCategoryView(self, owner_id, category, commands_list, page_number)
        view.interaction = interaction
        view.message = interaction.message
        await interaction.response.edit_message(embed=page, view=view)

    async def start_command(self, interaction: discord.Interaction, owner_id: int, command: app_commands.Command[Any, Any, Any]) -> None:
        parameters = list(getattr(command, "parameters", ()) or [])
        if not parameters:
            await self.confirm_or_execute(interaction, owner_id, command, {})
            return
        category = command_category(command.qualified_name)
        preview = embed(f"/{command.qualified_name}", command.description or "Preencha os parâmetros para continuar.", category)
        preview.add_field(name="Área", value=CATEGORY_INFO[category]["label"], inline=True)
        preview.add_field(name="Campos", value=f"`{len(parameters)}`", inline=True)
        preview.add_field(name="Execução", value="Preencha os dados abaixo para continuar.", inline=True)
        preview.add_field(name="Parâmetros", value="\n".join(f"`{parameter.name}` · {parameter_help(parameter)}" for parameter in parameters)[:1024], inline=False)
        view = DashboardParameterStartView(self, owner_id, command, parameters)
        await interaction.response.send_message(embed=preview, view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        view.interaction = interaction

    async def confirm_or_execute(self, interaction: discord.Interaction, owner_id: int, command: app_commands.Command[Any, Any, Any], values: dict[str, Any]) -> None:
        if command.qualified_name in CONFIRM_COMMANDS:
            section = command_category(command.qualified_name)
            page = embed("Confirmar ação", f"Você está prestes a executar `/{command.qualified_name}`.", section)
            page.add_field(name="Comando", value=f"`/{command.qualified_name}`", inline=True)
            page.add_field(name="Categoria", value=CATEGORY_INFO[command_category(command.qualified_name)]["label"], inline=True)
            if values:
                summary = "\n".join(f"`{key}` · `{str(value)[:180]}`" for key, value in values.items())
                page.add_field(name="Dados", value=summary[:1024], inline=False)
            view = DashboardConfirmView(self, owner_id, command, values)
            await interaction.response.send_message(embed=page, view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            view.interaction = interaction
            return
        await self.execute_command(interaction, command, values)

    async def execute_command(self, interaction: discord.Interaction, command: app_commands.Command[Any, Any, Any], values: dict[str, Any]) -> None:
        success = False
        error_type = None
        try:
            chain: list[Any] = []
            current = command
            while current is not None:
                chain.append(current)
                current = getattr(current, "parent", None)
            for node in reversed(chain):
                for check in list(getattr(node, "checks", ()) or ()):
                    result = check(interaction)
                    if inspect.isawaitable(result):
                        result = await result
                    if result is False:
                        raise app_commands.CheckFailure("A verificação do comando falhou.")
            if interaction.guild is None and (getattr(command, "guild_only", False) or any("guild_only" in repr(check).casefold() for node in chain for check in getattr(node, "checks", ()) or ())):
                raise app_commands.NoPrivateMessage()
            parameters = list(getattr(command, "parameters", ()) or ())
            missing = [parameter.name for parameter in parameters if getattr(parameter, "required", False) and parameter.name not in values]
            if missing:
                raise ValidationFailure("Preencha todos os campos obrigatórios: " + ", ".join(missing[:8]))
            callback = command.callback
            binding = getattr(command, "binding", None)
            if binding is not None:
                await callback(binding, interaction, **values)
            else:
                await callback(interaction, **values)
            success = True
        except Exception as exc:
            error_type = type(exc).__name__
            await self.send_execution_error(interaction, command, exc)
        finally:
            try:
                async with session_factory() as session:
                    await record_command_usage(session, interaction.user.id, interaction.guild.id if interaction.guild else None, interaction.channel_id, command.qualified_name, success, None if success else error_type or "DashboardExecutionError")
                    await session.commit()
            except SQLAlchemyError:
                logger.exception("dashboard command usage persistence failed command=%s user=%s", command.qualified_name, interaction.user.id)

    async def send_execution_error(self, interaction: discord.Interaction, command: app_commands.Command[Any, Any, Any], exc: Exception) -> None:
        if isinstance(exc, app_commands.errors.MissingPermissions):
            message = "Você não possui a permissão necessária para executar este comando."
        elif isinstance(exc, app_commands.errors.NoPrivateMessage):
            message = "Este comando só pode ser executado em um servidor."
        elif isinstance(exc, discord.Forbidden):
            message = "O BN Bot não possui as permissões necessárias para executar esta ação."
        elif isinstance(exc, discord.NotFound):
            message = "O recurso solicitado não foi encontrado."
        elif isinstance(exc, app_commands.errors.TransformerError):
            message = "Um dos parâmetros informados é inválido."
        elif isinstance(exc, SQLAlchemyError):
            message = "O banco de dados recusou a operação. Tente novamente."
        elif isinstance(exc, CooldownActive):
            message = f"Aguarde {exc.seconds}s antes de tentar novamente."
        elif isinstance(exc, InsufficientFunds):
            message = "Saldo insuficiente para concluir a operação."
        elif isinstance(exc, NotFound):
            message = "O recurso solicitado não foi encontrado."
        elif isinstance(exc, ValidationFailure):
            message = str(exc) or "Os dados informados são inválidos."
        elif isinstance(exc, ValueError):
            message = "Os dados informados não podem ser processados."
        elif isinstance(exc, discord.HTTPException):
            message = "O Discord recusou esta ação. Verifique as permissões e tente novamente."
        else:
            message = "Não foi possível executar este comando pelo dashboard."
        page = embed(f"Falha · /{command.qualified_name}", message, "system")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=page, ephemeral=True)
            else:
                await interaction.response.send_message(embed=page, ephemeral=True)
        except discord.HTTPException:
            pass


class DashboardParameterStartView(DashboardView):
    def __init__(self, cog: DashboardCog, owner_id: int, command: app_commands.Command[Any, Any, Any], parameters: list[Any]) -> None:
        super().__init__(cog, owner_id, timeout=600)
        self.command = command
        self.parameters = parameters
        open_modal = discord.ui.Button(label="Preencher parâmetros", style=CATEGORY_INFO[command_category(command.qualified_name)]["style"], row=0, custom_id=f"bn:dashboard:{owner_id}:params:{secrets.token_hex(6)}")
        open_modal.callback = self.open_modal_callback
        self.add_item(open_modal)
        back = discord.ui.Button(label="Voltar", style=discord.ButtonStyle.secondary, row=0, custom_id=f"bn:dashboard:{owner_id}:back:{secrets.token_hex(6)}")
        back.callback = self.back_callback
        self.add_item(back)

    async def open_modal_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(DashboardModal(self.cog, self.owner_id, self.command, self.parameters, 0, {}))
        if not interaction.is_expired():
            for item in self.children:
                item.disabled = True
            try:
                await interaction.edit_original_response(view=self)
            except (discord.HTTPException, discord.NotFound, discord.Forbidden):
                pass

    async def back_callback(self, interaction: discord.Interaction) -> None:
        await self.cog.show_category(interaction, self.owner_id, command_category(self.command.qualified_name), 0)


