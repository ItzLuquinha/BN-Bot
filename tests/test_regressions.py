from pathlib import Path
from types import SimpleNamespace

from app.core import db
from app.models import ChannelActivity, EconomyAccount, Experience, InventoryItem, Reputation, UserJob


def test_runtime_database_url_is_normalized_to_asyncpg(monkeypatch) -> None:
    monkeypatch.setattr(db, "get_settings", lambda: SimpleNamespace(database_url="postgresql://user:password@host:5432/db"))
    assert db.async_database_url().drivername == "postgresql+asyncpg"


def test_serial_entities_do_not_request_manual_bigint_ids() -> None:
    source = Path("app/repositories/economy.py").read_text(encoding="utf-8")
    assert "InventoryItem(id=tx_id()" not in source
    assert EconomyAccount.__table__.c.id.autoincrement in (True, "auto")
    assert Experience.__table__.c.id.autoincrement in (True, "auto")
    assert Reputation.__table__.c.id.autoincrement in (True, "auto")
    assert UserJob.__table__.c.id.autoincrement in (True, "auto")
    assert InventoryItem.__table__.c.id.autoincrement in (True, "auto")


def test_new_experience_row_initializes_python_defaults() -> None:
    source = Path("app/services/levels.py").read_text(encoding="utf-8")
    assert "total_xp=0, level=0, rewarded_level=0" in source


def test_buy_item_flushes_new_inventory_before_follow_up_queries() -> None:
    source = Path("app/repositories/economy.py").read_text(encoding="utf-8")
    block_start = source.index("if inv is None:")
    block_end = source.index("if inv.quantity + quantity", block_start)
    assert "await session.flush()" in source[block_start:block_end]


def test_purge_always_passes_callable_check() -> None:
    source = Path("app/discord/cogs/moderation.py").read_text(encoding="utf-8")
    assert "check = lambda message: user is None or message.author.id == user.id" in source
    assert "check = None if user is None" not in source


def test_poll_create_exposes_two_required_options() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    assert "option1: str" in source
    assert "option2: str" in source
    assert "options: str" not in source
    assert 'option1="Opção 1, obrigatória"' in source
    assert 'option2="Opção 2, obrigatória"' in source


def test_poll_create_supports_optional_options_three_to_ten() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    for index in range(3, 11):
        assert f"option{index}: str | None = None" in source


def test_testall_checks_actual_economy_result() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "expected_wallet = 40" in source
    assert "expected_bank = 30" in source
    assert "inventory_quantity == 1" in source
    assert "loaded_item.stock == 3" in source


def test_testall_includes_interaction_safety_and_poll_validation() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "_interaction_safety_check()" in source
    assert "_poll_validation_smoke()" in source
    assert "_security_surface_check()" in source
    assert "_code_hygiene_check()" in source


def test_command_handlers_defer_before_io() -> None:
    import ast

    root = Path("app/discord/cogs")
    issues = []
    io_names = {"ban", "create_role", "create_text_channel", "edit", "execute", "fetch_channel", "fetch_message", "history", "kick", "purge", "scalar", "send", "set_permissions", "timeout", "unban"}
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            decorators = [ast.unparse(value) for value in node.decorator_list]
            if not any(value.endswith(".command") or ".command(" in value or value.startswith("app_commands.command") for value in decorators):
                continue
            calls = sorted((value for value in ast.walk(node) if isinstance(value, ast.Call)), key=lambda value: value.lineno)
            defer_lines = [value.lineno for value in calls if ast.unparse(value.func) in {"defer", "interaction.response.defer"}]
            first_defer = min(defer_lines) if defer_lines else None
            for call in calls:
                name = ast.unparse(call.func)
                final = name.rsplit(".", 1)[-1]
                io = name == "session_factory" or name.startswith("redis_client.") or name.endswith("check_and_set") or (name.startswith("session.") and final in {"execute", "get", "scalar", "flush", "commit", "rollback", "delete"}) or (not name.startswith("interaction.response.") and not name.startswith("interaction.followup.") and final in io_names)
                if io and (first_defer is None or call.lineno < first_defer):
                    issues.append(f"{path.name}:{node.name}:{call.lineno}")
                if name == "interaction.response.send_message" and first_defer is not None and call.lineno > first_defer:
                    issues.append(f"{path.name}:{node.name}:{call.lineno}:response")
    assert issues == []


