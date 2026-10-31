"""KeyVaultSecretStore (B8, DEC-1304): the name mapping, the cache, the stale window and the errors.

The client is a fake of `SecretClient` and the clock is moved by the test: no network, no sleeping.
"""

import logging
import threading

import pytest
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ServiceRequestError

from diucs.adapters.outbound.keyvault_secrets import (
    DEFAULT_CACHE_SECONDS,
    DEFAULT_STALE_SECONDS,
    STALE_RETRY_SECONDS,
    KeyVaultSecretStore,
)
from diucs.application.ports.outbound.tokens import SecretStore, SecretStoreUnavailable
from diucs.domain.errors import NotFound
from tests.support.fake_key_vault import FakeKeyVaultClient, FakeMonotonic

TTL = 600
STALE = 3600
VALUE = "fake-value-one"


def _rig(
    secrets: dict[str, str | None] | None = None,
) -> tuple[KeyVaultSecretStore, FakeKeyVaultClient, FakeMonotonic]:
    client = FakeKeyVaultClient({"bff-jwt": VALUE} if secrets is None else secrets)
    clock = FakeMonotonic()
    store = KeyVaultSecretStore(client, cache_seconds=TTL, stale_seconds=STALE, clock=clock)
    return store, client, clock


def test_the_defaults_are_ten_minutes_and_an_hour() -> None:
    assert (DEFAULT_CACHE_SECONDS, DEFAULT_STALE_SECONDS) == (600, 3600)
    assert STALE_RETRY_SECONDS == 30


def test_it_is_a_secret_store() -> None:
    store: SecretStore = _rig()[0]

    assert store.get("bff-jwt") == VALUE.encode()


def test_the_value_is_the_text_as_bytes() -> None:
    store, _, _ = _rig({"bff-jwt": "café-✓"})

    assert store.get("bff-jwt") == "café-✓".encode()


def test_a_name_with_slashes_is_asked_for_by_its_vault_name() -> None:
    store, client, _ = _rig({"twilio--tenant-a--auth-token": "tok"})

    assert store.get("twilio/tenant-a/auth-token") == b"tok"
    assert client.calls == ["twilio--tenant-a--auth-token"]


@pytest.mark.parametrize("name", ["", "a--b", "A", "a_b", "twilio/a/", "x" * 128])
def test_a_refused_name_is_not_found_and_the_vault_is_not_called(name: str) -> None:
    store, client, _ = _rig()

    with pytest.raises(NotFound):
        store.get(name)

    assert client.calls == []


def test_a_secret_the_vault_does_not_hold_is_not_found() -> None:
    store, client, _ = _rig({})

    with pytest.raises(NotFound, match="bff-jwt"):
        store.get("bff-jwt")

    assert client.calls == ["bff-jwt"]


def test_a_secret_with_no_value_is_not_found() -> None:
    store, _, _ = _rig({"bff-jwt": None})

    with pytest.raises(NotFound):
        store.get("bff-jwt")


# ---- the cache


def test_a_second_read_inside_the_ttl_makes_no_vault_call() -> None:
    store, client, clock = _rig()
    store.get("bff-jwt")

    clock.advance(TTL - 1)
    store.get("bff-jwt")

    assert client.calls == ["bff-jwt"]


def test_a_read_at_the_ttl_asks_the_vault_again_and_takes_a_rotated_value() -> None:
    store, client, clock = _rig()
    store.get("bff-jwt")
    client.secrets["bff-jwt"] = "fake-value-two"

    clock.advance(TTL)

    assert store.get("bff-jwt") == b"fake-value-two"
    assert client.calls == ["bff-jwt", "bff-jwt"]


def test_each_name_is_cached_on_its_own() -> None:
    store, client, _ = _rig({"a": "1", "b": "2"})

    assert (store.get("a"), store.get("b"), store.get("a"), store.get("b")) == (
        b"1",
        b"2",
        b"1",
        b"2",
    )
    assert client.calls == ["a", "b"]


def test_a_miss_is_never_cached() -> None:
    store, client, _ = _rig({})
    with pytest.raises(NotFound):
        store.get("bff-jwt")

    client.secrets["bff-jwt"] = VALUE

    assert store.get("bff-jwt") == VALUE.encode()
    assert client.calls == ["bff-jwt", "bff-jwt"]


@pytest.mark.parametrize(
    "error",
    [
        HttpResponseError("forbidden"),
        ClientAuthenticationError("no token"),
        ServiceRequestError("no route to host"),
        RuntimeError("anything"),
        TimeoutError(),
    ],
    ids=lambda error: type(error).__name__,
)
def test_an_outage_with_nothing_held_fails_closed_and_is_not_cached(error: Exception) -> None:
    store, client, _ = _rig()
    client.fail(error)

    with pytest.raises(SecretStoreUnavailable, match="bff-jwt"):
        store.get("bff-jwt")
    with pytest.raises(SecretStoreUnavailable):
        store.get("bff-jwt")
    assert client.calls == ["bff-jwt", "bff-jwt"]  # nothing held, so nothing to back off from

    client.recover()
    assert store.get("bff-jwt") == VALUE.encode()


def test_an_unreadable_secret_is_not_a_not_found() -> None:
    store, client, _ = _rig()
    client.fail()

    with pytest.raises(SecretStoreUnavailable) as raised:
        store.get("bff-jwt")

    assert not isinstance(raised.value, NotFound)


