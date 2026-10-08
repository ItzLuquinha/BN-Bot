from __future__ import annotations

from collections.abc import Callable, Hashable
import discord
from discord import app_commands

from app.core.exceptions import CooldownActive
from app.services.cooldowns import check_and_set


def command_rate_limit(prefix: str, seconds: int, key: Callable[[discord.Interaction], Hashable] | None = None):
    if not prefix or seconds <= 0:
        raise ValueError("invalid rate limit configuration")

    def decorator(func):
        async def predicate(interaction: discord.Interaction) -> bool:
            value = key(interaction) if key is not None else interaction.user.id
            guild_id = interaction.guild_id or 0
            bucket = f"bn:rl:{prefix}:{guild_id}:{value}"
            retry_after = await check_and_set(bucket, seconds)
            if retry_after is not None:
                raise CooldownActive(retry_after)
            return True

        return app_commands.check(predicate)(func)

    return decorator