def test_requirements_include_greenlet_for_sqlalchemy_asyncio() -> None:
    root = Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (root / "requirements.txt").read_text(encoding="utf-8")
    assert '"greenlet>=3.1,<4"' in pyproject
    assert "greenlet>=3.1,<4" in requirements


def test_windows_setup_uses_project_python() -> None:
    root = Path(__file__).parents[1]
    setup = (root / "docs" / "SETUP_WINDOWS.md").read_text(encoding="utf-8")
    assert r'`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`' in setup


def test_suggestion_vote_flushes_for_same_transaction_reads() -> None:
    source = Path("app/services/community.py").read_text(encoding="utf-8")
    start = source.index("async def cast_suggestion_vote")
    end = source.index("async def update_suggestion", start)
    block = source[start:end]
    assert "await session.flush()" in block


def test_giveaway_toggle_flushes_new_entry() -> None:
    source = Path("app/services/community.py").read_text(encoding="utf-8")
    start = source.index("async def enter_giveaway")
    end = source.index("async def end_giveaway", start)
    block = source[start:end]
    assert "await session.flush()" in block


def test_xp_flushes_after_progression_update() -> None:
    source = Path("app/services/levels.py").read_text(encoding="utf-8")
    assert "row.updated_at = now\n    await session.flush()" in source


def test_sequences_diagnostics_targets_sequence_backed_tables() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    start = source.index("SERIAL_TABLES = {")
    end = source.index("\n}\nREQUIRED_COMMANDS", start) + 2
    block = source[start:end]
    for table in ("member_activity", "polls", "punishments", "tickets", "warnings"):
        assert f'"{table}"' in block


def test_security_scan_does_not_search_for_its_own_source_pattern() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "DISCORD_TOKEN = \"" not in source
    assert "ast.parse(path.read_text(encoding=\"utf-8\"))" in source


def test_interaction_scanner_does_not_classify_dict_get_as_io() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert '    "get",\n' not in source
    assert '"get_guild_settings"' in source


def test_testall_includes_transaction_error_and_orm_checks() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "_transaction_safety_check()" in source
    assert "_error_handling_check()" in source
    assert "_model_sequence_alignment_check()" in source
    transaction_source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "async def cast_suggestion_vote" in transaction_source
    assert "async def enter_giveaway" in transaction_source


def test_main_rejects_global_python_when_project_venv_exists() -> None:
    source = Path("main.py").read_text(encoding="utf-8")
    assert 'project_venv = Path(__file__).resolve().parent / ".venv"' in source
    assert "project_venv.resolve() not in executable.parents" in source


def test_doctor_rejects_wrong_interpreter() -> None:
    source = Path("scripts/doctor.py").read_text(encoding="utf-8")
    assert 'expected_venv = Path(__file__).resolve().parents[1] / ".venv"' in source
    assert "raise SystemExit(1)" in source


def test_community_entity_models_use_autoincrement() -> None:
    from app.models import MemberActivity, Poll, Punishment, Ticket, Warning

    models = (MemberActivity, Poll, Punishment, Ticket, Warning)
    assert all(model.__table__.c.id.autoincrement in (True, "auto") for model in models)


def test_sequence_migration_exists() -> None:
    migration = Path("alembic/versions/0006_autoincrement_ids.py").read_text(encoding="utf-8")
    assert 'TABLES = ("member_activity", "polls", "punishments", "tickets", "warnings")' in migration
    assert 'CREATE SEQUENCE IF NOT EXISTS public.{sequence} AS BIGINT' in migration
    assert 'SET DEFAULT nextval' in migration
    assert 'ALTER SEQUENCE public.{sequence} OWNED BY' in migration


