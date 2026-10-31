"""What the callers of `SecretStore.get` do with an unreadable secret (DEC-1304 item 4).

A secret the vault does not hold is `NotFound`, and each caller already decides what that means
(most refuse; the optional ones skip). An unreadable one is `SecretStoreUnavailable`: no caller may
read it as "not configured" and carry on with a default, so each of these must let it through.
"""

import pytest

from diucs.adapters.outbound.keyvault_secrets import KeyVaultSecretStore
from diucs.adapters.outbound.push_webpush.web_push import (
    configured_push_sender,
    vapid_private_key,
)
from diucs.application.ports.outbound.identity import (
    HmacPhoneHasher,
    TenantKeyedSecrets,
    secret_is_configured,
)
from diucs.application.ports.outbound.tokens import LinkTokenService, SecretStoreUnavailable
from diucs.application.use_cases.exchange_token import _secret as exchange_secret
from diucs.bootstrap.api_main import edge_for
from diucs.bootstrap.settings import Settings
from tests.support.fake_key_vault import FakeKeyVaultClient


def _down() -> KeyVaultSecretStore:
    client = FakeKeyVaultClient({"bff-jwt": "x" * 40, "edge-origin": "x" * 40})
    client.fail()
    return KeyVaultSecretStore(client)


async def test_the_link_token_service_does_not_read_an_outage_as_an_unknown_token() -> None:
    service = LinkTokenService(None, _down(), None)  # type: ignore[arg-type]

    with pytest.raises(SecretStoreUnavailable):
        await service.resolve("a-link-token-text")


def test_the_phone_hasher_does_not_hash_with_a_default() -> None:
    with pytest.raises(SecretStoreUnavailable):
        HmacPhoneHasher(_down()).hash("07700 900123")


def test_the_token_exchange_does_not_turn_an_outage_into_a_refusal() -> None:
    with pytest.raises(SecretStoreUnavailable):
        exchange_secret(_down(), "bff-jwt")


def test_the_push_sender_is_not_quietly_switched_off_by_an_outage() -> None:
    with pytest.raises(SecretStoreUnavailable):
        vapid_private_key(_down())
    with pytest.raises(SecretStoreUnavailable):
        configured_push_sender(_down(), "mailto:operations@diucs.example")


def test_the_edge_does_not_drop_its_origin_secret_on_an_outage() -> None:
    with pytest.raises(SecretStoreUnavailable):
        edge_for(Settings(), _down())


def test_the_tenant_keyed_view_passes_the_outage_on() -> None:
    with pytest.raises(SecretStoreUnavailable):
        TenantKeyedSecrets(_down()).get("link-token")


def test_asking_whether_a_secret_is_configured_is_not_answered_no_by_an_outage() -> None:
    with pytest.raises(SecretStoreUnavailable):
        secret_is_configured(_down(), "bff-jwt")
