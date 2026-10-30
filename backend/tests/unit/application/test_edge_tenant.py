"""The tenant a host names (TEN-040, DEC-134 item 3, DEC-167 item 1): the directory is asked by the
host and by nothing else, only an active tenant is returned, and a host no tenant owns, a tenant
that is not active and a damaged record all answer the same: None."""

from typing import Any

import pytest

from diucs.application.edge_tenant import resolve_active_tenant
from diucs.application.ports.outbound.tenants import TenantRecordInvalid
from diucs.domain.model.tenant import TenantStatus
from tests.support.tenant_samples import make_tenant


class _Directory:
    def __init__(self, answer: Any) -> None:
        self.asked: list[str] = []
        self._answer = answer

    async def by_host(self, host: str) -> Any:
        self.asked.append(host)
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


async def test_an_active_tenant_is_returned() -> None:
    tenant = make_tenant()
    directory = _Directory(tenant)
    assert await resolve_active_tenant(directory, "a.example.test") is tenant  # type: ignore[arg-type]
    assert directory.asked == ["a.example.test"]


@pytest.mark.parametrize(
    "status",
    [
        TenantStatus.PROVISIONING,
        TenantStatus.SUSPENDED,
        TenantStatus.OFFBOARDING,
        TenantStatus.OFFBOARDED,
        TenantStatus.PURGED,
    ],
)
async def test_a_tenant_that_is_not_active_is_none(status: TenantStatus) -> None:
    directory = _Directory(make_tenant(status))
    assert await resolve_active_tenant(directory, "a.example.test") is None  # type: ignore[arg-type]


async def test_a_host_no_tenant_owns_is_none() -> None:
    directory = _Directory(None)
    assert await resolve_active_tenant(directory, "x.example.test") is None  # type: ignore[arg-type]


async def test_a_damaged_record_is_none_and_not_guessed() -> None:
    directory = _Directory(TenantRecordInvalid("damaged"))
    assert await resolve_active_tenant(directory, "d.example.test") is None  # type: ignore[arg-type]


@pytest.mark.parametrize("host", [None, "", "a b", "a/b", "a:80", "-bad.example", "é.example"])
async def test_a_host_that_is_not_a_host_name_is_none_and_the_directory_is_not_asked(
    host: str | None,
) -> None:
    directory = _Directory(make_tenant())
    assert await resolve_active_tenant(directory, host) is None  # type: ignore[arg-type]
    assert directory.asked == []


async def test_the_host_is_asked_in_lower_case_without_a_final_dot() -> None:
    directory = _Directory(make_tenant())
    await resolve_active_tenant(directory, "A.Example.Test.")  # type: ignore[arg-type]
    assert directory.asked == ["a.example.test"]


async def test_another_error_of_the_directory_is_not_swallowed() -> None:
    directory = _Directory(ConnectionError("down"))
    with pytest.raises(ConnectionError):
        await resolve_active_tenant(directory, "a.example.test")  # type: ignore[arg-type]


async def test_a_record_that_is_not_a_tenant_is_none() -> None:
    directory = _Directory(object())
    assert await resolve_active_tenant(directory, "a.example.test") is None  # type: ignore[arg-type]
