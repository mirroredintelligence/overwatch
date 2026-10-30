"""Host-based tenant resolution for routes that carry no token (TEN-040, DEC-134 item 3).

The tenant is the one the request host names in the tenant directory, and nothing else: no header
(including the forwarded ones), query, cookie or body is read for it. A host no tenant owns, a
tenant that is not active, a damaged record and a request with no usable host all answer exactly as
a resource that is not there. The binding lasts for the request and nothing is left bound.
"""

import asyncio
from typing import Annotated, Any

import httpx
import pytest
from fastapi import Depends, FastAPI
from starlette.requests import Request

from diucs.adapters.inbound.fhir_rest.errors import NOT_FOUND_TEXT, install_exception_handlers
from diucs.adapters.inbound.fhir_rest.host_tenant import (
    HostNotResolved,
    bind_host_tenant,
    request_host,
    resolve_request_tenant,
)
from diucs.application.ports.outbound.tenants import TenantRecordInvalid
from diucs.application.tenancy import current_scope_or_none, current_tenant
from diucs.domain.errors import NotFound
from diucs.domain.model.tenant import Tenant, TenantStatus
from tests.support.tenant_samples import make_tenant

HOST_A = "a.example.test"
HOST_B = "b.example.test"
SUSPENDED = "s.example.test"
DAMAGED = "d.example.test"
UNKNOWN = "x.example.test"


class _Directory:
    def __init__(self) -> None:
        self.asked: list[str] = []
        self._by_host: dict[str, Any] = {
            HOST_A: make_tenant(id="tenant-a"),
            HOST_B: make_tenant(id="tenant-b"),
            SUSPENDED: make_tenant(TenantStatus.SUSPENDED, id="tenant-s"),
            DAMAGED: TenantRecordInvalid("damaged"),
        }

    async def by_host(self, host: str) -> Tenant | None:
        self.asked.append(host)
        value = self._by_host.get(host)
        if isinstance(value, Exception):
            raise value
        return value  # type: ignore[no-any-return]


class _Container:
    def __init__(self) -> None:
        self.tenants = _Directory()


def _request(
    headers: list[tuple[bytes, bytes]], server: tuple[str, int] = ("ignored", 80)
) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/x",
            "headers": headers,
            "server": server,
            "scheme": "http",
            "query_string": b"",
        }
    )


def _app(container: _Container) -> FastAPI:
    app = FastAPI()
    app.state.container = container
    install_exception_handlers(app)
    seen: list[str | None] = []
    app.state.seen = seen

    @app.get("/x")
    async def route(tenant: Annotated[Tenant, Depends(bind_host_tenant)]) -> dict[str, Any]:
        seen.append(str(current_tenant()))
        return {"bound": str(current_tenant()), "tenant": tenant.id}

    return app


def _client(container: _Container) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=_app(container))
    return httpx.AsyncClient(transport=transport, base_url=f"http://{HOST_A}")


# request_host


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"a.example.test", "a.example.test"),
        (b"A.Example.TEST", "a.example.test"),
        (b"a.example.test:8443", "a.example.test"),
        (b"a.example.test.", "a.example.test"),
    ],
)
def test_the_host_is_the_host_header_in_lower_case_without_port_or_final_dot(
    raw: bytes, expected: str
) -> None:
    assert request_host(_request([(b"host", raw)])) == expected


@pytest.mark.parametrize(
    "raw", [b"", b"a b.example", b"a_b.example", b"-a.example", b"a..example", b"[::1]", b"a/b"]
)
def test_a_host_that_is_not_a_host_name_is_none(raw: bytes) -> None:
    assert request_host(_request([(b"host", raw)])) is None


def test_no_host_header_is_none_even_when_the_server_address_is_known() -> None:
    assert request_host(_request([], server=(HOST_A, 80))) is None


def test_forwarded_host_headers_are_never_read() -> None:
    headers = [
        (b"host", HOST_A.encode()),
        (b"x-forwarded-host", HOST_B.encode()),
        (b"forwarded", f"host={HOST_B}".encode()),
        (b"x-tenant", b"tenant-b"),
        (b"x-original-host", HOST_B.encode()),
    ]
    assert request_host(_request(headers)) == HOST_A


