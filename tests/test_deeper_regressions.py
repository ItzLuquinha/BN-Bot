from pathlib import Path

from app.services.antiraid import clamp_quarantine_timeout_seconds


def test_temporary_role_worker_keeps_record_on_transient_discord_errors() -> None:
    source = Path("app/tasks/worker.py").read_text(encoding="utf-8")
    block = source[source.index("async def temporary_roles"):source.index("@temporary_roles.before_loop")]
    assert "except discord.HTTPException:" in block
    assert "continue" in block
    assert "delete_record = False" in block
    assert "cleanup deferred" in block


def test_antiraid_quarantine_timeout_is_safe_for_corrupt_config() -> None:
    assert clamp_quarantine_timeout_seconds(None) == 900
    assert clamp_quarantine_timeout_seconds("bad") == 900
    assert clamp_quarantine_timeout_seconds(-5) == 60
    assert clamp_quarantine_timeout_seconds(2_419_201) == 2_419_200
    assert clamp_quarantine_timeout_seconds(600) == 600


def test_command_sync_is_serialized() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert "self._command_sync_lock = asyncio.Lock()" in source
    ready = source[source.index("async def on_ready"):source.index("async def close", source.index("async def on_ready"))]
    join = source[source.index("async def on_guild_join"):source.index("async def on_guild_remove", source.index("async def on_guild_join"))]
    assert "async with self._command_sync_lock:" in ready
    assert "async with self._command_sync_lock:" in join


def test_poll_completion_does_not_count_twice() -> None:
    source = Path("app/services/community.py").read_text(encoding="utf-8")
    block = source[source.index("async def end_poll"):source.index("async def open_items", source.index("async def end_poll"))]
    assert block.count("counts = await poll_counts") == 1


def test_custom_permissions_are_deterministic_and_user_rules_override_roles() -> None:
    source = Path("app/services/permissions.py").read_text(encoding="utf-8")
    assert ".order_by(" in source
    assert "GuildPermission.id.desc()" in source
    assert "if user_rules:" in source
    assert "return user_rules[0].allowed" in source
    assert "relevant[-1]" not in source


def test_dashboard_distinguishes_expired_discord_tokens_from_service_outages() -> None:
    source = Path("app/dashboard/main.py").read_text(encoding="utf-8")
    start = source.index("async def discord_get")
    end = source.index("async def discord_token", start)
    block = source[start:end]
    assert "if response.status_code == 401:" in block
    assert 'status_code=401' in block
    assert "if response.status_code == 403:" in block
    assert 'status_code=502' in block


def test_automod_skips_invalid_rule_rows_instead_of_aborting_evaluation() -> None:
    source = Path("app/discord/cogs/automod.py").read_text(encoding="utf-8")
    start = source.index("for row in rule_rows:")
    end = source.index("whitelist =", start)
    block = source[start:end]
    assert "config_errors = validate_rule_config" in block
    assert "if config_errors:" in block
    assert "continue" in block


def test_dashboard_redirects_expired_api_sessions_to_oauth_login() -> None:
    source = Path("app/dashboard/static/app.js").read_text(encoding="utf-8")
    assert "response.status===401" in source
    assert "window.location.href='/auth/login'" in source


def test_worker_only_deletes_temporary_role_record_after_confirmed_completion_or_nonexistent_guild() -> None:
    source = Path("app/tasks/worker.py").read_text(encoding="utf-8")
    block = source[source.index("async def temporary_roles"):source.index("@temporary_roles.before_loop")]
    assert "delete_record = False" in block
    assert "cleanup deferred" in block
    assert "except discord.HTTPException:" in block
    assert "continue" in block


def test_on_ready_backfills_existing_guilds_for_dashboard() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert "async def _ensure_registered_guilds" in source
    assert "await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)" in source
    ready_start = source.index("async def on_ready")
    ready_end = source.index("async def close", ready_start)
    ready = source[ready_start:ready_end]
    assert "await self._ensure_registered_guilds()" in ready


def test_automod_invalid_rule_is_skipped_before_rule_evaluation() -> None:
    source = Path("app/discord/cogs/automod.py").read_text(encoding="utf-8")
    start = source.index("for row in rule_rows:")
    end = source.index("whitelist =", start)
    block = source[start:end]
    assert "validate_rule_config(row.rule_type, config)" in block
    assert "if config_errors:" in block
    assert "continue" in block
    assert "rules.append(_rule_definition(row))" in block


def test_command_matrix_covers_all_handlers() -> None:
    from app.services.command_matrix import audit_summary
    ok, cases, issues = audit_summary()
    assert ok, issues
    assert len(cases) == len(EXPECTED_COMMANDS)




def test_timeout_removal_commands_have_matching_permissions_and_api_calls() -> None:
    source = Path("app/discord/cogs/moderation.py").read_text(encoding="utf-8")
    for name in ("untimeout", "unmute"):
        assert f'@app_commands.command(name="{name}"' in source
        assert f'async def {name}' in source
    assert '@app_commands.checks.has_permissions(moderate_members=True)' in source
    assert 'await user.timeout(None' in source

