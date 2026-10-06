from __future__ import annotations
from datetime import timedelta
from decimal import Decimal
import discord

COLORS = {
    "system": 0x20252B,
    "economy": 0x178B63,
    "progression": 0x6D55C7,
    "moderation": 0xC86B52,
    "community": 0x2C7885,
    "security": 0x9F4658,
    "admin": 0xB38A46,
}

SECTIONS = {
    "system": "sistema",
    "economy": "economia",
    "progression": "progressão",
    "moderation": "moderação",
    "community": "comunidade",
    "security": "segurança",
    "admin": "administração",
}

STATUS = {
    "ok": "✓",
    "error": "×",
    "open": "○",
    "active": "●",
    "closed": "■",
    "pending": "◇",
    "warning": "△",
}


def embed(title: str, description: str | None = None, section: str = "system") -> discord.Embed:
    result = discord.Embed(title=title, description=description, color=COLORS.get(section, COLORS["system"]))
    result.set_author(name=f"BN / {SECTIONS.get(section, section)}")
    result.set_footer(text=f"BN Bot · {SECTIONS.get(section, section)}")
    return result


def money(value: Decimal | int | float) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    formatted = f"{amount:,.2f}"
    formatted = formatted.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{formatted} moedas"


def compact_money(value: Decimal | int | float) -> str:
    amount = Decimal(str(value))
    if amount >= 1_000_000_000:
        return f"{amount / Decimal('1000000000'):.1f} bi"
    if amount >= 1_000_000:
        return f"{amount / Decimal('1000000'):.1f} mi"
    if amount >= 1_000:
        return f"{amount / Decimal('1000'):.1f} mil"
    return f"{amount:.2f}".replace(".", ",")


def number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def bar(value: int | float, maximum: int | float, width: int = 12) -> str:
    ratio = 0.0 if maximum <= 0 else min(max(float(value) / float(maximum), 0.0), 1.0)
    filled = round(ratio * width)
    return "▰" * filled + "▱" * (width - filled)


def percent(value: int | float, maximum: int | float) -> str:
    if maximum <= 0:
        return "0%"
    return f"{min(max(float(value) / float(maximum) * 100, 0.0), 100.0):.0f}%"


def duration(value: timedelta | int) -> str:
    seconds = int(value.total_seconds()) if isinstance(value, timedelta) else int(value)
    days, remainder = divmod(max(seconds, 0), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def user_line(member: discord.abc.User) -> str:
    return f"{member.mention} · `{member.id}`"


def status_line(label: str, value: str, status: str = "ok") -> str:
    return f"{STATUS.get(status, status)} **{label}** · {value}"


def result_embed(title: str, description: str, section: str, success: bool = True) -> discord.Embed:
    result = embed(title, description, section)
    result.set_footer(text=f"BN Bot · {SECTIONS.get(section, section)} · {'OK' if success else 'atenção'}")
    return result


def add_result(embed_obj: discord.Embed, label: str, value: str, inline: bool = True) -> None:
    embed_obj.add_field(name=label, value=value, inline=inline)


def ledger(rows: list[tuple[str, str]], width: int = 14) -> str:
    longest = max((len(label) for label, _ in rows), default=0)
    label_width = min(max(longest, width), 22)
    content = "\n".join(f"{label:<{label_width}}  {value}" for label, value in rows)
    return f"```text\n{content}\n```"


def divider(label: str) -> str:
    return f"`── {label} ──`"


def line_chunks(lines: list[str], limit: int = 3800) -> list[str]:
    pages: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            pages.append(current)
            current = line
        else:
            current = candidate
    if current:
        pages.append(current)
    return pages or [""]
