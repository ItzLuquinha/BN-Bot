from pathlib import Path


def test_transfer_updates_lifetime_accounting() -> None:
    source = Path("app/repositories/economy.py").read_text(encoding="utf-8")
    block = source[source.index("async def transfer"):source.index("async def get_shop_items", source.index("async def transfer"))]
    assert "sender.lifetime_spent += amount" in block
    assert "receiver.lifetime_earned += amount" in block


def test_job_queries_are_guild_scoped_on_both_sides_of_the_join() -> None:
    for path in ("app/discord/cogs/economy.py", "app/discord/cogs/progression.py"):
        source = Path(path).read_text(encoding="utf-8")
        assert "Job.guild_id == guild.id" in source


def test_dashboard_community_mutations_use_transition_services() -> None:
    source = Path("app/dashboard/main.py").read_text(encoding="utf-8")
    assert "update_suggestion(session, suggestion_id" in source
    assert "update_report(session, report_id" in source
    assert "set_ticket_status(session, ticket_id" in source
    assert "row.status = payload.status" not in source


def test_dashboard_reopens_closed_tickets_through_the_service_contract() -> None:
    source = Path("app/dashboard/main.py").read_text(encoding="utf-8")
    assert 'service_status = "reopened" if requested_status == "open" and row.status == "closed" else requested_status' in source


def test_missing_ticket_channel_is_persistently_closed_before_cooldown_check() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    block = source[source.index("existing = await session.scalar(select(Ticket)"):source.index("ticket_row = await create_ticket", source.index("existing = await session.scalar(select(Ticket)"))]
    assert 'await set_ticket_status(session, existing.id, interaction.user.id, "closed"' in block
    assert "await session.commit()" in block
    assert block.index("await session.commit()") < block.index("cooldown = await check_and_set")


def test_automod_allowed_extension_policy_is_strict_for_extensionless_files() -> None:
    source = Path("app/services/automod.py").read_text(encoding="utf-8")
    assert 'bool(allowed_extensions and (not extensions or not extensions.issubset(allowed_extensions)))' in source


def test_diagnostics_command_check_uses_command_matrix_as_canonical_inventory() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "EXPECTED_COMMANDS as MATRIX_EXPECTED_COMMANDS" in source
    assert "unexpected = sorted(name for name in command_names if name not in MATRIX_EXPECTED_COMMANDS)" in source


def test_stale_theme_backup_file_is_removed() -> None:
    assert not Path("app/discord/theme.py.new").exists()


def test_removed_gif_is_absent_from_the_project() -> None:
    needle = "L0eLbQSACTr10" + "Voj83"
    for path in Path(".").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        assert needle not in path.read_text(encoding="utf-8")
