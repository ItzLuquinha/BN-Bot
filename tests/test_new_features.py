from pathlib import Path


def test_testall_has_direct_error_button():
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert "class TestallErrorsView" in source
    assert "self.errors_button.label" in source
    assert "Ver erros (" in source
    assert "ephemeral=True" in source


def test_tutorial_admin_uses_stable_thumbnail():
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert 'if value == "administracao":' in source
    assert "page.remove_image()" in source
    assert "page.set_thumbnail" in source


def test_dice_uses_user_selected_gif():
    source = Path("app/discord/theme.py").read_text(encoding="utf-8")
    assert "I38qmkMXsMOFKsuer9" in source


def test_praise_message_is_the_requested_phrase():
    source = Path("app/discord/cogs/fun.py").read_text(encoding="utf-8")
    assert "Obrigado por existirem." in source


def test_database_migrations_run_before_bot_start():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "upgrade_to_head" in source
    assert "await asyncio.to_thread(upgrade_to_head)" in source


def test_group_registration_is_idempotent():
    for path, group in [
        ("app/discord/cogs/admin.py", "admin_group"),
        ("app/discord/cogs/automod.py", "automod_group"),
        ("app/discord/cogs/antiraid.py", "raid_group"),
    ]:
        source = Path(path).read_text(encoding="utf-8")
        assert f"if bot.tree.get_command({group}.name) is None:" in source


def test_praise_notifies_only_vix() -> None:
    source = Path("app/discord/cogs/fun.py").read_text(encoding="utf-8")
    block = source[source.index('@app_commands.command(name="praise"'):source.index('@app_commands.command(name="eightball"')]
    assert "users=[members[1]]" in block
    assert "roles=False" in block
    assert "everyone=False" in block
    assert "content=mentions" in block


def test_tutorial_uses_the_central_permission_map() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    permissions = Path("app/services/permissions.py").read_text(encoding="utf-8")
    assert "required_permission_text" in source
    assert "COMMAND_PERMISSIONS" in permissions
    assert "`/admin ...` · Gerenciar Servidor" in source
    assert "`/automod ...` e `/antiraid ...` · Gerenciar Servidor" in source


def test_bump_legacy_source_is_gone():
    assert not Path("app/discord/cogs/bump.py").exists()
    assert not Path("app/services/bump.py").exists()


def test_voice_tracking_handles_voice_and_stage_channels():
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert "guild.voice_channels" in source
    assert "stage_channels" in source
    assert "on_voice_state_update" in source
    assert "voice_joined_at" in source


def test_economy_commands_use_shop_metadata_and_pagination():
    source = Path("app/discord/cogs/economy.py").read_text(encoding="utf-8")
    repository = Path("app/repositories/economy.py").read_text(encoding="utf-8")
    assert "available_from" in source
    assert "available_until" in source
    assert "cooldown_seconds" in source
    assert "stack_limit" in source
    assert "PaginatedEmbedView" in source
    assert "get_shop_item" in repository
    assert "insufficient stock" in repository


def test_jobs_do_not_reference_a_nonexistent_active_column():
    source = Path("app/discord/cogs/economy.py").read_text(encoding="utf-8")
    assert "UserJob.active" not in source


def test_ticket_permissions_are_consistent_with_staff_gate():
    permissions = Path("app/services/permissions.py").read_text(encoding="utf-8")
    community = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    assert '"ticket-close": "staff_role"' in permissions
    assert 'not await is_staff(guild, member)' in community


def test_transactions_and_rewards_are_exposed():
    economy = Path("app/discord/cogs/economy.py").read_text(encoding="utf-8")
    admin = Path("app/discord/cogs/admin.py").read_text(encoding="utf-8")
    matrix = Path("app/services/command_matrix.py").read_text(encoding="utf-8")
    assert '@app_commands.command(name="transactions"' in economy
    assert '@admin_group.command(name="rewards"' in admin
    assert '"transactions"' in matrix
    assert '"admin rewards"' in matrix


def test_suggestion_and_report_workflows_validate_transitions():
    source = Path("app/services/community.py").read_text(encoding="utf-8")
    assert "suggestion cannot move" in source
    assert "report cannot move" in source
    assert "this status requires a staff note" in source
    assert "this status requires a resolution note" in source


def test_dashboard_executor_validates_checks_and_records_failures():
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert 'for check in list(getattr(node, "checks", ()) or ())' in source
    assert "record_command_usage" in source
    assert "error_type = type(exc).__name__" in source


def test_testall_reports_critical_and_attention_levels():
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert "diagnostic_severity" in source
    assert "CRÍTICO" in source
    assert "ATENÇÃO" in source
    assert "Críticos:" in source


def test_user_installable_commands_are_excluded_from_guild_sync() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert 'guild_commands = [command for command in global_commands if not self._is_user_installable(command)]' in source
    assert 'self.tree.copy_global_to(guild=guild_object)' not in source
    assert 'self.tree.add_command(command, guild=guild_object)' in source
    assert 'user_installable_excluded=' in source

def test_diagnostics_flags_global_and_guild_command_overlap() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert 'overlap = sorted(set(primary_signatures) & set(global_signatures))' in source
    assert 'mesmo comando em guilda e global' in source

    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert 'guild_commands = [command for command in global_commands if not self._is_user_installable(command)]' in source
    assert 'for command in guild_commands:' in source
    assert 'user_installable_excluded=' in source

def test_donate_command_uses_the_requested_paypal_account() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    matrix = Path("app/services/command_matrix.py").read_text(encoding="utf-8")
    analytics = Path("app/repositories/analytics.py").read_text(encoding="utf-8")
    assert '@app_commands.command(name="donate"' in source
    assert 'url="https://paypal.me/RianBraga"' in source
    assert "@RianBraga" in source
    assert '"donate"' in matrix
    assert '"donate"' in analytics

def test_twarn_uses_the_requested_gif() -> None:
    source = Path("app/discord/theme.py").read_text(encoding="utf-8")
    assert '"timed_warning": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExcW9wbTlsdTNwOWh0dzh0aXB2ODAzNnFlOTZic2ZlNW83b2p0b2J6NiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/ioa0Au2SQOO9LKv9Fz/giphy.gif"' in source
