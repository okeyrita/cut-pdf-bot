"""Per-user job slots.

PDF work is expensive and the worker pool is small. Without a cap, one user forwarding a folder of
books occupies every worker and everyone else waits. The counter lives in Redis with a TTL, so a
crashed bot cannot leak a slot forever.
"""

import logging

from redis.asyncio import Redis as AsyncRedis


logger = logging.getLogger(__name__)

_KEY = "pdfbot:active:{user_id}"


class JobSlots:
    """Counts a user's in-flight jobs."""

    def __init__(self, redis: AsyncRedis, limit: int, ttl_seconds: int) -> None:
        self._redis = redis
        self._limit = limit
        self._ttl = ttl_seconds

    @staticmethod
    def key(user_id: int) -> str:
        return _KEY.format(user_id=user_id)

    async def acquire(self, user_id: int) -> bool:
        """Take a slot. Returns False when the user is already at the limit.

        ``INCR`` then check, rather than check-then-increment: the former is atomic, so two updates
        arriving together cannot both pass the check.
        """
        key = self.key(user_id)
        count = await self._redis.incr(key)
        if count == 1:
            # TTL is the leak guard: if the bot dies before release(), the slot frees itself.
            await self._redis.expire(key, self._ttl)
        if count > self._limit:
            await self._redis.decr(key)
            return False
        return True

    async def release(self, user_id: int) -> None:
        """Give a slot back. Never lets the counter go negative."""
        key = self.key(user_id)
        count = await self._redis.decr(key)
        if count <= 0:
            await self._redis.delete(key)

    async def active(self, user_id: int) -> int:
        raw = await self._redis.get(self.key(user_id))
        return int(raw) if raw else 0
