"""Every Redis client the process builds survives an idle connection the network closed (DEC-1333).

The container's shared client served sessions, codes, the rate limiter and the cache without these
settings, so the first call after an idle spell failed with a ConnectionError (the operator sign-in's
POST /auth/operator-token returned 500 for that reason)."""

from overwatch.bootstrap.container import _redis_client


def test_the_container_client_has_a_health_check_keepalive_and_retry() -> None:
    client = _redis_client("redis://:secret@redis:6379/0")
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["health_check_interval"] > 0
    assert kwargs["socket_keepalive"] is True
    assert client.get_retry() is not None
