"""Redis client utilities.

Provides a wrapper around the redis client for state management
used by the MCP operator (sessions, cache, rate limiting).
"""

from typing import Any

import redis


class RedisClient:
    """Redis client wrapper for MCP operator state management."""

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0) -> None:
        """Initialize the Redis client.

        Args:
            host: Redis host.
            port: Redis port.
            db: Redis database number.
        """
        self._client = redis.Redis(host=host, port=port, db=db, decode_responses=True)

    @classmethod
    def from_service(cls, service_name: str, namespace: str) -> "RedisClient":
        """Create a RedisClient from a Kubernetes service reference.

        Args:
            service_name: The Redis service name.
            namespace: The Redis service namespace.

        Returns:
            A configured RedisClient.
        """
        host = f"{service_name}.{namespace}.svc.cluster.local"
        return cls(host=host)

    def ping(self) -> bool:
        """Check if Redis is available.

        Returns:
            True if Redis responds to ping, False otherwise.
        """
        try:
            return self._client.ping()
        except redis.ConnectionError:
            return False

    def get(self, key: str) -> str | None:
        """Get a value by key.

        Args:
            key: The key to get.

        Returns:
            The value, or None if not found.
        """
        return self._client.get(key)

    def set(self, key: str, value: str, ex: int | None = None, px: int | None = None) -> bool:
        """Set a value by key.

        Args:
            key: The key to set.
            value: The value to set.
            ex: Expiry time in seconds.
            px: Expiry time in milliseconds.

        Returns:
            True if set successfully.
        """
        return bool(self._client.set(key, value, ex=ex, px=px))

    def delete(self, key: str) -> int:
        """Delete a key.

        Args:
            key: The key to delete.

        Returns:
            The number of keys deleted.
        """
        return self._client.delete(key)

    def hget(self, name: str, key: str) -> str | None:
        """Get a hash field value.

        Args:
            name: The hash name.
            key: The field key.

        Returns:
            The field value, or None if not found.
        """
        return self._client.hget(name, key)

    def hset(self, name: str, key: str, value: str) -> int:
        """Set a hash field value.

        Args:
            name: The hash name.
            key: The field key.
            value: The field value.

        Returns:
            1 if new field, 0 if updated.
        """
        return self._client.hset(name, key, value)

    def hgetall(self, name: str) -> dict[str, Any]:
        """Get all fields in a hash.

        Args:
            name: The hash name.

        Returns:
            Dict of all field key-value pairs.
        """
        return self._client.hgetall(name)

    def incr(self, key: str) -> int:
        """Increment a counter.

        Args:
            key: The counter key.

        Returns:
            The new counter value.
        """
        return self._client.incr(key)

    def expire(self, key: str, seconds: int) -> bool:
        """Set expiry on a key.

        Args:
            key: The key.
            seconds: Expiry time in seconds.

        Returns:
            True if expiry was set.
        """
        return self._client.expire(key, seconds)
