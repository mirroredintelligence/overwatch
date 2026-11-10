"""The Redis client keeps an idle connection alive sooner than the network would close it."""

import socket

import pytest

from overwatch.adapters.outbound.cache_redis import redis_cache


@pytest.mark.skipif(not hasattr(socket, "TCP_KEEPIDLE"), reason="this platform has no TCP_KEEPIDLE")
def test_keep_alive_starts_within_a_minute_and_gives_up_a_dead_peer_within_two() -> None:
    options = redis_cache.keepalive_options()
    assert options[socket.TCP_KEEPIDLE] == 60
    assert (
        options[socket.TCP_KEEPIDLE] + options[socket.TCP_KEEPINTVL] * options[socket.TCP_KEEPCNT]
        <= 120
    )


def test_only_the_options_the_platform_has_are_set() -> None:
    assert all(isinstance(key, int) for key in redis_cache.keepalive_options())
