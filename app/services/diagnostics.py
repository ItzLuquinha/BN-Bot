from __future__ import annotations

import ast
import importlib.metadata
import re
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text

from app.core.db import get_engine, session_factory
from app.config import get_settings
from app.core.redis import redis_client
from app.core.time import utc_now
from app.models import ChannelActivity, EconomyAccount, Experience, Giveaway, GuildSettings, Member, MessageLog, Poll, Reminder, Report, ShopItem, Suggestion, Ticket, UserJob
from app.repositories.economy import add_wallet, buy_item, get_or_create_account, move_bank_to_wallet, move_wallet_to_bank, sell_item, transfer
from app.repositories.guilds import ensure_guild, ensure_user
from app.services.antiraid import JoinContext, calculate_risk
from app.services.automod import MessageContext, RuleDefinition, evaluate_rules, validate_rule_config
from app.services.community import add_poll_vote, cast_suggestion_vote, create_ticket, end_giveaway, end_poll, enter_giveaway, save_ticket_transcript, set_ticket_status, validate_poll_options
from app.services.cooldowns import check_and_set, release
from app.services.levels import add_xp, level_from_xp, required_xp
from app.services.rewards import claim_reward


@dataclass(slots=True)
class DiagnosticResult:
    name: str
    ok: bool
    detail: str


CRITICAL_TABLES = {
    "guilds",
    "users",
    "achievements",
    "audit_logs",
    "auto_responses",
    "automations",
    "backups",
    "channel_activity",
    "cooldowns",
    "custom_commands",
    "economy_accounts",
    "economy_transactions",
    "experiences",
    "giveaways",
    "guild_permissions",
    "guild_settings",
    "integrations",
    "jobs",
    "marriages",
    "member_activity",
    "members",
    "message_logs",
    "moderation_logs",
    "notifications",
    "pets",
    "polls",
    "punishments",
    "quests",
    "reminders",
    "reports",
    "reputation_events",
    "reputations",
    "reward_claims",
    "shop_items",
    "suggestions",
    "temporary_roles",
    "tickets",
    "user_achievements",
    "user_jobs",
    "user_quests",
    "verifications",
    "warnings",
    "inventory_items",
    "poll_votes",
    "suggestion_votes",
    "giveaway_entries",
    "ticket_events",
    "automod_rules",
    "automod_list_entries",
    "automod_events",
    "raid_protection",
    "raid_events",
    "raid_lockdown_channels",
}

SERIAL_TABLES = {
    "achievements",
    "auto_responses",
    "automations",
    "custom_commands",
    "economy_accounts",
    "experiences",
    "guild_permissions",
    "integrations",
    "jobs",
    "marriages",
    "members",
    "pets",
    "quests",
    "reputations",
    "shop_items",
    "inventory_items",
    "user_achievements",
    "user_jobs",
    "user_quests",
    "member_activity",
    "channel_activity",
    "polls",
    "punishments",
    "tickets",
    "warnings",
}
REQUIRED_COMMANDS = {
    "ping",
    "uptime",
    "botinfo",
    "serverinfo",
    "userinfo",
    "avatar",
    "help",
    "testall",
    "dashboard",
    "remind",
    "balance",
    "bank",
    "deposit",
    "withdraw",
    "pay",
    "daily",
    "weekly",
    "shop",
    "buy",
    "sell",
    "inventory",
    "jobs",
    "job",
    "work",
    "profile",
    "rep",
    "reps",
    "leaderboard",
    "warn",
    "warns",
    "unwarn",
    "clearwarns",
    "timeout",
    "kick",
    "ban",
    "unban",
    "purge",
    "ticket",
    "ticket-close",
    "ticket-reopen",
    "ticket-claim",
    "ticket-config",
    "suggest",
    "suggestion-status",
    "report",
    "report-status",
    "giveaway create",
    "giveaway end",
    "giveaway reroll",
    "giveaway cancel",
    "poll create",
    "poll end",
    "community-config",
    "automod",
    "antiraid",
    "admin",
}