def test_analytics_diagnostic_is_registered() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "async def _analytics_smoke" in source
    assert "results.append(await _analytics_smoke" in source


def test_alembic_can_import_project_from_source_tree() -> None:
    config = Path("alembic.ini").read_text(encoding="utf-8")
    env = Path("alembic/env.py").read_text(encoding="utf-8")
    assert "prepend_sys_path = ." in config
    assert "PROJECT_ROOT = Path(__file__).resolve().parents[1]" in env
    assert "sys.path.insert(0, str(PROJECT_ROOT))" in env


def test_windows_setup_uses_current_python_for_alembic() -> None:
    root = Path(__file__).parents[1]
    setup = (root / "docs" / "SETUP_WINDOWS.md").read_text(encoding="utf-8")
    assert r"`.\.venv\Scripts\python.exe -m alembic upgrade head`" in setup


def test_channel_activity_uses_autoincrement() -> None:
    assert ChannelActivity.__table__.c.id.autoincrement in (True, "auto")


def test_channel_activity_sequence_migration_exists() -> None:
    migration = Path("alembic/versions/0007_channel_activity_sequence.py").read_text(encoding="utf-8")
    assert 'revision = "0007_channel_activity_sequence"' in migration
    assert "channel_activity_id_seq" in migration
    assert "SET DEFAULT nextval" in migration


def test_testall_includes_remote_command_sync() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "async def _remote_command_sync_check" in source
    assert "results.append(await _remote_command_sync_check(bot, guild_id))" in source

def test_development_command_sync_is_guild_scoped() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert "self.tree.copy_global_to(guild=guild_object)" in source
    assert "await self.tree.sync(guild=guild_object)" in source

def test_discord_guild_id_is_configurable() -> None:
    source = Path("app/config.py").read_text(encoding="utf-8")
    assert "discord_guild_id: int | None = None" in source


def test_remote_command_sync_ignores_group_nodes() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert 'if not hasattr(command, "commands")' in source

def test_channel_activity_is_in_sequence_alignment() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert '"channel_activity": ChannelActivity' in source
    serial_start = source.index("SERIAL_TABLES = {")
    assert '"channel_activity"' in source[serial_start:]


def test_admin_audit_has_logger() -> None:
    source = Path("app/discord/cogs/admin.py").read_text(encoding="utf-8")
    assert 'import logging' in source
    assert 'logger = logging.getLogger("bn_bot.discord.admin")' in source


def test_diagnostics_imports_channel_activity() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "ChannelActivity" in source.split("from app.models import ", 1)[1].split("\n", 1)[0]


def test_ticket_reopen_repairs_missing_or_deleted_panel() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    start = source.index('async def ticket_reopen_command')
    end = source.index('async def ticket_claim_command', start)
    block = source[start:end]
    assert 'except discord.NotFound:' in block
    assert 'ticket_row.panel_message_id = message.id' in block


def test_giveaway_enter_rejects_expired_giveaway() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    start = source.index('async def giveaway_enter')
    end = source.index('async def finish_giveaway', start)
    block = source[start:end]
    assert 'giveaway.ends_at <= utc_now()' in block
    assert 'Este sorteio já foi encerrado.' in block


def test_testall_audit_failure_is_best_effort() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    start = source.index('async def testall')
    block = source[start:]
    assert 'testall audit persistence failed' in block
    assert 'except Exception:' in block


def test_interaction_scan_catches_response_edit_and_duplicate_defer() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert 'interaction.response.edit_message' in source
    assert 'múltiplos defer' in source


def test_utility_imports_all_visual_helpers_it_uses() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert 'status_line' in source.split('from app.discord.theme import ', 1)[1].split('\n', 1)[0]
    assert 'bar' in source.split('from app.discord.theme import ', 1)[1].split('\n', 1)[0]