def test_development_guild_sync_does_not_copy_global_commands_into_guild_scope() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    block = source[source.index("async def _sync_guild_commands"):source.index("async def _sync_command_scopes", source.index("async def _sync_guild_commands"))]
    assert 'self.tree.add_command(command, guild=guild_object)' in block
    assert 'self.tree.copy_global_to(guild=guild_object)' not in block

def test_guild_command_sync_verifies_guild_scoped_local_commands() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    block = source[source.index("async def _sync_guild_commands"):source.index("async def _sync_command_scopes", source.index("async def _sync_guild_commands"))]
    assert 'self.tree.walk_commands(guild=guild_object)' in block

def test_dashboard_is_registered_and_executable() -> None:
    bot = Path("app/discord/bot.py").read_text(encoding="utf-8")
    dashboard = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert "from app.discord.cogs.dashboard import DashboardCog" in bot
    assert "await self.add_cog(DashboardCog(self))" in bot
    assert '@app_commands.command(name="dashboard"' in dashboard
    assert "DashboardHomeView" in dashboard
    assert "confirm_or_execute" in dashboard


def test_dashboard_choice_parser_preserves_choice_objects_only_when_annotation_requires_them() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert 'expects_choice = "Choice" in annotation_text(command, parameter.name)' in source
    assert "return choice if expects_choice else choice.value" in source


def test_command_matrix_uses_group_qualified_names() -> None:
    from app.services.command_matrix import audit_commands
    names = {case.qualified_name for case in audit_commands()}
    assert "admin credit" in names
    assert "automod rule-add" in names
    assert "giveaway create" in names
    assert "poll create" in names
    assert "dashboard" in names


def test_dashboard_awaits_async_discord_object_parser() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert "return await parse_discord_object(interaction, command, parameter, raw)" in source


def test_reminder_channel_delivery_blocks_unintended_everyone_and_role_mentions() -> None:
    source = Path("app/tasks/worker.py").read_text(encoding="utf-8")
    block = source[source.index("async def reminders"):source.index("@reminders.before_loop")]
    assert "allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)" in block


def test_serial_ids_are_flushed_before_their_values_are_used() -> None:
    checks = {
        "app/discord/cogs/admin.py": [("ShopItem(", "item_id = row.id"), ("Job(", "job_id = row.id")],
        "app/discord/cogs/automod.py": [("AutoModRule(", "rule_id = row.id")],
    }
    for file_name, pairs in checks.items():
        source = Path(file_name).read_text(encoding="utf-8")
        for start_token, id_token in pairs:
            start = source.index(start_token)
            end = source.index(id_token, start) + len(id_token)
            block = source[start:end]
            assert "await session.flush()" in block
            assert block.index("await session.flush()") < block.index(id_token)


def test_command_matrix_contains_each_expected_command_exactly_once() -> None:
    from app.services.command_matrix import EXPECTED_COMMANDS, audit_commands
    names = [case.qualified_name for case in audit_commands()]
    assert len(names) == len(set(names))
    assert set(names) == EXPECTED_COMMANDS


def test_dashboard_rejects_non_snowflake_input_without_stripping_arbitrary_characters() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert 're.fullmatch(r"<@!?([0-9]+)>|<#([0-9]+)>|<@&([0-9]+)>", value)' in source
    assert 'parse_snowflake(value)' in source
    assert 're.sub(r"\\D", "", value)' not in source


def test_antiraid_has_runtime_redis_fallback() -> None:
    source = Path("app/services/antiraid.py").read_text(encoding="utf-8")
    start = source.index("store = await get_store()")
    end = source.index("context.recent_joins = recent_joins", start)
    block = source[start:end]
    assert "except Exception:" in block
    assert "if store.redis is None:" in block
    assert "RaidWindowStore(None)" in block


def test_ticket_creation_uses_priority_labels_instead_of_status_labels() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    assert 'priority_labels = {"low": "baixa", "normal": "normal", "high": "alta", "urgent": "urgente"}' in source
    assert 'STATUS_LABELS.get(priority, priority)' not in source


def test_ticket_channel_creation_fetches_uncached_opener() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    block = source[source.index("async def ensure_ticket_channel"):source.index("async def build_ticket_message", source.index("async def ensure_ticket_channel"))]
    assert "guild.get_member(ticket.opener_id)" in block
    assert "await guild.fetch_member(ticket.opener_id)" in block


def test_rewards_falls_back_to_utc_when_saved_timezone_is_invalid() -> None:
    source = Path("app/services/rewards.py").read_text(encoding="utf-8")
    assert "except ZoneInfoNotFoundError:" in source
    assert 'local_now("UTC")' in source


def test_giveaway_result_message_restricts_allowed_mentions() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    block = source[source.index("async def finish_giveaway"):source.index("poll_group =", source.index("async def finish_giveaway"))]
    assert "allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)" in block


def test_command_matrix_detects_indirect_staff_guard() -> None:
    from app.services.command_matrix import audit_commands
    case = next(case for case in audit_commands() if case.qualified_name == "ticket-claim")
    assert case.permission_guard


def test_command_matrix_enforces_protection_contracts() -> None:
    from app.services.command_matrix import PROTECTED_COMMANDS, audit_commands
    cases = {case.qualified_name: case for case in audit_commands()}
    assert all(cases[name].permission_guard for name in PROTECTED_COMMANDS)