# resolve_request_tenant


async def test_the_resolved_tenant_is_the_one_the_host_names() -> None:
    container = _Container()
    request = _request([(b"host", HOST_B.encode())])
    request.scope["app"] = _app(container)
    tenant = await resolve_request_tenant(request)
    assert tenant is not None
    assert tenant.id == "tenant-b"


# The dependency, through a route


async def test_a_known_host_binds_its_tenant_for_the_request_and_leaves_nothing_bound() -> None:
    container = _Container()
    async with _client(container) as client:
        response = await client.get(f"http://{HOST_B}/x")

    assert response.status_code == 200
    assert response.json() == {"bound": "tenant-b", "tenant": "tenant-b"}
    assert container.tenants.asked == [HOST_B]
    assert current_scope_or_none() is None


async def test_a_header_query_cookie_or_body_naming_another_tenant_changes_nothing() -> None:
    container = _Container()
    async with _client(container) as client:
        response = await client.request(
            "GET",
            f"http://{HOST_A}/x?tenant=tenant-b&tenantId=tenant-b",
            headers={
                "X-Forwarded-Host": HOST_B,
                "X-Tenant": "tenant-b",
                "X-Tenant-Id": "tenant-b",
                "Forwarded": f"host={HOST_B}",
                "Cookie": "tenant=tenant-b",
            },
            content=b'{"tenant": "tenant-b"}',
        )

    assert response.json() == {"bound": "tenant-a", "tenant": "tenant-a"}
    assert container.tenants.asked == [HOST_A]


@pytest.mark.parametrize("host", [UNKNOWN, SUSPENDED, DAMAGED])
async def test_an_unknown_suspended_or_damaged_host_is_not_found_and_runs_no_route(
    host: str,
) -> None:
    container = _Container()
    app = _app(container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get(f"http://{host}/x")

    assert response.status_code == 404
    assert response.json()["issue"][0]["code"] == "not-found"
    assert response.json()["issue"][0]["diagnostics"] == NOT_FOUND_TEXT
    assert app.state.seen == []
    assert current_scope_or_none() is None


async def test_every_refusal_is_byte_for_byte_the_answer_for_a_path_that_is_not_there() -> None:
    container = _Container()
    transport = httpx.ASGITransport(app=_app(container))
    async with httpx.AsyncClient(transport=transport) as client:
        missing = await client.get(f"http://{HOST_A}/nothing-here")
        refusals = [await client.get(f"http://{host}/x") for host in (UNKNOWN, SUSPENDED, DAMAGED)]
        no_host = await client.get("http://a.example.test/x", headers={"Host": "a b"})

    for response in [*refusals, no_host]:
        assert response.status_code == missing.status_code == 404
        assert response.content == missing.content


async def test_a_request_with_an_unusable_host_never_asks_the_directory() -> None:
    container = _Container()
    transport = httpx.ASGITransport(app=_app(container))
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("http://a.example.test/x", headers={"Host": "a b"})

    assert response.status_code == 404
    assert container.tenants.asked == []


def test_the_refusal_is_a_not_found() -> None:
    assert issubclass(HostNotResolved, NotFound)


async def test_a_directory_failure_other_than_a_damaged_record_is_not_an_open_route() -> None:
    class _Down(_Directory):
        async def by_host(self, host: str) -> Tenant | None:
            raise ConnectionError("down")

    container = _Container()
    container.tenants = _Down()
    transport = httpx.ASGITransport(app=_app(container), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get(f"http://{HOST_A}/x")

    assert response.status_code == 500


async def test_two_requests_in_flight_each_keep_their_own_tenant() -> None:
    container = _Container()
    transport = httpx.ASGITransport(app=_app(container))
    async with httpx.AsyncClient(transport=transport) as client:
        first, second = await asyncio.gather(
            client.get(f"http://{HOST_A}/x"), client.get(f"http://{HOST_B}/x")
        )

    assert first.json()["bound"] == "tenant-a"
    assert second.json()["bound"] == "tenant-b"