IO_ATTRIBUTES = {
    "ban",
    "create_role",
    "create_text_channel",
    "edit",
    "execute",
    "fetch_channel",
    "fetch_message",
    "history",
    "kick",
    "purge",
    "scalar",
    "send",
    "set_permissions",
    "timeout",
    "unban",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _migration_heads() -> set[str]:
    config = Config(str(_project_root() / "alembic.ini"))
    return set(ScriptDirectory.from_config(config).get_heads())


def _command_parameter_map(command: Any) -> dict[str, Any]:
    return {parameter.name: parameter for parameter in getattr(command, "parameters", ())}


def _python_runtime_check() -> DiagnosticResult:
    try:
        in_virtualenv = sys.prefix != sys.base_prefix
        executable = Path(sys.executable).resolve()
        executable_text = str(executable).replace("\\", "/")
        greenlet_ok = True
        try:
            import greenlet as greenlet_module
            greenlet_version = str(getattr(greenlet_module, "__version__", "installed"))
        except Exception as exc:
            greenlet_ok = False
            greenlet_version = f"ausente: {type(exc).__name__}"
        expected_virtualenv = ".venv/" in executable_text.lower()
        ok = in_virtualenv and expected_virtualenv and greenlet_ok
        detail = f"Python: {sys.version.split()[0]} | executável: {executable} | venv: {in_virtualenv} | greenlet: {greenlet_version}"
        return DiagnosticResult("Python runtime", ok, detail if ok else detail + " | use .\\.venv\\Scripts\\Activate.ps1 e instale as dependências no mesmo interpretador")
    except Exception as exc:
        return DiagnosticResult("Python runtime", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _command_matrix_check() -> DiagnosticResult:
    try:
        from app.services.command_matrix import audit_summary
        ok, cases, issues = audit_summary()
        if not ok:
            return DiagnosticResult("Command matrix", False, " | ".join(issues[:8]))
        return DiagnosticResult("Command matrix", True, f"{len(cases)}/{len(cases)} comandos auditados individualmente: resposta, defer, escopo e contrato funcional")
    except Exception as exc:
        return DiagnosticResult("Command matrix", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _command_matrix_details() -> list[DiagnosticResult]:
    try:
        from app.services.command_matrix import audit_commands, case_issues
        results: list[DiagnosticResult] = []
        for case in audit_commands():
            issues = case_issues(case)
            status = "OK" if not issues else "falha: " + "; ".join(issues)
            scope = "guild" if case.guild_only else "DM/guild"
            result = DiagnosticResult(
                f"CMD /{case.qualified_name}",
                not issues,
                f"{case.file}:{case.function} | params={case.parameter_count} | escopo={scope} | resposta={'OK' if case.response_path else 'ausente'} | defer={'OK' if case.defer_before_io else 'falha'} | {status}",
            )
            results.append(result)
        return results
    except Exception as exc:
        return [DiagnosticResult("Command matrix details", False, f"{type(exc).__name__}: {str(exc)[:220]}")]


def _command_check(bot: Any) -> DiagnosticResult:
    command_objects = list(bot.tree.walk_commands())
    leaf_commands = [command for command in command_objects if not getattr(command, "commands", None)]
    group_commands = [command for command in command_objects if getattr(command, "commands", None)]
    command_names = [command.qualified_name for command in leaf_commands]
    all_names = [command.qualified_name for command in command_objects]
    duplicates = sorted({name for name in command_names if command_names.count(name) > 1})
    missing = sorted(name for name in REQUIRED_COMMANDS if name not in all_names)
    malformed = sorted(
        command.qualified_name
        for command in command_objects
        if not str(command.description or "").strip() or len(command.name) > 32 or len(str(command.description)) > 100 or len(getattr(command, "parameters", ())) > 25
    )
    parameter_metadata_issues: list[str] = []
    ordering_issues: list[str] = []
    for command in leaf_commands:
        optional_seen = False
        for parameter in getattr(command, "parameters", ()):
            if not str(parameter.name or "").strip() or len(parameter.name) > 32 or not str(parameter.description or "").strip() or len(str(parameter.description)) > 100:
                parameter_metadata_issues.append(f"{command.qualified_name}:{parameter.name}")
            if parameter.required and optional_seen:
                ordering_issues.append(f"{command.qualified_name}:{parameter.name}")
            elif not parameter.required:
                optional_seen = True
    poll_create = next((command for command in leaf_commands if command.qualified_name == "poll create"), None)
    poll_interface_error = None
    if poll_create is None:
        poll_interface_error = "poll create ausente"
    else:
        parameters = _command_parameter_map(poll_create)
        required = [parameters.get(name) for name in ("question", "option1", "option2")]
        optional = [parameters.get(f"option{index}") for index in range(3, 11)]
        if any(parameter is None or not parameter.required for parameter in required):
            poll_interface_error = "poll create não possui pergunta, opção 1 e opção 2 obrigatórias"
        elif any(parameter is None or parameter.required for parameter in optional):
            poll_interface_error = "poll create possui opções opcionais configuradas como obrigatórias"
        elif parameters.get("duration_minutes") is None or parameters["duration_minutes"].required:
            poll_interface_error = "poll create possui duração inválida"
    issues: list[str] = []
    if duplicates:
        issues.append(f"duplicados: {', '.join(duplicates[:5])}")
    if missing:
        issues.append(f"ausentes: {', '.join(missing[:8])}")
    if malformed:
        issues.append(f"metadados inválidos: {', '.join(malformed[:5])}")
    if ordering_issues:
        issues.append(f"ordem de parâmetros inválida: {', '.join(ordering_issues[:5])}")
    if parameter_metadata_issues:
        issues.append(f"metadados de parâmetros inválidos: {', '.join(parameter_metadata_issues[:5])}")
    if poll_interface_error:
        issues.append(poll_interface_error)
    if issues:
        return DiagnosticResult("Comandos", False, " | ".join(issues))
    return DiagnosticResult("Comandos", True, f"{len(command_names)} comandos executáveis + {len(group_commands)} grupos, sem duplicações e poll com 2 opções obrigatórias")


def _is_command_callback(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    for decorator in node.decorator_list:
        text_value = ast.unparse(decorator)
        if text_value.endswith(".command") or ".command(" in text_value or text_value.startswith("app_commands.command"):
            return True
    return False


def _called_name(node: ast.AST) -> str:
    return ast.unparse(node)


def _is_defer_call(call: ast.Call) -> bool:
    name = _called_name(call.func)
    return name == "defer" or name == "interaction.response.defer" or name.endswith(".defer")


def _enum_int(value: Any, default: int = 0) -> int:
    raw = getattr(value, "value", value)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _is_io_call(call: ast.Call) -> bool:
    name = _called_name(call.func)
    if name == "session_factory" or name.startswith("redis_client.") or name.endswith("check_and_set"):
        return True
    if name.startswith("session."):
        return name.rsplit(".", 1)[-1] in {"execute", "get", "scalar", "flush", "commit", "rollback", "delete"}
    if name.startswith("interaction.response.") or name.startswith("interaction.followup."):
        return False
    final = name.rsplit(".", 1)[-1]
    if final in {"get_guild_settings", "is_staff", "ensure_ticket_channel", "send_channel_message", "refresh_suggestion_message"}:
        return True
    return final in IO_ATTRIBUTES


def _interaction_safety_check() -> DiagnosticResult:
    issues: list[str] = []
    cogs_root = _project_root() / "app" / "discord" / "cogs"
    for path in sorted(cogs_root.glob("*.py")):
        if path.name.startswith("__"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            issues.append(f"{path.name}:{exc.lineno} SyntaxError")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) or not _is_command_callback(node):
                continue
            calls = sorted((call for call in ast.walk(node) if isinstance(call, ast.Call)), key=lambda item: item.lineno)
            defer_lines = [call.lineno for call in calls if _is_defer_call(call)]
            first_defer = min(defer_lines) if defer_lines else None
            direct_response_after = [call.lineno for call in calls if _called_name(call) in {"interaction.response.send_message", "interaction.response.edit_message"} and first_defer is not None and call.lineno > first_defer]
            duplicate_defers = defer_lines[1:]
            io_before_defer = [f"{call.lineno}:{_called_name(call)}" for call in calls if _is_io_call(call) and (first_defer is None or call.lineno < first_defer)]
            if direct_response_after:
                issues.append(f"{path.name}:{node.name} response direto após defer em {direct_response_after[0]}")
            if duplicate_defers:
                issues.append(f"{path.name}:{node.name} múltiplos defer em {duplicate_defers[0]}")
            if io_before_defer:
                issues.append(f"{path.name}:{node.name} I/O antes de defer em {io_before_defer[0]}")
    if issues:
        return DiagnosticResult("Interações", False, " | ".join(issues[:8]))
    return DiagnosticResult("Interações", True, "callbacks com I/O fazem defer antes do trabalho e não respondem duas vezes")


def _component_error_handling_check() -> DiagnosticResult:
    try:
        community_path = _project_root() / "app" / "discord" / "cogs" / "community.py"
        source = community_path.read_text(encoding="utf-8")
        required = [
            "class BNComponentView",
            "async def on_error",
            "class TicketView(BNComponentView)",
            "class SuggestionView(BNComponentView)",
            "class GiveawayView(BNComponentView)",
            "class PollView(BNComponentView)",
        ]
        missing = [item for item in required if item not in source]
        detail = "views persistentes possuem resposta de erro" if not missing else "faltam proteções de erro: " + ", ".join(missing[:4])
        return DiagnosticResult("Component errors", not missing, detail)
    except Exception as exc:
        return DiagnosticResult("Component errors", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _message_logging_check() -> DiagnosticResult:
    try:
        source = (_project_root() / "app" / "repositories" / "analytics.py").read_text(encoding="utf-8")
        ok = "MessageLog(id=message_id" in source and "message_id=message_id" in source
        detail = "message_id é persistido corretamente no log de mensagens" if ok else "record_message não preenche message_id"
        return DiagnosticResult("Message logging", ok, detail)
    except Exception as exc:
        return DiagnosticResult("Message logging", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _admin_command_layout_check(bot: Any) -> DiagnosticResult:
    try:
        admin = bot.tree.get_command("admin")
        if admin is None:
            return DiagnosticResult("Admin command layout", False, "grupo /admin não registrado")
        names = {command.name for command in getattr(admin, "commands", [])}
        required = {"credit", "debit", "shop-add", "job-add", "timezone"}
        missing = sorted(required - names)
        if bot.tree.get_command("credit") is not None:
            missing.append("credit está duplicado fora de /admin")
        detail = "/admin contém os comandos administrativos esperados" if not missing else " | ".join(missing[:8])
        return DiagnosticResult("Admin command layout", not missing, detail)
    except Exception as exc:
        return DiagnosticResult("Admin command layout", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _response_contract_check() -> DiagnosticResult:
    try:
        source = (_project_root() / "app" / "core" / "interactions.py").read_text(encoding="utf-8")
        required = ["if not interaction.response.is_done()", "return await interaction.followup.send"]
        missing = [item for item in required if item not in source]
        detail = "respond() seleciona response ou followup conforme o estado da interaction" if not missing else "contrato de response incompleto"
        return DiagnosticResult("Response contract", not missing, detail)
    except Exception as exc:
        return DiagnosticResult("Response contract", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _command_source_safety_check() -> DiagnosticResult:
    try:
        issues: list[str] = []
        cogs_root = _project_root() / "app" / "discord" / "cogs"
        for path in sorted(cogs_root.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            uses_logger = any(isinstance(node, ast.Name) and node.id == "logger" and isinstance(node.ctx, ast.Load) for node in ast.walk(tree))
            if uses_logger:
                has_logging_import = "import logging" in source or "from logging import" in source
                has_logger_definition = "logging.getLogger(" in source
                if not has_logging_import or not has_logger_definition:
                    issues.append(f"{path.name}:logger sem configuração")
            if "channel.purge(" in source:
                purge_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and _called_name(node.func) == "channel.purge"]
                for call in purge_calls:
                    if not any(keyword.arg == "check" for keyword in call.keywords):
                        issues.append(f"{path.name}:channel.purge sem check")
            if "await self.balance(interaction)" in source:
                issues.append(f"{path.name}:command callback encadeando balance diretamente")
            if re.search(r"\bcheck\s*=\s*None\b", source):
                issues.append(f"{path.name}:check=None em caminho de comando")
        return DiagnosticResult("Command source safety", not issues, "cogs sem padrões de command runtime conhecidos como frágeis" if not issues else " | ".join(issues[:8]))
    except Exception as exc:
        return DiagnosticResult("Command source safety", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _command_serialization_check(bot: Any) -> DiagnosticResult:
    try:
        issues: list[str] = []
        for command in bot.tree.walk_commands():
            try:
                payload = command.to_dict(bot.tree)
            except Exception as exc:
                issues.append(f"{command.qualified_name}: {type(exc).__name__}")
                continue
            if not getattr(command, "commands", None):
                options = payload.get("options") or []
                if len(options) > 25:
                    issues.append(f"{command.qualified_name}: mais de 25 opções")
                for option in options:
                    description = str(option.get("description", ""))
                    if len(description) > 100:
                        issues.append(f"{command.qualified_name}:{option.get('name')}: descrição longa")
        sources = "\n".join(path.read_text(encoding="utf-8") for path in (_project_root() / "app").rglob("*.py"))
        custom_ids = re.findall(r"custom_id\s*=\s*[f\"']([^f\"']+)", sources)
        custom_ids += re.findall(r"custom_id\s*=\s*\"([^\"]+)\"", sources)
        too_long = [value[:100] for value in custom_ids if len(value) > 100]
        static_duplicates = sorted({value for value in custom_ids if custom_ids.count(value) > 1 and "{" not in value})
        if too_long:
            issues.append(f"custom_id > 100 caracteres: {too_long[0]}")
        if static_duplicates:
            issues.append(f"custom_id estática duplicada: {static_duplicates[0]}")
        return DiagnosticResult("Command payloads", not issues, "comandos serializam e componentes respeitam limites" if not issues else " | ".join(issues[:8]))
    except Exception as exc:
        return DiagnosticResult("Command payloads", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _command_id_input_check() -> DiagnosticResult:
    expected = {
        "ticket_close_command": {"ticket_id": "str"},
        "ticket_reopen_command": {"ticket_id": "str"},
        "ticket_claim_command": {"ticket_id": "str"},
        "suggestion_status": {"suggestion_id": "str"},
        "report_status": {"report_id": "str"},
        "giveaway_end_command": {"giveaway_id": "str"},
        "giveaway_reroll": {"giveaway_id": "str"},
        "giveaway_cancel": {"giveaway_id": "str"},
        "poll_end_command": {"poll_id": "str"},
        "unwarn": {"warning_id": "str"},
        "unban": {"user_id": "str"},
    }
    issues: list[str] = []
    root = _project_root() / "app" / "discord" / "cogs"
    functions: dict[str, ast.AsyncFunctionDef] = {}
    for path in root.glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            issues.append(f"{path.name}:{exc.lineno} SyntaxError")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                functions[node.name] = node
    for name, parameters in expected.items():
        node = functions.get(name)
        if node is None:
            issues.append(f"{name} ausente")
            continue
        annotations = {argument.arg: ast.unparse(argument.annotation) if argument.annotation is not None else "" for argument in node.args.args}
        for parameter, annotation in parameters.items():
            if annotations.get(parameter, "").replace(" ", "") != annotation:
                issues.append(f"{name}:{parameter} deveria ser {annotation}")
    return DiagnosticResult("IDs de comandos", not issues, "IDs Discord de alta faixa usam entrada string e validação Snowflake" if not issues else " | ".join(issues[:8]))


def _command_decorator_check() -> DiagnosticResult:
    try:
        required = {"ticket", "suggest", "suggestion-status", "report", "report-status", "purge", "testall"}
        found: dict[str, str] = {}
        for path in (_project_root() / "app" / "discord" / "cogs").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef):
                    continue
                for decorator in node.decorator_list:
                    text_value = ast.unparse(decorator)
                    if "command(name=" in text_value:
                        for constant in ast.walk(decorator):
                            if isinstance(constant, ast.Constant) and isinstance(constant.value, str) and constant.value in required:
                                found[constant.value] = path.name
        missing = sorted(required - set(found))
        return DiagnosticResult("Decorators de comandos", not missing, "comandos críticos encontrados com decorators slash" if not missing else f"comandos ausentes: {', '.join(missing)}")
    except Exception as exc:
        return DiagnosticResult("Decorators de comandos", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _poll_validation_smoke() -> DiagnosticResult:
    try:
        two = validate_poll_options(["Sim", "Não"])
        ten = validate_poll_options([f"Opção {index}" for index in range(10)])
        cases = [
            ("duplicada", ["Sim", "sim"]),
            ("vazia", ["", "Sim"]),
            ("curta", ["Sim"]),
            ("longa", ["Sim", "x" * 81]),
            ("excesso", [str(index) for index in range(11)]),
        ]
        rejected = 0
        for _, values in cases:
            try:
                validate_poll_options(values)
            except ValueError:
                rejected += 1
        ok = two == ["Sim", "Não"] and len(ten) == 10 and rejected == len(cases)
        return DiagnosticResult("Poll validation", ok, "2 a 10 opções, vazios, duplicadas, longas e excesso validados" if ok else "validação de opções inconsistente")
    except Exception as exc:
        return DiagnosticResult("Poll validation", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _security_surface_check() -> DiagnosticResult:
    try:
        expected = {
            "purge": "has_permissions(manage_messages=True)",
            "warn": "has_permissions(manage_messages=True)",
            "timeout": "has_permissions(moderate_members=True)",
            "kick": "has_permissions(kick_members=True)",
            "ban": "has_permissions(ban_members=True)",
            "unban": "has_permissions(ban_members=True)",
            "automod": "has_permissions(manage_guild=True)",
            "antiraid": "has_permissions(manage_guild=True)",
            "admin": "has_permissions(manage_guild=True)",
        }
        sources = "\n".join(path.read_text(encoding="utf-8") for path in (_project_root() / "app" / "discord" / "cogs").glob("*.py"))
        missing = [name for name, marker in expected.items() if marker not in sources]
        dangerous: list[str] = []
        secret_names = {"DISCORD_TOKEN", "DISCORD_CLIENT_SECRET", "DATABASE_URL", "REDIS_URL", "APP_SECRET_KEY"}
        ignored_values = {"", "changeme", "change-me", "your-token-here", "your-secret-here"}
        for path in (_project_root() / "app").rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                dangerous.append(path.name)
                continue
            for node in ast.walk(tree):
                targets: list[ast.expr] = []
                value: ast.expr | None = None
                if isinstance(node, ast.Assign):
                    targets = list(node.targets)
                    value = node.value
                elif isinstance(node, ast.AnnAssign):
                    targets = [node.target]
                    value = node.value
                if value is None or not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                    continue
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in secret_names:
                        literal = value.value.strip()
                        if literal and literal.casefold() not in ignored_values:
                            dangerous.append(path.name)
                            break
                if path.name in dangerous:
                    break
        unsafe: list[str] = []
        for path in (_project_root() / "app").rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    call_name = ast.unparse(node.func)
                    if call_name in {"eval", "exec", "os.system", "subprocess.call", "subprocess.run", "subprocess.Popen"}:
                        if call_name in {"subprocess.call", "subprocess.run", "subprocess.Popen"}:
                            if any(keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True for keyword in node.keywords):
                                unsafe.append(f"{path.name}:shell=True")
                        else:
                            unsafe.append(f"{path.name}:{call_name}")
                    if call_name in {"pickle.load", "pickle.loads"}:
                        unsafe.append(f"{path.name}:{call_name}")
        unsafe = sorted(set(unsafe))
        issues = []
        if missing:
            issues.append(f"permissões ausentes: {', '.join(missing)}")
        if dangerous:
            issues.append(f"secrets hardcoded: {', '.join(dangerous)}")
        if unsafe:
            issues.append(f"construtos inseguros: {', '.join(unsafe[:6])}")
        return DiagnosticResult("Segurança", not issues, "comandos sensíveis protegidos, secrets fora do código e sem construtos inseguros" if not issues else " | ".join(issues[:5]))
    except Exception as exc:
        return DiagnosticResult("Segurança", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _code_hygiene_check() -> DiagnosticResult:
    try:
        issues = []
        for path in (_project_root() / "app").rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if line.lstrip().startswith("#"):
                    issues.append(f"{path.name}:{number} comentário")
        if chr(0x2014) in "\n".join(path.read_text(encoding="utf-8") for path in (_project_root() / "app").rglob("*.py")):
            issues.append("em-dash")
        return DiagnosticResult("Higiene do código", not issues, "sem comentários no código e sem em-dash" if not issues else " | ".join(issues[:8]))
    except Exception as exc:
        return DiagnosticResult("Higiene do código", False, f"{type(exc).__name__}: {str(exc)[:220]}")


async def _database_checks(results: list[DiagnosticResult]) -> None:
    try:
        async with session_factory() as session:
            value = await session.scalar(text("SELECT 1"))
            identity = await session.execute(text("SELECT current_database(), current_user"))
            database_name, database_user = identity.one()
        results.append(DiagnosticResult("PostgreSQL", value == 1, f"conexão OK | banco: {database_name} | usuário: {database_user}"))
    except Exception as exc:
        results.append(DiagnosticResult("PostgreSQL", False, f"{type(exc).__name__}: {str(exc)[:220]}"))
        return

    try:
        async with session_factory() as session:
            rows = await session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
            present = {str(row[0]) for row in rows.all()}
        missing = sorted(CRITICAL_TABLES - present)
        results.append(DiagnosticResult("Schema", not missing, "tabelas principais presentes" if not missing else f"tabelas ausentes: {', '.join(missing[:12])}"))
    except Exception as exc:
        results.append(DiagnosticResult("Schema", False, f"{type(exc).__name__}: {str(exc)[:220]}"))

    try:
        heads = _migration_heads()
        async with session_factory() as session:
            rows = await session.execute(text("SELECT version_num FROM alembic_version"))
            versions = {str(row[0]) for row in rows.all()}
        ok = bool(versions) and versions == heads
        results.append(DiagnosticResult("Migrations", ok, f"versão atual: {', '.join(sorted(versions)) or 'nenhuma'} | head: {', '.join(sorted(heads))}"))
    except Exception as exc:
        results.append(DiagnosticResult("Migrations", False, f"{type(exc).__name__}: {str(exc)[:220]}"))

    try:
        async with session_factory() as session:
            missing_sequences = []
            for table in sorted(SERIAL_TABLES):
                value = await session.scalar(text("SELECT pg_get_serial_sequence(:table_name, 'id')"), {"table_name": f"public.{table}"})
                if not value:
                    missing_sequences.append(table)
        results.append(DiagnosticResult("Sequences", not missing_sequences, "sequences principais presentes" if not missing_sequences else f"sem sequence: {', '.join(missing_sequences[:10])}"))
    except Exception as exc:
        results.append(DiagnosticResult("Sequences", False, f"{type(exc).__name__}: {str(exc)[:220]}"))

    try:
        expected_constraints = {
            "economy_accounts": "guild_id, user_id",
            "inventory_items": "guild_id, user_id, shop_item_id",
            "user_jobs": "guild_id, user_id",
            "experiences": "guild_id, user_id",
            "poll_votes": "poll_id, user_id",
            "suggestion_votes": "suggestion_id, user_id",
            "giveaway_entries": "giveaway_id, user_id",
        }
        missing_constraints = []
        async with session_factory() as session:
            for table, columns in expected_constraints.items():
                value = await session.scalar(text("SELECT count(*) FROM pg_constraint WHERE conrelid = CAST(:table_name AS regclass) AND contype = 'u' AND pg_get_constraintdef(oid) LIKE :definition"), {"table_name": f"public.{table}", "definition": f"%({columns})%"})
                if not value:
                    missing_constraints.append(table)
        results.append(DiagnosticResult("Constraints", not missing_constraints, "unicidades críticas presentes" if not missing_constraints else f"constraints ausentes: {', '.join(missing_constraints)}"))
    except Exception as exc:
        results.append(DiagnosticResult("Constraints", False, f"{type(exc).__name__}: {str(exc)[:220]}"))

    queries = {
        "negative economy": "SELECT count(*) FROM economy_accounts WHERE wallet < 0 OR bank < 0 OR lifetime_earned < 0 OR lifetime_spent < 0",
        "negative inventory": "SELECT count(*) FROM inventory_items WHERE quantity < 0",
        "invalid shop": "SELECT count(*) FROM shop_items WHERE price <= 0 OR stack_limit <= 0 OR stock < 0",
        "invalid poll options": "SELECT count(*) FROM polls WHERE jsonb_typeof(options::jsonb) <> 'array' OR jsonb_array_length(options::jsonb) < 2 OR jsonb_array_length(options::jsonb) > 10",
        "orphan poll votes": "SELECT count(*) FROM poll_votes vote WHERE NOT EXISTS (SELECT 1 FROM polls poll WHERE poll.id = vote.poll_id)",
        "orphan suggestion votes": "SELECT count(*) FROM suggestion_votes vote WHERE NOT EXISTS (SELECT 1 FROM suggestions item WHERE item.id = vote.suggestion_id)",
        "orphan giveaway entries": "SELECT count(*) FROM giveaway_entries entry WHERE NOT EXISTS (SELECT 1 FROM giveaways item WHERE item.id = entry.giveaway_id)",
        "orphan user jobs": "SELECT count(*) FROM user_jobs item WHERE NOT EXISTS (SELECT 1 FROM jobs job WHERE job.id = item.job_id)",
    }
    try:
        async with session_factory() as session:
            failures = []
            for name, query in queries.items():
                value = int(await session.scalar(text(query)) or 0)
                if value:
                    failures.append(f"{name}: {value}")
        results.append(DiagnosticResult("Integridade", not failures, "saldos, inventário, loja, polls e relações sem violações" if not failures else " | ".join(failures[:8])))
    except Exception as exc:
        results.append(DiagnosticResult("Integridade", False, f"{type(exc).__name__}: {str(exc)[:220]}"))


def _redis_key(prefix: str, guild_id: int) -> str:
    return f"bn:testall:{prefix}:{guild_id}:{secrets.token_hex(8)}"


async def _redis_checks(results: list[DiagnosticResult], guild_id: int) -> None:
    try:
        await redis_client.ping()
        key = _redis_key("roundtrip", guild_id)
        created = await redis_client.set(key, "ok", ex=10, nx=True)
        value = await redis_client.get(key)
        ttl = await redis_client.ttl(key)
        deleted = await redis_client.delete(key)
        ok = bool(created) and value == "ok" and ttl > 0 and deleted == 1
        results.append(DiagnosticResult("Redis", ok, "ping, SET/GET, TTL e DELETE OK" if ok else "roundtrip Redis inconsistente"))
    except Exception as exc:
        results.append(DiagnosticResult("Redis", False, f"{type(exc).__name__}: {str(exc)[:220]}"))
    try:
        key = _redis_key("cooldown", guild_id)
        first = await check_and_set(key, 3)
        second = await check_and_set(key, 3)
        await release(key)
        ok = first is None and second is not None
        results.append(DiagnosticResult("Cooldown", ok, "set inicial e bloqueio subsequente OK" if ok else "cooldown não bloqueou a segunda tentativa"))
    except Exception as exc:
        results.append(DiagnosticResult("Cooldown", False, f"{type(exc).__name__}: {str(exc)[:220]}"))


async def _economy_smoke(guild_id: int, diagnostic_user_id: int) -> DiagnosticResult:
    try:
        async with session_factory() as session:
            await ensure_guild(session, guild_id, f"Guild {guild_id}")
            await ensure_user(session, diagnostic_user_id, str(diagnostic_user_id), str(diagnostic_user_id))
            receiver_id = diagnostic_user_id - 1
            await ensure_user(session, receiver_id, str(receiver_id), str(receiver_id))
            account = await get_or_create_account(session, guild_id, diagnostic_user_id, lock=True)
            receiver = await get_or_create_account(session, guild_id, receiver_id, lock=True)
            await add_wallet(session, guild_id, diagnostic_user_id, 100, "diagnostic")
            await move_wallet_to_bank(session, guild_id, diagnostic_user_id, 40)
            await move_bank_to_wallet(session, guild_id, diagnostic_user_id, 10)
            await transfer(session, guild_id, diagnostic_user_id, receiver_id, 15)
            item = ShopItem(guild_id=guild_id, name=f"__bn_diagnostic_{secrets.token_hex(8)}", description="diagnostic", category="diagnostic", rarity="common", price=10, stock=5, stack_limit=10, metadata_json={}, created_at=utc_now(), updated_at=utc_now())
            session.add(item)
            await session.flush()
            await buy_item(session, guild_id, diagnostic_user_id, item.id, 2)
            await sell_item(session, guild_id, diagnostic_user_id, item.id, 1)
            await session.flush()
            loaded_item = await session.get(ShopItem, item.id)
            inventory_quantity = int(await session.scalar(text("SELECT quantity FROM inventory_items WHERE guild_id = :guild_id AND user_id = :user_id AND shop_item_id = :item_id"), {"guild_id": guild_id, "user_id": diagnostic_user_id, "item_id": item.id}) or 0)
            funds_rejected = False
            try:
                await transfer(session, guild_id, diagnostic_user_id, receiver_id, 10_000)
            except Exception:
                funds_rejected = True
            expected_wallet = 40
            expected_bank = 30
            wallet_value = account.wallet
            bank_value = account.bank
            receiver_wallet_value = receiver.wallet
            loaded_stock_value = loaded_item.stock if loaded_item is not None else None
            ok = wallet_value == expected_wallet and bank_value == expected_bank and receiver_wallet_value == 15 and inventory_quantity == 1 and loaded_item is not None and loaded_stock_value == 4 and funds_rejected
            await session.rollback()
        return DiagnosticResult("Economia", ok, "carteira, banco, transferência, compra, venda, estoque e bloqueio de saldo insuficiente OK em rollback" if ok else f"estado inesperado: wallet={wallet_value} bank={bank_value} receiver={receiver_wallet_value} inventory={inventory_quantity} stock={loaded_stock_value}" )
    except Exception as exc:
        return DiagnosticResult("Economia", False, f"{type(exc).__name__}: {str(exc)[:220]}")


async def _progression_smoke(guild_id: int, diagnostic_user_id: int) -> DiagnosticResult:
    try:
        monotonic = all(required_xp(level) < required_xp(level + 1) for level in range(0, 10))
        level_formula = level_from_xp(0) == 0 and level_from_xp(100) == 1 and level_from_xp(200) == 1 and level_from_xp(500) == 2
        async with session_factory() as session:
            await ensure_guild(session, guild_id, f"Guild {guild_id}")
            await ensure_user(session, diagnostic_user_id, str(diagnostic_user_id), str(diagnostic_user_id))
            total_xp, level, leveled = await add_xp(session, guild_id, diagnostic_user_id, 101)
            row = await session.scalar(select(Experience).where(Experience.guild_id == guild_id, Experience.user_id == diagnostic_user_id))
            first_row_total = row.total_xp if row is not None else None
            first_row_level = row.level if row is not None else None
            second_total, second_level, second_leveled = await add_xp(session, guild_id, diagnostic_user_id, 399)
            ok = monotonic and level_formula and total_xp == 101 and level == 1 and leveled and row is not None and first_row_total == 101 and first_row_level == 1 and second_total == 500 and second_level == 2 and second_leveled
            await session.rollback()
        return DiagnosticResult("XP", ok, "fórmula, flush, criação da linha, persistência, level up e progressão de segundo nível OK em rollback" if ok else f"progressão retornou estado inesperado: total={second_total} level={second_level} leveled={second_leveled}")
    except Exception as exc:
        return DiagnosticResult("XP", False, f"{type(exc).__name__}: {str(exc)[:220]}")


async def _rewards_smoke(guild_id: int, diagnostic_user_id: int) -> DiagnosticResult:
    try:
        async with session_factory() as session:
            await ensure_guild(session, guild_id, f"Guild {guild_id}")
            await ensure_user(session, diagnostic_user_id, str(diagnostic_user_id), str(diagnostic_user_id))
            daily_amount, daily_streak = await claim_reward(session, guild_id, diagnostic_user_id, "daily", 250)
            weekly_amount, weekly_streak = await claim_reward(session, guild_id, diagnostic_user_id, "weekly", 1500)
            ok = daily_amount > 0 and daily_streak == 1 and weekly_amount > 0 and weekly_streak == 1
            await session.rollback()
        return DiagnosticResult("Rewards", ok, "daily e weekly testados em usuário sintético e rollback" if ok else "recompensas retornaram estado inesperado")
    except Exception as exc:
        return DiagnosticResult("Rewards", False, f"{type(exc).__name__}: {str(exc)[:220]}")


async def _reminder_smoke(guild_id: int, diagnostic_user_id: int) -> DiagnosticResult:
    try:
        async with session_factory() as session:
            due_at = utc_now() + timedelta(minutes=5)
            row = Reminder(id=secrets.randbits(62), guild_id=guild_id, user_id=diagnostic_user_id, channel_id=1, message="Diagnóstico", due_at=due_at, sent_at=None, delivery="channel")
            session.add(row)
            await session.flush()
            loaded = await session.get(Reminder, row.id)
            ok = loaded is not None and loaded.delivery == "channel" and loaded.sent_at is None and loaded.due_at == due_at
            await session.rollback()
        return DiagnosticResult("Reminders", ok, "criação, leitura e estado pendente testados em rollback" if ok else "reminder retornou estado inesperado")
    except Exception as exc:
        return DiagnosticResult("Reminders", False, f"{type(exc).__name__}: {str(exc)[:220]}")


async def _community_smoke(guild_id: int, diagnostic_user_id: int) -> DiagnosticResult:
    try:
        async with session_factory() as session:
            await ensure_guild(session, guild_id, f"Guild {guild_id}")
            poll = Poll(id=secrets.randbits(62), guild_id=guild_id, channel_id=1, question="Diagnóstico", options=["Sim", "Não", "Talvez"], ends_at=utc_now() + timedelta(minutes=5), status="active", message_id=None, created_at=utc_now(), updated_at=utc_now())
            session.add(poll)
            await session.flush()
            _, first_counts = await add_poll_vote(session, poll.id, diagnostic_user_id, 0)
            _, second_counts = await add_poll_vote(session, poll.id, diagnostic_user_id, 1)
            final_counts = await end_poll(session, poll.id)
            ended_vote_rejected = False
            try:
                await add_poll_vote(session, poll.id, diagnostic_user_id, 2)
            except ValueError:
                ended_vote_rejected = True
            suggestion = Suggestion(id=secrets.randbits(62), guild_id=guild_id, author_id=diagnostic_user_id, channel_id=1, content="Diagnóstico", status="pending", upvotes=0, downvotes=0, staff_note=None, message_id=None, created_at=utc_now(), updated_at=utc_now())
            session.add(suggestion)
            await session.flush()
            initial_up, initial_down = await cast_suggestion_vote(session, suggestion.id, diagnostic_user_id, 1)
            same_up, same_down = await cast_suggestion_vote(session, suggestion.id, diagnostic_user_id, 1)
            up, down = await cast_suggestion_vote(session, suggestion.id, diagnostic_user_id, -1)
            giveaway = Giveaway(id=secrets.randbits(62), guild_id=guild_id, channel_id=1, prize="Diagnóstico", winners=1, ends_at=utc_now() + timedelta(minutes=5), requirements={}, status="active", message_id=None, created_at=utc_now(), updated_at=utc_now())
            session.add(giveaway)
            await session.flush()
            entered = await enter_giveaway(session, giveaway.id, diagnostic_user_id)
            toggled_off = await enter_giveaway(session, giveaway.id, diagnostic_user_id)
            entered_again = await enter_giveaway(session, giveaway.id, diagnostic_user_id)
            winner_ids = await end_giveaway(session, giveaway.id)
            ticket = await create_ticket(session, guild_id, diagnostic_user_id, "diagnostic", "normal", "Diagnóstico")
            await set_ticket_status(session, ticket.id, diagnostic_user_id, "closed")
            await save_ticket_transcript(session, ticket.id, "diagnostic", diagnostic_user_id)
            ok = first_counts == [1, 0, 0] and second_counts == [0, 1, 0] and final_counts == [0, 1, 0] and ended_vote_rejected and (initial_up, initial_down) == (1, 0) and (same_up, same_down) == (1, 0) and (up, down) == (0, 1) and entered and not toggled_off and entered_again and len(winner_ids) == 1 and ticket.status == "closed" and ticket.transcript == "diagnostic"
            await session.rollback()
        return DiagnosticResult("Community", ok, "poll, troca de voto, bloqueio pós-encerramento, suggestion, giveaway e ticket testados em rollback" if ok else "estado comunitário inesperado")
    except Exception as exc:
        return DiagnosticResult("Community", False, f"{type(exc).__name__}: {str(exc)[:220]}")


async def _analytics_smoke(guild_id: int, diagnostic_user_id: int) -> DiagnosticResult:
    try:
        from app.repositories.analytics import record_message
        async with session_factory() as session:
            probe_user_id = secrets.randbits(50)
            probe_channel_id = secrets.randbits(50)
            await ensure_guild(session, guild_id, f"Guild {guild_id}")
            await ensure_user(session, probe_user_id, f"diagnostic-{probe_user_id}", f"Diagnostic {probe_user_id}", None, None, False)
            bucket = utc_now().replace(minute=0, second=0, microsecond=0)
            first_message = secrets.randbits(62)
            second_message = secrets.randbits(62)
            await record_message(session, guild_id, probe_user_id, probe_channel_id, first_message, 10, bucket)
            await record_message(session, guild_id, probe_user_id, probe_channel_id, second_message, 12, bucket)
            await session.flush()
            member_value = int(await session.scalar(text("SELECT value FROM member_activity WHERE guild_id = :guild_id AND user_id = :user_id AND bucket_start = :bucket_start AND metric = 'messages'"), {"guild_id": guild_id, "user_id": probe_user_id, "bucket_start": bucket}) or 0)
            channel_value = int(await session.scalar(text("SELECT value FROM channel_activity WHERE guild_id = :guild_id AND channel_id = :channel_id AND bucket_start = :bucket_start AND metric = 'messages'"), {"guild_id": guild_id, "channel_id": probe_channel_id, "bucket_start": bucket}) or 0)
            message_rows = int(await session.scalar(select(func.count(MessageLog.id)).where(MessageLog.guild_id == guild_id, MessageLog.id.in_([first_message, second_message]))) or 0)
            ok = member_value == 2 and channel_value == 2 and message_rows == 2
            await session.rollback()
        return DiagnosticResult("Analytics", ok, "atividade de membro, atividade de canal e message logs com upsert seguro em rollback" if ok else f"analytics inconsistente: member={member_value} channel={channel_value} logs={message_rows}")
    except Exception as exc:
        return DiagnosticResult("Analytics", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _automod_smoke(guild_id: int, user_id: int) -> DiagnosticResult:
    try:
        duplicate = RuleDefinition(1, "duplicate-test", "duplicate", "delete", True, 10, set(), set(), {})
        caps = RuleDefinition(2, "caps-test", "caps", "warn", True, 5, set(), set(), {"min_letters": 10, "ratio": 0.75})
        context = MessageContext(guild_id, 1, user_id, {4}, content="MENSAGEM REPETIDA", recent_contents=["MENSAGEM REPETIDA"])
        evaluation = evaluate_rules([duplicate, caps], context, (), (), now=datetime.now(timezone.utc))
        config_errors = validate_rule_config("spam", {"max_messages": 0, "window_seconds": 5000})
        ok = evaluation.action == "delete" and evaluation.rule is not None and evaluation.rule.rule_type == "duplicate" and len(config_errors) == 2
        return DiagnosticResult("AutoMod", ok, "motor de regras, prioridade e validação de configuração OK" if ok else "motor de regras retornou estado inesperado")
    except Exception as exc:
        return DiagnosticResult("AutoMod", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _antiraid_smoke(guild_id: int, user_id: int) -> DiagnosticResult:
    try:
        current = datetime.now(timezone.utc)
        context = JoinContext(guild_id, user_id, 60, recent_joins=[current - timedelta(seconds=1)] * 7, recent_new_accounts=[current - timedelta(seconds=1)] * 7)
        decision = calculate_risk(context, {"join_threshold": 8, "join_window_seconds": 20, "new_account_seconds": 604800, "new_account_ratio": 0.6, "risk_threshold": 70, "response_action": "alert"}, current)
        ok = decision.join_count >= 8 and decision.triggered and decision.risk_score >= 70
        return DiagnosticResult("Anti-Raid", ok, "janela, threshold e score de risco OK" if ok else "motor de risco retornou estado inesperado")
    except Exception as exc:
        return DiagnosticResult("Anti-Raid", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _runtime_regression_check() -> DiagnosticResult:
    try:
        issues: list[str] = []
        group_sources = {
            "app/discord/cogs/admin.py": "admin_group",
            "app/discord/cogs/automod.py": "automod_group",
            "app/discord/cogs/antiraid.py": "raid_group",
        }
        for relative, group_name in group_sources.items():
            source = (_project_root() / relative).read_text(encoding="utf-8")
            if f"if bot.tree.get_command({group_name}.name) is None:" not in source:
                issues.append(f"registro duplicável: {relative}")
        rewards_source = (_project_root() / "app/services/rewards.py").read_text(encoding="utf-8")
        start = rewards_source.find("    try:\n        async with session.begin_nested():", rewards_source.find("async def claim_reward"))
        end = rewards_source.find("    except IntegrityError", start) if start >= 0 else -1
        block = rewards_source[start:end] if start >= 0 and end >= 0 else ""
        if "session.add(RewardClaim(" not in block or "await session.flush()" not in block or "await add_wallet(" not in block:
            issues.append("reward claim fora do savepoint de integridade")
        return DiagnosticResult("Regressões runtime", not issues, "registro de grupos e recompensa idempotentes" if not issues else " | ".join(issues))
    except Exception as exc:
        return DiagnosticResult("Regressões runtime", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _transaction_safety_check() -> DiagnosticResult:
    try:
        expected = [
            ("app/services/levels.py", "async def add_xp", "await session.flush()"),
            ("app/services/community.py", "async def cast_suggestion_vote", "await session.flush()"),
            ("app/services/community.py", "async def enter_giveaway", "await session.flush()"),
            ("app/repositories/economy.py", "async def buy_item", "await session.flush()"),
        ]
        issues: list[str] = []
        for relative, function_signature, required in expected:
            source = (_project_root() / relative).read_text(encoding="utf-8")
            start = source.find(function_signature)
            if start < 0:
                issues.append(f"{relative}:{function_signature} ausente")
                continue
            next_def = source.find("\nasync def ", start + len(function_signature))
            block = source[start:next_def if next_def >= 0 else len(source)]
            if required not in block:
                issues.append(f"{relative}:{function_signature} sem flush")
        return DiagnosticResult("Transações", not issues, "flushes críticos presentes para autoflush desativado" if not issues else " | ".join(issues[:6]))
    except Exception as exc:
        return DiagnosticResult("Transações", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _error_handling_check() -> DiagnosticResult:
    try:
        source = (_project_root() / "app" / "discord" / "bot.py").read_text(encoding="utf-8")
        required = (
            "async def on_app_command_error",
            "CommandInvokeError",
            "MissingPermissions",
            "SQLAlchemyError",
            "interaction.response.is_done()",
            "interaction.followup.send",
            "logger.error(\"application command failure",
        )
        missing = [item for item in required if item not in source]
        return DiagnosticResult("Erros", not missing, "handler global de commands, followup, logging e erros principais presente" if not missing else f"elementos ausentes: {', '.join(missing[:6])}")
    except Exception as exc:
        return DiagnosticResult("Erros", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _model_sequence_alignment_check() -> DiagnosticResult:
    try:
        from app.models import Achievement, AutoResponse, Automation, CustomCommand, EconomyAccount, Experience, GuildPermission, Integration, Job, Marriage, Member, MemberActivity, Pet, Poll, Punishment, Quest, Reputation, ShopItem, InventoryItem, Ticket, UserAchievement, UserJob, UserQuest, Warning
        models = {
            "achievements": Achievement,
            "auto_responses": AutoResponse,
            "automations": Automation,
            "custom_commands": CustomCommand,
            "economy_accounts": EconomyAccount,
            "experiences": Experience,
            "guild_permissions": GuildPermission,
            "integrations": Integration,
            "jobs": Job,
            "marriages": Marriage,
            "members": Member,
            "pets": Pet,
            "quests": Quest,
            "reputations": Reputation,
            "shop_items": ShopItem,
            "inventory_items": InventoryItem,
            "user_achievements": UserAchievement,
            "user_jobs": UserJob,
            "user_quests": UserQuest,
            "member_activity": MemberActivity,
            "channel_activity": ChannelActivity,
            "polls": Poll,
            "punishments": Punishment,
            "tickets": Ticket,
            "warnings": Warning,
        }
        missing = [name for name, model in models.items() if model.__table__.c.id.autoincrement not in (True, "auto")]
        return DiagnosticResult("ORM IDs", not missing, "modelos SERIAL configurados para autoincremento" if not missing else f"autoincremento ausente: {', '.join(missing[:8])}")
    except Exception as exc:
        return DiagnosticResult("ORM IDs", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _dependency_check() -> DiagnosticResult:
    required = ("discord.py", "SQLAlchemy", "greenlet", "asyncpg", "redis", "FastAPI", "alembic")
    missing: list[str] = []
    versions: list[str] = []
    for package in required:
        try:
            versions.append(f"{package} {importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            missing.append(package)
    detail = ", ".join(versions)
    return DiagnosticResult("Dependências", not missing, detail if not missing else f"dependências ausentes: {', '.join(missing)}")


def _environment_files_check() -> DiagnosticResult:
    try:
        example = _project_root() / ".env.example"
        required = {"DISCORD_TOKEN", "DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "DATABASE_URL", "REDIS_URL", "APP_SECRET_KEY"}
        if not example.exists():
            return DiagnosticResult("Environment files", False, ".env.example ausente")
        entries: set[str] = set()
        unsafe: list[str] = []
        for line in example.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            entries.add(key.strip())
            literal = value.strip().strip('"').strip("'")
            normalized = literal.casefold()
            placeholders = {"", "changeme", "change-me", "your-token-here", "your-secret-here", "change-this-to-a-long-random-secret"}
            local_examples = {
                "database_url": "postgresql+asyncpg://postgres:postgres@localhost:5432/bn_bot",
                "redis_url": "redis://localhost:6379/0",
            }
            if key.strip() in required and normalized and normalized not in placeholders and normalized != local_examples.get(key.strip().casefold(), ""):
                unsafe.append(key.strip())
        missing = sorted(required - entries)
        issues = []
        if missing:
            issues.append(f"variáveis ausentes: {', '.join(missing)}")
        if unsafe:
            issues.append(f"valores reais no .env.example: {', '.join(unsafe)}")
        return DiagnosticResult("Environment files", not issues, ".env.example completo e sem secrets reais" if not issues else " | ".join(issues))
    except Exception as exc:
        return DiagnosticResult("Environment files", False, f"{type(exc).__name__}: {str(exc)[:220]}")


async def _schema_defaults_check() -> DiagnosticResult:
    try:
        async with session_factory() as session:
            rows = await session.execute(text("""
                SELECT table_name, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND column_name = 'id'
                  AND table_name = ANY(CAST(:tables AS TEXT[]))
            """), {"tables": list(SERIAL_TABLES)})
            defaults = {str(row[0]): str(row[1] or "") for row in rows.all()}
        missing = [table for table in sorted(SERIAL_TABLES) if "nextval(" not in defaults.get(table, "")]
        return DiagnosticResult("Sequence defaults", not missing, "IDs críticos apontam para nextval()" if not missing else f"defaults ausentes: {', '.join(missing[:10])}")
    except Exception as exc:
        return DiagnosticResult("Sequence defaults", False, f"{type(exc).__name__}: {str(exc)[:220]}")


async def _schema_foreign_keys_check() -> DiagnosticResult:
    expected = {
        "economy_accounts": {"guild_id", "user_id"},
        "inventory_items": {"guild_id", "shop_item_id"},
        "user_jobs": {"guild_id", "job_id"},
        "experiences": {"guild_id"},
        "poll_votes": {"poll_id"},
        "suggestion_votes": {"suggestion_id"},
        "giveaway_entries": {"giveaway_id"},
        "ticket_events": {"ticket_id"},
    }
    try:
        query = text("""
            SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
        """)
        async with session_factory() as session:
            rows = await session.execute(query)
            found: dict[str, set[str]] = {}
            for table, column in rows.all():
                found.setdefault(str(table), set()).add(str(column))
        missing = [f"{table}.{column}" for table, columns in expected.items() for column in sorted(columns - found.get(table, set()))]
        return DiagnosticResult("Foreign keys", not missing, "relações críticas protegidas por FK" if not missing else f"FKs ausentes: {', '.join(missing[:10])}")
    except Exception as exc:
        return DiagnosticResult("Foreign keys", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _command_runtime_limits_check(bot: Any) -> DiagnosticResult:
    expected = {
        "purge": {"amount": "app_commands.Range[int, 1, 1000]"},
        "remind": {"duration_minutes": "app_commands.Range[int, 1, 525600]"},
        "poll_create": {"duration_minutes": "app_commands.Range[int, 1, 525600]"},
        "giveaway_create": {"duration_minutes": "app_commands.Range[int, 1, 525600]"},
    }
    issues: list[str] = []
    root = _project_root() / "app" / "discord" / "cogs"
    functions: dict[str, ast.AsyncFunctionDef] = {}
    for path in root.glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            issues.append(f"{path.name}:{exc.lineno} SyntaxError")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                functions[node.name] = node
    for function_name, parameters in expected.items():
        node = functions.get(function_name)
        if node is None:
            issues.append(f"{function_name} ausente")
            continue
        annotations = {argument.arg: ast.unparse(argument.annotation) if argument.annotation is not None else "" for argument in node.args.args}
        for parameter_name, expected_annotation in parameters.items():
            actual = annotations.get(parameter_name, "")
            if actual.replace(" ", "") != expected_annotation.replace(" ", ""):
                issues.append(f"{function_name}:{parameter_name} limite inválido")
    command_names = {item.qualified_name for item in bot.tree.walk_commands()}
    for required_command in ("purge", "remind", "poll create", "giveaway create"):
        if required_command not in command_names:
            issues.append(f"{required_command} ausente no registro")
    return DiagnosticResult("Limites de comandos", not issues, "limites principais presentes no código e no registro slash" if not issues else " | ".join(issues[:8]))


def _component_limit_check() -> DiagnosticResult:
    try:
        issues: list[str] = []
        root = _project_root() / "app"
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for match in re.finditer(r"custom_id\s*=\s*f?[\"']([^\"']+)[\"']", source):
                if len(match.group(1)) > 100:
                    issues.append(f"{path.name}: custom_id acima de 100 caracteres")
            for match in re.finditer(r"label\s*=\s*f?[\"']([^\"']+)[\"']", source):
                if "{" not in match.group(1) and len(match.group(1)) > 80:
                    issues.append(f"{path.name}: label acima de 80 caracteres")
        return DiagnosticResult("Componentes", not issues, "custom_id e labels dentro dos limites do Discord" if not issues else " | ".join(issues[:8]))
    except Exception as exc:
        return DiagnosticResult("Componentes", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _persistent_views_check() -> DiagnosticResult:
    try:
        source = "\n".join(path.read_text(encoding="utf-8") for path in (_project_root() / "app" / "discord" / "cogs").glob("*.py"))
        required = ("class TicketView", "class SuggestionView", "class GiveawayView", "class PollView", "add_view", "registered_views")
        missing = [item for item in required if item not in source]
        return DiagnosticResult("Persistent views", not missing, "tickets, suggestions, giveaways e polls possuem views persistíveis" if not missing else f"elementos ausentes: {', '.join(missing)}")
    except Exception as exc:
        return DiagnosticResult("Persistent views", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _configuration_safety_check() -> DiagnosticResult:
    try:
        settings = get_settings()
        issues = []
        if not settings.discord_token.strip():
            issues.append("DISCORD_TOKEN vazio")
        if not settings.discord_client_id.strip() or not settings.discord_client_secret.strip():
            issues.append("credenciais OAuth2 incompletas")
        if len(settings.app_secret_key) < 32:
            issues.append("APP_SECRET_KEY curta")
        if settings.app_env == "production" and not settings.discord_redirect_uri.lower().startswith("https://"):
            issues.append("redirect URI sem HTTPS em produção")
        return DiagnosticResult("Configuração", not issues, "secrets presentes, chave de sessão adequada e OAuth2 configurado" if not issues else " | ".join(issues))
    except Exception as exc:
        return DiagnosticResult("Configuração", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _dashboard_check() -> DiagnosticResult:
    try:
        source = (_project_root() / "app" / "dashboard" / "main.py").read_text(encoding="utf-8")
        required_fragments = ("FastAPI(title=\"BN Bot Dashboard\")", "SessionMiddleware", "/auth/login", "/auth/callback", "/api/me", "/api/guilds", "oauth_state", "x-csrf-token", "dashboard_session")
        missing = [fragment for fragment in required_fragments if fragment not in source]
        return DiagnosticResult("Dashboard", not missing, "FastAPI, sessão, OAuth2, CSRF e APIs principais presentes" if not missing else f"elementos ausentes: {', '.join(missing)}")
    except Exception as exc:
        return DiagnosticResult("Dashboard", False, f"{type(exc).__name__}: {str(exc)[:220]}")


def _workers_check(bot: Any) -> DiagnosticResult:
    worker = getattr(bot, "worker", None)
    if worker is None:
        return DiagnosticResult("Workers", False, "worker não está inicializado")
    worker_names = ("reminders", "temporary_roles", "antiraid", "community")
    stopped = [name for name in worker_names if getattr(getattr(worker, name, None), "is_running", lambda: False)() is False]
    failed = [name for name in worker_names if getattr(getattr(worker, name, None), "failed", lambda: False)()]
    if stopped or failed:
        detail = []
        if stopped:
            detail.append(f"parados: {', '.join(stopped)}")
        if failed:
            detail.append(f"falhos: {', '.join(failed)}")
        return DiagnosticResult("Workers", False, " | ".join(detail))
    return DiagnosticResult("Workers", True, "todos os workers estão ativos e sem estado de falha")



def _command_option_signature(options: list[dict[str, Any]] | None) -> tuple:
    result = []
    for option in options or []:
        result.append((
            str(option.get("name", "")),
            _enum_int(option.get("type", 0)),
            bool(option.get("required", False)),
            _command_option_signature(option.get("options")),
        ))
    return tuple(result)


def _local_command_signature(command: Any, tree: Any) -> tuple:
    data = command.to_dict(tree)
    return (str(command.qualified_name), int(data.get("type", 0)), _command_option_signature(data.get("options")))


def _remote_option_signature(options: list[dict[str, Any]] | None) -> tuple:
    return tuple(
        (
            str(option.get("name", "")),
            _enum_int(option.get("type", 0)),
            bool(option.get("required", False)),
            _remote_option_signature(option.get("options")),
        )
        for option in (options or [])
    )


def _remote_command_signatures(commands: list[Any]) -> dict[str, tuple]:
    result: dict[str, tuple] = {}

    def walk_options(options: list[dict[str, Any]] | None, prefix: str) -> None:
        for option in options or []:
            option_type = _enum_int(option.get("type", 0))
            option_name = str(option.get("name", ""))
            qualified = f"{prefix} {option_name}".strip()
            nested = option.get("options") or []
            if option_type == 2:
                walk_options(nested, qualified)
            elif option_type == 1:
                result[qualified] = ("1", option_name, _remote_option_signature(nested))

    for command in commands:
        data = command.to_dict()
        top_name = str(data.get("name", ""))
        top_type = _enum_int(data.get("type", 0))
        options = data.get("options") or []
        if top_type == 2:
            walk_options(options, top_name)
        elif top_type == 1:
            result[top_name] = ("1", top_name, _remote_option_signature(options))
        else:
            result[top_name] = (str(top_type), top_name, ())
    return result


async def _remote_command_sync_check(bot: Any, guild_id: int) -> DiagnosticResult:
    try:
        import discord
        guild_object = discord.Object(id=guild_id)
        guild_remote = await bot.tree.fetch_commands(guild=guild_object)
        global_remote = await bot.tree.fetch_commands()
        local = {command.qualified_name: _local_command_signature(command, bot.tree) for command in bot.tree.walk_commands() if not getattr(command, "commands", None)}
        settings = get_settings()
        primary = global_remote if settings.app_env == "production" else guild_remote
        secondary = guild_remote if settings.app_env == "production" else global_remote
        primary_signatures = _remote_command_signatures(primary)
        duplicate_primary = sorted({str(getattr(command, "name", "")) for command in primary if sum(1 for candidate in primary if getattr(candidate, "name", "") == getattr(command, "name", "")) > 1})
        duplicate_secondary = sorted({str(getattr(command, "name", "")) for command in secondary if sum(1 for candidate in secondary if getattr(candidate, "name", "") == getattr(command, "name", "")) > 1})
        missing = sorted(set(local) - set(primary_signatures))
        stale = []
        for name in sorted(set(local) & set(primary_signatures)):
            local_data = local[name]
            remote_data = primary_signatures[name]
            local_options = local_data[2]
            remote_options = remote_data[2] if len(remote_data) > 2 else ()
            if local_options != remote_options:
                stale.append(name)
        scope_issues = []
        if duplicate_primary:
            scope_issues.append(f"duplicados no escopo principal: {', '.join(duplicate_primary[:6])}")
        if duplicate_secondary:
            scope_issues.append(f"duplicados no escopo secundário: {', '.join(duplicate_secondary[:6])}")
        if secondary:
            label = "comandos de guilda antigos" if settings.app_env == "production" else "comandos globais antigos"
            scope_issues.append(f"{label}: {len(secondary)}")
        if missing or stale or scope_issues:
            detail = []
            if missing:
                detail.append(f"ausentes no Discord: {', '.join(missing[:6])}")
            if stale:
                detail.append(f"assinatura desatualizada: {', '.join(stale[:6])}")
            detail.extend(scope_issues)
            return DiagnosticResult("Discord commands", False, " | ".join(detail))
        expected_scope = "globais" if settings.app_env == "production" else "da guild"
        return DiagnosticResult("Discord commands", True, f"{len(primary_signatures)} comandos executáveis {expected_scope} sincronizados com a árvore local; escopo secundário vazio")
    except Exception as exc:
        return DiagnosticResult("Discord commands", False, f"{type(exc).__name__}: {str(exc)[:220]}")

async def run_diagnostics(bot: Any, guild_id: int, user_id: int, channel_id: int | None = None) -> list[DiagnosticResult]:
    results: list[DiagnosticResult] = [
        _python_runtime_check(),
        _command_check(bot),
        _command_matrix_check(),
        *_command_matrix_details(),
        _command_serialization_check(bot),
        _command_id_input_check(),
        _command_decorator_check(),
        _interaction_safety_check(),
        _command_source_safety_check(),
        _component_error_handling_check(),
        _message_logging_check(),
        _response_contract_check(),
        _admin_command_layout_check(bot),
        _poll_validation_smoke(),
        _security_surface_check(),
        _code_hygiene_check(),
        _transaction_safety_check(),
        _error_handling_check(),
        _model_sequence_alignment_check(),
        _dependency_check(),
        _environment_files_check(),
        _persistent_views_check(),
        _configuration_safety_check(),
        _command_runtime_limits_check(bot),
        _component_limit_check(),
    ]
    try:
        engine = get_engine()
        driver = engine.sync_engine.dialect.driver
        results.append(DiagnosticResult("Driver PostgreSQL", driver == "asyncpg", f"driver da aplicação: {driver}"))
    except Exception as exc:
        results.append(DiagnosticResult("Driver PostgreSQL", False, f"{type(exc).__name__}: {str(exc)[:220]}"))
    await _database_checks(results)
    results.append(await _schema_defaults_check())
    results.append(await _schema_foreign_keys_check())
    await _redis_checks(results, guild_id)
    try:
        async with session_factory() as session:
            settings = await session.get(GuildSettings, guild_id)
        results.append(DiagnosticResult("Configuração da guild", settings is not None, "configuração encontrada" if settings else "guild ainda não inicializada"))
    except Exception as exc:
        results.append(DiagnosticResult("Configuração da guild", False, f"{type(exc).__name__}: {str(exc)[:220]}"))
    results.append(await _remote_command_sync_check(bot, guild_id))

    diagnostic_user_id = -(secrets.randbelow(2_000_000_000_000_000_000) + 1)
    results.append(await _economy_smoke(guild_id, diagnostic_user_id))
    results.append(await _progression_smoke(guild_id, diagnostic_user_id))
    results.append(await _rewards_smoke(guild_id, diagnostic_user_id))
    results.append(await _reminder_smoke(guild_id, diagnostic_user_id))
    results.append(await _analytics_smoke(guild_id, diagnostic_user_id))
    results.append(await _community_smoke(guild_id, diagnostic_user_id))
    results.append(_runtime_regression_check())
    results.append(_automod_smoke(guild_id, diagnostic_user_id))
    results.append(_antiraid_smoke(guild_id, diagnostic_user_id))
    results.append(_dashboard_check())
    results.append(_workers_check(bot))

    guild = bot.get_guild(guild_id)
    if guild is None or guild.me is None:
        results.append(DiagnosticResult("Permissões", False, "BN Bot não está disponível na guild"))
    else:
        permissions = guild.me.guild_permissions
        core_permissions = {"view_channel": permissions.view_channel, "send_messages": permissions.send_messages, "read_message_history": permissions.read_message_history}
        feature_permissions = {"manage_messages": permissions.manage_messages, "manage_channels": permissions.manage_channels, "manage_roles": permissions.manage_roles, "moderate_members": permissions.moderate_members, "kick_members": permissions.kick_members, "ban_members": permissions.ban_members, "manage_guild": permissions.manage_guild}
        missing_core = [name for name, enabled in core_permissions.items() if not enabled]
        missing_features = [name for name, enabled in feature_permissions.items() if not enabled]
        channel = guild.get_channel(channel_id) if channel_id else None
        channel_issue = []
        if channel is not None:
            channel_permissions = channel.permissions_for(guild.me)
            channel_issue = [name for name in ("view_channel", "send_messages", "read_message_history") if not getattr(channel_permissions, name)]
        if missing_core or channel_issue:
            details = []
            if missing_core:
                details.append(f"servidor: {', '.join(missing_core)}")
            if channel_issue:
                details.append(f"canal: {', '.join(channel_issue)}")
            results.append(DiagnosticResult("Permissões", False, " | ".join(details)))
        else:
            detail = "permissões core presentes"
            if missing_features:
                detail += f" | recursos administrativos indisponíveis sem: {', '.join(missing_features)}"
            else:
                detail += " | permissões dos recursos principais presentes"
            results.append(DiagnosticResult("Permissões", True, detail))

    if bot.user:
        latency = bot.latency
        ready = bot.is_ready()
        results.append(DiagnosticResult("Gateway Discord", ready, f"online em {len(bot.guilds)} servidor(es) | latência {round(latency * 1000)} ms" if ready else "gateway não está pronto"))
    else:
        results.append(DiagnosticResult("Gateway Discord", False, "usuário do bot indisponível"))

    return results
