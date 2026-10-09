from pathlib import Path


def test_sell_item_restocks_finite_shop_inventory() -> None:
    source = Path("app/repositories/economy.py").read_text(encoding="utf-8")
    start = source.index("async def sell_item")
    end = source.index("return value", start) + len("return value")
    block = source[start:end]
    assert "if item.stock is not None:" in block
    assert "item.stock += quantity" in block


def test_dashboard_component_budget_stays_below_discord_limit() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert "per_page = 10" in source
    assert "row=1 + index // 5" in source
    assert "nav_row = 3" in source


def test_dashboard_command_buttons_use_unique_runtime_ids() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert "bn:dashboard:{owner_id}:run:" in source
    assert "secrets.token_hex(6)" in source


def test_reward_cooldown_uses_next_calendar_boundary() -> None:
    from datetime import datetime
    source = Path("app/services/rewards.py").read_text(encoding="utf-8")
    assert "def seconds_until_next_reward" in source
    assert "datetime.combine(next_date, time.min, tzinfo=local.tzinfo)" in source


def test_dashboard_optional_text_inputs_use_none_for_missing_defaults() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert 'return None' in source
    assert 'return discord.utils.MISSING' not in source


def test_dashboard_command_modes_are_explicit_and_textual() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert 'def command_mode' in source
    assert 'return "confirm", "Confirmação"' in source
    assert 'return "form", "Formulário"' in source
    assert 'return "direct", "Direto"' in source


def test_dashboard_category_buttons_do_not_use_decorative_symbols() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert 'button_emoji' not in source
    assert 'COMMAND_MODE_ICONS' not in source


def test_dashboard_home_distributes_categories_across_valid_rows() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert 'for index, (category, info) in enumerate(CATEGORY_INFO.items()):' in source
    assert 'row = 0 if index < 5 else 1' in source
    assert 'row=row' in source


def test_every_expected_command_has_a_passing_individual_behavior_contract() -> None:
    from app.services.command_matrix import EXPECTED_COMMANDS, audit_commands, case_issues
    cases = {case.qualified_name: case for case in audit_commands()}
    assert set(cases) == EXPECTED_COMMANDS
    assert len(cases) == len(EXPECTED_COMMANDS)
    failures = {name: case_issues(case) for name, case in cases.items() if case_issues(case)}
    assert failures == {}


def test_dashboard_initial_response_does_not_fetch_ephemeral_original() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    block = source[source.index("async def dashboard"):source.index("def commands_by_category", source.index("async def dashboard"))]
    assert "await interaction.response.send_message" in block
    assert "await interaction.original_response()" not in block
    assert "allowed_mentions=discord.AllowedMentions.none()" in block


def test_dashboard_views_reuse_existing_interaction_message_instead_of_fetching_it() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert "view.message = interaction.message" in source
    assert source.count("await interaction.original_response()") == 0


def test_dashboard_keeps_a_safe_fallback_when_discord_rejects_the_initial_payload() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    block = source[source.index("async def dashboard"):source.index("def commands_by_category", source.index("async def dashboard"))]
    assert "except discord.HTTPException as exc:" in block
    assert 'getattr(exc, "status", None)' in block
    assert '"O painel não pôde ser aberto. Tente novamente."' in block


def test_dashboard_ephemeral_component_edits_use_edit_original_response() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert "await interaction.edit_original_response(view=self)" in source
    assert "await interaction.message.edit(view=self)" not in source
    assert "await interaction.message.edit(view=None)" not in source


def test_dashboard_error_handler_covers_expected_check_failures() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    required = (
        "RateLimitExceeded",
        "CommandOnCooldown",
        "BotMissingPermissions",
        "MissingRole",
        "MissingAnyRole",
        "CheckFailure",
    )
    assert all(item in source for item in required)