def test_command_source_safety_diagnostic_is_registered() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "def _command_source_safety_check" in source
    assert "_command_source_safety_check()," in source


def test_float_command_ranges_use_float_bounds() -> None:
    economy = Path("app/discord/cogs/economy.py").read_text(encoding="utf-8")
    admin = Path("app/discord/cogs/admin.py").read_text(encoding="utf-8")
    assert "MAX_TRANSACTION = 1_000_000_000.0" in economy
    assert "MAX_ADMIN_AMOUNT = 1_000_000_000.0" in admin
    assert "Range[float, 0.01, MAX_TRANSACTION]" in economy
    assert "Range[float, 0.01, MAX_ADMIN_AMOUNT]" in admin


def test_command_import_preflight_covers_all_cogs() -> None:
    main = Path("main.py").read_text(encoding="utf-8")
    doctor = Path("scripts/doctor.py").read_text(encoding="utf-8")
    for module_name in (
        "app.discord.cogs.utility",
        "app.discord.cogs.economy",
        "app.discord.cogs.progression",
        "app.discord.cogs.moderation",
        "app.discord.cogs.community",
        "app.discord.cogs.automod",
        "app.discord.cogs.admin",
        "app.discord.cogs.antiraid",
    ):
        assert module_name in main
        assert module_name in doctor


def test_all_float_range_constants_are_float_typed() -> None:
    import ast

    for relative_path, constant_name in (
        ("app/discord/cogs/economy.py", "MAX_TRANSACTION"),
        ("app/discord/cogs/admin.py", "MAX_ADMIN_AMOUNT"),
    ):
        tree = ast.parse(Path(relative_path).read_text(encoding="utf-8"))
        assignments = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == constant_name for target in node.targets)
        ]
        assert assignments
        assert isinstance(assignments[0].value, ast.Constant)
        assert type(assignments[0].value.value) is float


def test_doctor_checks_command_definitions_before_runtime() -> None:
    source = Path("scripts/doctor.py").read_text(encoding="utf-8")
    assert "Command definitions: OK" in source
    assert "Command definitions: ERRO" in source


def test_script_entrypoints_bootstrap_project_root() -> None:
    doctor = Path("scripts/doctor.py").read_text(encoding="utf-8")
    seed = Path("scripts/seed.py").read_text(encoding="utf-8")
    for source in (doctor, seed):
        assert "PROJECT_ROOT = Path(__file__).resolve().parents[1]" in source
        assert "sys.path.insert(0, str(PROJECT_ROOT))" in source


def test_doctor_can_load_commands_when_invoked_as_script() -> None:
    source = Path("scripts/doctor.py").read_text(encoding="utf-8")
    root_bootstrap = source.index("PROJECT_ROOT =")
    import_block = source.index("command_modules =")
    assert root_bootstrap < import_block


def test_message_log_persists_message_id() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "repositories" / "analytics.py").read_text(encoding="utf-8")
    assert "MessageLog(id=message_id" in source
    assert "message_id=message_id" in source


def test_admin_credit_is_nested_under_admin_group() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "discord" / "cogs" / "admin.py").read_text(encoding="utf-8")
    assert '@admin_group.command(name="credit"' in source
    assert '@app_commands.command(name="credit"' not in source


def test_persistent_component_views_define_error_handler() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "discord" / "cogs" / "community.py").read_text(encoding="utf-8")
    assert "class BNComponentView" in source
    assert "async def on_error" in source
    assert "class PollView(BNComponentView)" in source


def test_help_select_does_not_send_unverified_emoji_names() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "discord" / "cogs" / "utility.py").read_text(encoding="utf-8")
    assert 'emoji="◆"' not in source
    assert 'emoji="◇"' not in source


def test_tree_error_handler_is_installed() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "discord" / "bot.py").read_text(encoding="utf-8")
    assert "self.tree.on_error = self.on_app_command_error" in source


def test_message_logging_call_supplies_message_id() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "repositories" / "analytics.py").read_text(encoding="utf-8")
    assert "message_id=message_id" in source
