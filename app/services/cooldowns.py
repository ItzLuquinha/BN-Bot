import asyncio
from time import monotonic
from app.core.redis import redis_client

_memory: dict[str, float] = {}
_memory_lock = asyncio.Lock()


async def check_and_set(key: str, seconds: int) -> int | None:
    if seconds <= 0:
        return None
    try:
        acquired = await redis_client.set(key, "1", ex=seconds, nx=True)
        if acquired:
            return None
        ttl = await redis_client.ttl(key)
        return max(int(ttl), 1)
    except Exception:
        now = monotonic()
        async with _memory_lock:
            expired = [item for item, expires in _memory.items() if expires <= now]
            for item in expired:
                _memory.pop(item, None)
            expires_at = _memory.get(key)
            if expires_at is not None and expires_at > now:
                return max(int(expires_at - now), 1)
            _memory[key] = now + seconds
            return None


async def release(key: str) -> None:
    try:
        await redis_client.delete(key)
    except Exception:
        async with _memory_lock:
            _memory.pop(key, None)
