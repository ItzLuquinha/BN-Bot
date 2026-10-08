from __future__ import annotations
import re

UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 30 * 86400


def parse_interval(value: str) -> int:
    normalized = value.strip().casefold()
    match = re.fullmatch(r"([1-9][0-9]*)\s*([smhd])", normalized)
    if match is None:
        raise ValueError("invalid bump interval")
    amount = int(match.group(1))
    seconds = amount * UNIT_SECONDS[match.group(2)]
    if seconds < MIN_INTERVAL_SECONDS or seconds > MAX_INTERVAL_SECONDS:
        raise ValueError("bump interval out of range")
    return seconds
