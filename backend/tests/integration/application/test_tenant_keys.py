"""Per-tenant keys against the real link-token store (TEN-023, DEC-350).

The same token text, issued in two tenants, is two different hashes, because each tenant's key is
derived from the platform secret with the tenant as context. So a hash that tenant A stored is not
the hash tenant B's key gives for that text, the global unique key on the token hash cannot make
one tenant's token collide with another's, and the platform key itself opens nothing.

Synthetic values only. Runs on the shared harness schema: the stored hashes differ, so nothing
needs the contracted schema (DEC-159).
"""

from datetime import UTC, datetime, timedelta

import pytest
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.identity import TenantKeyedSecrets
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.rules.tenant_keys import derive_tenant_key
from diucs.domain.rules.tokens import hash_token
from tests.support.tenancy import as_tenant
from tests.support.uow import tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

PLATFORM = b"link-token-platform-secret-0123456789"
NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
EXPIRES = NOW + timedelta(minutes=30)
PHONE_HASH = "ab" * 32


def _same_token(count: int) -> bytes:
    return b"\x07" * count


async def _issue(factory: UnitOfWorkFactory, tenant: str) -> str:
    secrets = TenantKeyedSecrets(FixedSecretStore({LINK_TOKEN_SECRET: PLATFORM}))
    with as_tenant(tenant):
        async with factory() as uow:
            service = LinkTokenService(uow.link_tokens, secrets, FixedClock(NOW), rng=_same_token)
            token = await service.issue("booking-reply", "svc-1", PHONE_HASH, EXPIRES)
            await uow.commit()
    return token


async def _resolve(factory: UnitOfWorkFactory, tenant: str, token: str) -> str | None:
    secrets = TenantKeyedSecrets(FixedSecretStore({LINK_TOKEN_SECRET: PLATFORM}))
    with as_tenant(tenant):
        async with factory() as uow:
            record = await LinkTokenService(uow.link_tokens, secrets, FixedClock(NOW)).resolve(
                token
            )
    return None if record is None else record.token_hash


@pytest.mark.usefixtures("clean_graph")
async def test_one_token_text_is_two_hashes_in_two_tenants_and_each_resolves_only_at_home(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    factory_a = tenant_uow_factory(neo4j_driver, tenant_id)
    factory_b = tenant_uow_factory(neo4j_driver, other_tenant_id)

    token_a = await _issue(factory_a, tenant_id)
    token_b = await _issue(factory_b, other_tenant_id)  # no collision on the global unique key

    assert token_a == token_b  # the random source was forced to give one text twice
    hash_a = await _resolve(factory_a, tenant_id, token_a)
    hash_b = await _resolve(factory_b, other_tenant_id, token_b)
    assert hash_a == hash_token(token_a, derive_tenant_key(PLATFORM, tenant_id, LINK_TOKEN_SECRET))
    assert hash_b == hash_token(
        token_b, derive_tenant_key(PLATFORM, other_tenant_id, LINK_TOKEN_SECRET)
    )
    assert hash_a != hash_b


@pytest.mark.usefixtures("clean_graph")
async def test_the_platform_key_and_the_other_tenants_key_open_nothing(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    factory_a = tenant_uow_factory(neo4j_driver, tenant_id)
    token = await _issue(factory_a, tenant_id)

    other_key = hash_token(token, derive_tenant_key(PLATFORM, other_tenant_id, LINK_TOKEN_SECRET))
    platform_hash = hash_token(token, PLATFORM)
    with as_tenant(tenant_id):
        async with factory_a() as uow:
            assert await uow.link_tokens.get_by_hash(other_key) is None
            assert await uow.link_tokens.get_by_hash(platform_hash) is None
            assert await uow.link_tokens.get_by_hash(
                hash_token(token, derive_tenant_key(PLATFORM, tenant_id, LINK_TOKEN_SECRET))
            )


@pytest.mark.usefixtures("clean_graph")
async def test_a_token_issued_in_one_tenant_does_not_resolve_in_another(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    factory_a = tenant_uow_factory(neo4j_driver, tenant_id)
    factory_b = tenant_uow_factory(neo4j_driver, other_tenant_id)
    token = await _issue(factory_a, tenant_id)

    assert await _resolve(factory_a, tenant_id, token) is not None
    assert await _resolve(factory_b, other_tenant_id, token) is None
