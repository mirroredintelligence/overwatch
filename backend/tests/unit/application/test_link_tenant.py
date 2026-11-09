"""A public link names its own tenant (DEC-1354): one host serves every tenant, a tenant with its
own domain still works, and every failure is the same None."""

from typing import Any

import pytest

from overwatch.application.edge_tenant import resolve_hinted_tenant, resolve_link_tenant
from overwatch.application.ports.outbound.tenants import TenantRecordInvalid
from overwatch.domain.model.tenant import TenantStatus
from overwatch.domain.rules.tokens import (
    LINK_TOKEN_LENGTH,
    new_link_token,
    split_link_token,
    tenant_letters,
    tenant_link_token,
)
from tests.support.tenant_samples import make_tenant

TOKEN = new_link_token(lambda n: bytes(range(n)))


class _Directory:  # a stand-in for the directory port, which the function only reads
    def __init__(self, tenant: Any = None, host_tenant: Any = None) -> None:
        self.tenant = tenant
        self.host_tenant = host_tenant
        self.got: list[str] = []
        self.hosts: list[str] = []

    async def get(self, tenant_id: str) -> Any:
        self.got.append(tenant_id)
        if isinstance(self.tenant, Exception):
            raise self.tenant
        return self.tenant

    async def by_host(self, host: str) -> Any:
        self.hosts.append(host)
        return self.host_tenant


@pytest.mark.parametrize("tenant_id", ["fortrus-limited", "a1", "nhs-trust-2", "x" * 31, "0a-9z"])
def test_the_tenant_letters_round_trip_and_are_letters_only(tenant_id: str) -> None:
    letters = tenant_letters(tenant_id)
    assert letters.isalpha() and len(letters) == len(tenant_id)
    assert split_link_token(tenant_link_token(tenant_id, TOKEN)) == (tenant_id, TOKEN)


def test_a_bare_token_has_no_tenant() -> None:
    assert len(TOKEN) == LINK_TOKEN_LENGTH
    assert split_link_token(TOKEN) == (None, TOKEN)


@pytest.mark.parametrize("head", ["Z", "ZZ9", "AB-", "BB" + "Z" * 40])
def test_text_that_is_not_a_tenant_in_front_of_a_token_has_no_tenant(head: str) -> None:
    text = head + TOKEN
    assert split_link_token(text) == (None, text)


async def test_the_token_names_the_tenant_and_the_host_is_not_asked() -> None:
    tenant = make_tenant()
    directory = _Directory(tenant=tenant)
    found = await resolve_link_tenant(
        directory, "shared.example.test", tenant_link_token(tenant.id, TOKEN)
    )  # type: ignore[arg-type]
    assert found is tenant
    assert directory.hosts == []


async def test_a_token_without_a_tenant_falls_back_to_the_host() -> None:
    tenant = make_tenant()
    directory = _Directory(host_tenant=tenant)
    assert await resolve_link_tenant(directory, "own.example.test", TOKEN) is tenant  # type: ignore[arg-type]
    assert directory.hosts == ["own.example.test"]


@pytest.mark.parametrize(
    "status",
    [
        TenantStatus.PROVISIONING,
        TenantStatus.SUSPENDED,
        TenantStatus.OFFBOARDING,
        TenantStatus.PURGED,
    ],
)
async def test_a_tenant_that_is_not_active_is_none(status: TenantStatus) -> None:
    tenant = make_tenant(status)
    directory = _Directory(tenant=tenant)
    assert await resolve_link_tenant(directory, None, tenant_link_token(tenant.id, TOKEN)) is None  # type: ignore[arg-type]


async def test_an_unknown_tenant_and_a_damaged_record_are_none() -> None:
    text = tenant_link_token("nobody-here", TOKEN)
    assert await resolve_link_tenant(_Directory(tenant=None), None, text) is None  # type: ignore[arg-type]
    assert (
        await resolve_link_tenant(_Directory(tenant=TenantRecordInvalid("x")), None, text) is None
    )  # type: ignore[arg-type]


async def test_a_hint_names_the_tenant_and_is_not_replaced_by_the_host() -> None:
    tenant = make_tenant()
    directory = _Directory(tenant=tenant, host_tenant=make_tenant())
    found = await resolve_hinted_tenant(directory, "own.example.test", tenant.id)  # type: ignore[arg-type]
    assert found is tenant
    assert directory.hosts == []


async def test_a_hint_that_names_no_active_tenant_is_none_and_the_host_is_not_tried() -> None:
    directory = _Directory(tenant=None, host_tenant=make_tenant())
    assert await resolve_hinted_tenant(directory, "own.example.test", "nobody") is None  # type: ignore[arg-type]
    assert directory.hosts == []


async def test_no_hint_is_the_host() -> None:
    tenant = make_tenant()
    directory = _Directory(host_tenant=tenant)
    assert await resolve_hinted_tenant(directory, "own.example.test", None) is tenant  # type: ignore[arg-type]


async def test_a_link_with_no_tenant_in_it_uses_the_hint_before_the_host() -> None:
    tenant = make_tenant()
    directory = _Directory(tenant=tenant)
    assert await resolve_link_tenant(directory, "x.example.test", TOKEN, tenant.id) is tenant  # type: ignore[arg-type]
    assert directory.hosts == []
