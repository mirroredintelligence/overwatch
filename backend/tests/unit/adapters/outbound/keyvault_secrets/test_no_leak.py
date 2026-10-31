"""A secret value is never in a log line, a repr, `vars()`, an exception or a traceback (DEC-1304
item 4). The value is a canary text; the provider's own error text is a second canary, because only
the type of a provider error may be logged."""

import logging
import traceback

import pytest
from azure.core.exceptions import HttpResponseError

from diucs.adapters.outbound.keyvault_secrets import KeyVaultSecretStore
from diucs.application.ports.outbound.tokens import SecretStoreUnavailable
from diucs.domain.errors import NotFound
from tests.support.fake_key_vault import FakeKeyVaultClient, FakeMonotonic

CANARY = "CANARY-secret-value-5b1c0f9e"
PROVIDER_DETAIL = "PROVIDER-DETAIL-canary-77d2"


def _everything_that_can_show_a_value(
    store: KeyVaultSecretStore, client: FakeKeyVaultClient
) -> list[str]:
    return [repr(store), str(store), repr(vars(store)), str(vars(store)), repr(client)]


def test_nothing_shows_the_value_through_a_whole_life(caplog: pytest.LogCaptureFixture) -> None:
    client = FakeKeyVaultClient({"bff-jwt": CANARY, "twilio--tenant-a--auth-token": CANARY})
    clock = FakeMonotonic()
    store = KeyVaultSecretStore(client, cache_seconds=600, stale_seconds=3600, clock=clock)
    shown: list[str] = []

    def capture(error: BaseException) -> None:
        shown.append("".join(traceback.format_exception(error)))
        shown.append(str(error))
        shown.append(repr(error))

    with caplog.at_level(logging.DEBUG):
        assert store.get("bff-jwt") == CANARY.encode()  # a read
        assert store.get("bff-jwt") == CANARY.encode()  # a cached read
        assert store.get("twilio/tenant-a/auth-token") == CANARY.encode()
        shown += _everything_that_can_show_a_value(store, client)

        for refused in ("a--b", "A", ""):
            with pytest.raises(NotFound) as refusal:
                store.get(refused)
            capture(refusal.value)
        with pytest.raises(NotFound) as missing:
            store.get("not-there")
        capture(missing.value)

        client.fail(HttpResponseError(PROVIDER_DETAIL))
        clock.advance(600)
        assert store.get("bff-jwt") == CANARY.encode()  # stale served, a warning logged
        with pytest.raises(SecretStoreUnavailable) as outage:
            store.get("never-held")
        capture(outage.value)
        clock.advance(3600)
        with pytest.raises(SecretStoreUnavailable) as closed:
            store.get("bff-jwt")  # the window has closed
        capture(closed.value)
        shown += _everything_that_can_show_a_value(store, client)

    text = caplog.text + "\n" + "\n".join(shown)
    assert CANARY not in text
    assert PROVIDER_DETAIL not in text
    assert "bff-jwt" in caplog.text  # the name is what the log is for
    assert caplog.records, "the run must have logged something for this test to mean anything"


def test_the_exception_does_not_chain_the_provider_error() -> None:
    client = FakeKeyVaultClient({"bff-jwt": CANARY})
    client.fail(HttpResponseError(PROVIDER_DETAIL))
    store = KeyVaultSecretStore(client)

    with pytest.raises(SecretStoreUnavailable) as outage:
        store.get("bff-jwt")

    assert outage.value.__cause__ is None
    assert outage.value.__suppress_context__ is True


def test_the_held_value_is_not_in_the_repr_of_the_cache() -> None:
    client = FakeKeyVaultClient({"bff-jwt": CANARY})
    store = KeyVaultSecretStore(client)
    store.get("bff-jwt")

    for name, attribute in vars(store).items():
        assert CANARY not in repr(attribute), name
        assert CANARY.encode() not in repr(attribute).encode(), name
