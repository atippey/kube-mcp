"""Unit tests for Redis client utilities."""

from unittest.mock import MagicMock, patch

import redis
from src.utils.redis_client import RedisClient


class TestRedisClientInit:
    """Tests for RedisClient initialization."""

    def test_init_default(self) -> None:
        """Test default initialization."""
        with patch("redis.Redis") as mock_redis:
            client = RedisClient()
            mock_redis.assert_called_once_with(
                host="localhost", port=6379, db=0, decode_responses=True
            )
            assert client._client == mock_redis.return_value

    def test_init_custom(self) -> None:
        """Test initialization with custom parameters."""
        with patch("redis.Redis") as mock_redis:
            client = RedisClient(host="redis-host", port=1234, db=5)
            mock_redis.assert_called_once_with(
                host="redis-host", port=1234, db=5, decode_responses=True
            )
            assert client._client == mock_redis.return_value

    def test_from_service(self) -> None:
        """Test initialization from Kubernetes service."""
        with patch("redis.Redis") as mock_redis:
            client = RedisClient.from_service("redis-svc", "default")
            mock_redis.assert_called_once_with(
                host="redis-svc.default.svc.cluster.local",
                port=6379,
                db=0,
                decode_responses=True,
            )
            assert client._client == mock_redis.return_value


class TestRedisClientPing:
    """Tests for RedisClient.ping."""

    def test_ping_success(self) -> None:
        """Test ping success."""
        with patch("redis.Redis") as mock_redis:
            mock_redis.return_value.ping.return_value = True
            client = RedisClient()
            assert client.ping() is True

    def test_ping_failure(self) -> None:
        """Test ping failure."""
        with patch("redis.Redis") as mock_redis:
            mock_redis.return_value.ping.side_effect = redis.ConnectionError("Connection refused")
            client = RedisClient()
            assert client.ping() is False


class TestRedisClientBasicOps:
    """Tests for basic Redis operations (get, set, delete)."""

    def test_get(self) -> None:
        """Test get operation."""
        with patch("redis.Redis") as mock_redis:
            client = RedisClient()
            mock_redis.return_value.get.return_value = "value"

            result = client.get("key")

            assert result == "value"
            mock_redis.return_value.get.assert_called_once_with("key")

    def test_get_none(self) -> None:
        """Test get operation when key does not exist."""
        with patch("redis.Redis") as mock_redis:
            client = RedisClient()
            mock_redis.return_value.get.return_value = None

            result = client.get("key")

            assert result is None
            mock_redis.return_value.get.assert_called_once_with("key")

    def test_set(self) -> None:
        """Test set operation."""
        with patch("redis.Redis") as mock_redis:
            client = RedisClient()
            mock_redis.return_value.set.return_value = True

            result = client.set("key", "value")

            assert result is True
            mock_redis.return_value.set.assert_called_once_with("key", "value", ex=None, px=None)

    def test_set_with_expiry(self) -> None:
        """Test set operation with expiry."""
        with patch("redis.Redis") as mock_redis:
            client = RedisClient()
            mock_redis.return_value.set.return_value = True

            result = client.set("key", "value", ex=60)

            assert result is True
            mock_redis.return_value.set.assert_called_once_with("key", "value", ex=60, px=None)

    def test_delete(self) -> None:
        """Test delete operation."""
        with patch("redis.Redis") as mock_redis:
            client = RedisClient()
            mock_redis.return_value.delete.return_value = 1

            result = client.delete("key")

            assert result == 1
            mock_redis.return_value.delete.assert_called_once_with("key")


class TestRedisClientHashOps:
    """Tests for Redis hash operations."""

    def test_hget(self) -> None:
        """Test hget operation."""
        with patch("redis.Redis") as mock_redis:
            client = RedisClient()
            mock_redis.return_value.hget.return_value = "value"

            result = client.hget("name", "key")

            assert result == "value"
            mock_redis.return_value.hget.assert_called_once_with("name", "key")

    def test_hset(self) -> None:
        """Test hset operation."""
        with patch("redis.Redis") as mock_redis:
            client = RedisClient()
            mock_redis.return_value.hset.return_value = 1

            result = client.hset("name", "key", "value")

            assert result == 1
            mock_redis.return_value.hset.assert_called_once_with("name", "key", "value")

    def test_hgetall(self) -> None:
        """Test hgetall operation."""
        with patch("redis.Redis") as mock_redis:
            client = RedisClient()
            expected_dict = {"key1": "value1", "key2": "value2"}
            mock_redis.return_value.hgetall.return_value = expected_dict

            result = client.hgetall("name")

            assert result == expected_dict
            mock_redis.return_value.hgetall.assert_called_once_with("name")


class TestRedisClientOtherOps:
    """Tests for other Redis operations (incr, expire)."""

    def test_incr(self) -> None:
        """Test incr operation."""
        with patch("redis.Redis") as mock_redis:
            client = RedisClient()
            mock_redis.return_value.incr.return_value = 5

            result = client.incr("key")

            assert result == 5
            mock_redis.return_value.incr.assert_called_once_with("key")

    def test_expire(self) -> None:
        """Test expire operation."""
        with patch("redis.Redis") as mock_redis:
            client = RedisClient()
            mock_redis.return_value.expire.return_value = True

            result = client.expire("key", 60)

            assert result is True
            mock_redis.return_value.expire.assert_called_once_with("key", 60)
