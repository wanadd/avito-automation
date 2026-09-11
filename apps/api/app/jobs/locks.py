import secrets
import uuid

from redis import Redis

from app.core.config import get_settings


class SourceLock:
    def __init__(self, redis: Redis, source_id: uuid.UUID, ttl_seconds: int | None = None):
        self.redis = redis
        self.source_id = source_id
        self.ttl_seconds = ttl_seconds or get_settings().redis_lock_ttl_seconds
        self.key = f"avito:locks:source-collection:{source_id}"
        self.token = secrets.token_hex(16)

    def acquire(self) -> bool:
        return bool(self.redis.set(self.key, self.token, nx=True, ex=self.ttl_seconds))

    def release(self) -> None:
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
          return redis.call("del", KEYS[1])
        end
        return 0
        """
        self.redis.eval(script, 1, self.key, self.token)


class MemorySourceLock:
    _locks: set[uuid.UUID] = set()

    def __init__(self, source_id: uuid.UUID):
        self.source_id = source_id
        self.acquired = False

    def acquire(self) -> bool:
        if self.source_id in self._locks:
            return False
        self._locks.add(self.source_id)
        self.acquired = True
        return True

    def release(self) -> None:
        if self.acquired:
            self._locks.discard(self.source_id)
            self.acquired = False
