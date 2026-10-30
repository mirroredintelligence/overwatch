"""Link and invitation tokens resolve only in the tenant they were issued in (TEN-041, DEC-520).

Two tenants on the shared harness graph. A token is issued in tenant A through the real link-token
service and store. The pre-session resolver, bound to A by the edge (the host), finds it; bound to B
it does not, and answers exactly as it does for a token nobody holds, a token of another purpose
and text that cannot be a token. Each tenant hashes with its own derived key (TEN-023), so the same
token text is two different records, and the one hash the schema keeps unique across tenants
(`link_token_hash`, DEC-228 item 4) cannot be stored twice.

Written in build wave 5 and not run there: the orchestrator runs the full integration suite once on
the merged tip. Synthetic values only.
"""

from datetime import timedelta

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.identity import TenantKeyedSecrets
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenant_resolution import (
    ENTRY_REFUSED_MESSAGE,
    EntryRefused,
    PreSessionResolver,
)
from diucs.bootstrap.container import TEST_NOW
from diucs.domain.errors import Conflict
from diucs.domain.rules.tokens import LinkCheck, hash_token
from tests.support.tenancy import as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

PLATFORM_LINK_KEY = b"synthetic-platform-link-key-for-the-resolver-tests-1234"
PHONE = "f" * 64
UNKNOWN = "QqQqQqQqQqQqQqQqQqQqQqQ"
PURPOSE = "capacity-reply"


@pytest.fixture
def secrets() -> TenantKeyedSecrets:
    return TenantKeyedSecrets(FixedSecretStore({LINK_TOKEN_SECRET: PLATFORM_LINK_KEY}))


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(TEST_NOW)


def _resolver(
    uow_factory: UnitOfWorkFactory, clock: FixedClock, secrets: TenantKeyedSecrets
) -> PreSessionResolver:
    return PreSessionResolver(uow_factory, clock, secrets)


async def _issue(
    uow_factory: UnitOfWorkFactory,
    clock: FixedClock,
    secrets: TenantKeyedSecrets,
    purpose: str = PURPOSE,
    expires_in: timedelta = timedelta(minutes=30),
) -> str:
    """Issue one link in the unit's own tenant and return the token text."""
    async with uow_factory() as uow:
        token = await LinkTokenService(uow.link_tokens, secrets, clock).issue(
            purpose, "c-1", PHONE, clock.now() + expires_in
        )
        await uow.commit()
    return token


async def test_a_link_is_found_in_its_own_tenant_and_refused_in_the_other(
    clean_graph: None,
    uow_factory: UnitOfWorkFactory,
    clock: FixedClock,
    secrets: TenantKeyedSecrets,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    with as_tenant(tenant_id):
        token = await _issue(uow_factory, clock, secrets)
        found = await _resolver(uow_factory, clock, secrets).open_link(token, {PURPOSE})
    assert found.state is LinkCheck.OK
    assert found.record.purpose == PURPOSE

    with as_tenant(other_tenant_id), pytest.raises(EntryRefused):
        await _resolver(uow_factory, clock, secrets).open_link(token, {PURPOSE})


async def test_another_tenants_link_is_refused_exactly_as_a_token_nobody_holds_is(
    clean_graph: None,
    uow_factory: UnitOfWorkFactory,
    clock: FixedClock,
    secrets: TenantKeyedSecrets,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    with as_tenant(tenant_id):
        token = await _issue(uow_factory, clock, secrets)
        wrong_purpose = await _issue(uow_factory, clock, secrets, purpose="invite")

    messages: set[str] = set()
    with as_tenant(other_tenant_id):
        resolver = _resolver(uow_factory, clock, secrets)
        for text in (token, UNKNOWN, "not a token", wrong_purpose):
            with pytest.raises(EntryRefused) as caught:
                await resolver.link(text, {PURPOSE})
            messages.add(str(caught.value))
    assert messages == {ENTRY_REFUSED_MESSAGE}


async def test_the_same_token_text_is_two_records_with_two_keys_in_two_tenants(
    clean_graph: None,
    secrets: TenantKeyedSecrets,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    token = "AbCdEfGhIjKlMnOpQrStUvW"
    with as_tenant(tenant_id):
        hash_a = hash_token(token, secrets.get(LINK_TOKEN_SECRET))
    with as_tenant(other_tenant_id):
        hash_b = hash_token(token, secrets.get(LINK_TOKEN_SECRET))

    assert hash_a != hash_b


async def test_an_expired_link_is_a_state_in_its_tenant_and_open_link_refuses_it(
    clean_graph: None,
    uow_factory: UnitOfWorkFactory,
    clock: FixedClock,
    secrets: TenantKeyedSecrets,
    tenant_id: str,
) -> None:
    with as_tenant(tenant_id):
        token = await _issue(uow_factory, clock, secrets, expires_in=timedelta(minutes=5))
        clock.set(clock.now() + timedelta(minutes=6))
        resolver = _resolver(uow_factory, clock, secrets)

        assert (await resolver.link(token, {PURPOSE})).state is LinkCheck.EXPIRED
        with pytest.raises(EntryRefused):
            await resolver.open_link(token, {PURPOSE})


async def test_a_used_link_is_a_state_in_its_tenant_and_open_link_refuses_it(
    clean_graph: None,
    uow_factory: UnitOfWorkFactory,
    clock: FixedClock,
    secrets: TenantKeyedSecrets,
    tenant_id: str,
) -> None:
    with as_tenant(tenant_id):
        token = await _issue(uow_factory, clock, secrets)
        async with uow_factory() as uow:
            await LinkTokenService(uow.link_tokens, secrets, clock).burn(token, "key-1")
            await uow.commit()
        resolver = _resolver(uow_factory, clock, secrets)

        assert (await resolver.link(token, {PURPOSE})).state is LinkCheck.USED
        with pytest.raises(EntryRefused):
            await resolver.open_link(token, {PURPOSE})


async def test_an_invitation_resolves_only_by_its_purpose_and_only_in_its_tenant(
    clean_graph: None,
    uow_factory: UnitOfWorkFactory,
    clock: FixedClock,
    secrets: TenantKeyedSecrets,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    with as_tenant(tenant_id):
        invitation = await _issue(uow_factory, clock, secrets, purpose="invite")
        capacity = await _issue(uow_factory, clock, secrets)
        resolver = _resolver(uow_factory, clock, secrets)
        found = await resolver.invitation(invitation)
        with pytest.raises(EntryRefused):
            await resolver.invitation(capacity)
    assert found.record.purpose == "invite"

    with as_tenant(other_tenant_id), pytest.raises(EntryRefused):
        await _resolver(uow_factory, clock, secrets).invitation(invitation)


async def test_a_second_tenant_cannot_store_a_hash_the_first_holds(
    clean_graph: None,
    uow_factory: UnitOfWorkFactory,
    clock: FixedClock,
    secrets: TenantKeyedSecrets,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    # `link_token_hash` stays unique across tenants (DEC-228 item 4): a clash cannot tell tenant B
    # that tenant A holds the hash, because a hash made under B's key is never A's.
    with as_tenant(tenant_id):
        token = await _issue(uow_factory, clock, secrets)
        async with uow_factory() as uow:
            record = await uow.link_tokens.get_by_hash(
                hash_token(token, secrets.get(LINK_TOKEN_SECRET))
            )
    assert record is not None

    with as_tenant(other_tenant_id):
        async with uow_factory() as uow:
            with pytest.raises(Conflict):
                await uow.link_tokens.add(record)
