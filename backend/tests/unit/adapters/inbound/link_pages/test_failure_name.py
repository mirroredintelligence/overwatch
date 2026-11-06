"""The link page logs which dependency failed (the one-off 500 on a link, DEC-1343 follow-up): the
class with its module, never the message."""

from redis.exceptions import ConnectionError as RedisConnectionError

from overwatch.adapters.inbound.link_pages.capacity_links import failure_name


def test_a_redis_connection_error_is_named_with_its_module() -> None:
    assert failure_name(RedisConnectionError("Error 22 connecting to host:6379")) == (
        "redis.exceptions.ConnectionError"
    )


def test_the_message_is_never_in_the_name() -> None:
    assert "host" not in failure_name(RedisConnectionError("Error 22 connecting to host:6379"))


def test_a_builtin_connection_error_is_told_apart_from_redis() -> None:
    assert failure_name(ConnectionError("reset")) == "builtins.ConnectionError"