# ---- stale-if-error


def _expired_and_down() -> tuple[KeyVaultSecretStore, FakeKeyVaultClient, FakeMonotonic]:
    store, client, clock = _rig()
    store.get("bff-jwt")
    client.fail()
    clock.advance(TTL)
    return store, client, clock


def test_a_failed_refresh_serves_the_value_held(caplog: pytest.LogCaptureFixture) -> None:
    store, client, _ = _expired_and_down()

    with caplog.at_level(logging.WARNING):
        assert store.get("bff-jwt") == VALUE.encode()

    assert client.calls == ["bff-jwt", "bff-jwt"]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "bff-jwt" in warnings[0].getMessage()


def test_the_stale_window_ends_at_the_ttl_plus_the_stale_seconds() -> None:
    store, client, clock = _expired_and_down()
    assert store.get("bff-jwt") == VALUE.encode()  # a refresh failed at TTL

    clock.advance(STALE - 1)  # one second before the window closes (age TTL + STALE - 1)
    assert store.get("bff-jwt") == VALUE.encode()

    clock.advance(1)  # age TTL + STALE: the window is closed
    with pytest.raises(SecretStoreUnavailable):
        store.get("bff-jwt")


def test_while_serving_stale_the_vault_is_asked_again_only_after_the_retry_pause() -> None:
    store, client, clock = _expired_and_down()
    store.get("bff-jwt")
    assert len(client.calls) == 2

    clock.advance(STALE_RETRY_SECONDS - 1)
    store.get("bff-jwt")
    assert len(client.calls) == 2  # inside the pause: no call, so a dead vault is not hammered

    clock.advance(1)
    store.get("bff-jwt")
    assert len(client.calls) == 3


def test_when_the_vault_comes_back_the_value_is_fresh_again() -> None:
    store, client, clock = _expired_and_down()
    store.get("bff-jwt")
    client.recover()
    client.secrets["bff-jwt"] = "fake-value-two"

    clock.advance(STALE_RETRY_SECONDS)

    assert store.get("bff-jwt") == b"fake-value-two"
    clock.advance(TTL - 1)
    store.get("bff-jwt")
    assert client.calls.count("bff-jwt") == 3  # the first, the failure, the recovery


def test_a_secret_the_vault_says_is_gone_is_not_served_from_the_cache() -> None:
    store, client, clock = _rig()
    store.get("bff-jwt")
    del client.secrets["bff-jwt"]
    clock.advance(TTL)

    with pytest.raises(NotFound):
        store.get("bff-jwt")
    with pytest.raises(NotFound):
        store.get("bff-jwt")  # evicted, and not found is not cached either


def test_a_failure_serves_only_the_name_that_was_held() -> None:
    store, client, clock = _rig({"a": "1", "b": "2"})
    store.get("a")
    client.fail()
    clock.advance(TTL)

    assert store.get("a") == b"1"
    with pytest.raises(SecretStoreUnavailable):
        store.get("b")


def test_a_zero_stale_window_serves_nothing_stale() -> None:
    client = FakeKeyVaultClient({"bff-jwt": VALUE})
    clock = FakeMonotonic()
    store = KeyVaultSecretStore(client, cache_seconds=TTL, stale_seconds=0, clock=clock)
    store.get("bff-jwt")
    client.fail()
    clock.advance(TTL)

    with pytest.raises(SecretStoreUnavailable):
        store.get("bff-jwt")


@pytest.mark.parametrize("cache,stale", [(-1, 0), (0, -1)])
def test_a_negative_window_is_refused(cache: float, stale: float) -> None:
    with pytest.raises(ValueError, match="seconds"):
        KeyVaultSecretStore(FakeKeyVaultClient(), cache_seconds=cache, stale_seconds=stale)


# ---- concurrency


def test_two_reads_of_one_cold_name_make_one_vault_call() -> None:
    store, client, _ = _rig()
    client.gate = threading.Event()
    results: list[bytes] = []

    def read() -> None:
        results.append(store.get("bff-jwt"))

    first = threading.Thread(target=read)
    first.start()
    assert client.entered.wait(timeout=5)  # the first read is inside the vault call
    second = threading.Thread(target=read)
    second.start()
    second.join(timeout=0.2)  # the second waits for the first, or arrives after it
    client.gate.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert results == [VALUE.encode(), VALUE.encode()]
    assert client.calls == ["bff-jwt"]


def test_a_read_of_another_name_does_not_wait_for_a_slow_one() -> None:
    store, client, _ = _rig({"slow": "1", "quick": "2"})
    gate = threading.Event()
    client.gate = gate
    slow = threading.Thread(target=lambda: store.get("slow"))
    slow.start()
    assert client.entered.wait(timeout=5)
    client.gate = None  # later calls do not wait

    assert store.get("quick") == b"2"

    gate.set()
    slow.join(timeout=5)


# ---- close


def test_close_closes_the_client_and_what_the_builder_gave() -> None:
    client = FakeKeyVaultClient()
    closed: list[str] = []
    store = KeyVaultSecretStore(client, on_close=lambda: closed.append("credential"))

    store.close()

    assert client.closed and closed == ["credential"]
