"""The device-token dependency of the routes that carry no signed token (TEN-041, DEC-520).

A wall screen presents its opaque device token as a bearer. The tenant is the host's (the one
binder of TEN-040) and the token is looked up inside it, so a token of another tenant, an unknown
one, a missing or malformed header, an unknown host and a suspended tenant all answer the one 404
of a path that is not there, byte for byte. Nothing in the request but the host names a tenant, and
no token reaches a log line.
"""

import logging
from typing import Annotated, Any

import httpx
import pytest
from fastapi import Depends, FastAPI

from diucs.adapters.inbound.fhir_rest.errors import install_exception_handlers
from diucs.adapters.inbound.fhir_rest.token_resolvers import (
    bearer_token,
    resolve_active_device,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.identity import DEVICE_TOKEN_SECRET
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.tenancy import current_scope_or_none, current_tenant
from diucs.application.tenant_resolution import EntryRefused
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from diucs.domain.model.tenant import Tenant, TenantStatus
from diucs.domain.rules.tokens import hash_token
from tests.support.edge import EDGE_NOW
from tests.support.pre_session import Devices, Links, Uow
from tests.support.tenant_samples import make_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

HOST_A, HOST_B, HOST_S = "a.example.test", "b.example.test", "s.example.test"
SECRET = b"synthetic-device-secret-for-resolver-tests-012345"
TOKEN_A = "AbCdEfGhIjKlMnOpQrStUvW"
TOKEN_B = "WvUtSrQpOnMlKjIhGfEdCbA"


def _device(device_id: str, token: str) -> Device:
    return Device(
        id=device_id,
        status=DeviceStatus.ACTIVE,
        name="Ward screen",
        location=None,
        device_type=DeviceType.WALL_DISPLAY,
        token_hash=hash_token(token, SECRET),
        board_scope=BoardScope.TENANT,
    )


class _Directory:
    def __init__(self) -> None:
        self._by_host: dict[str, Tenant] = {
            HOST_A: make_tenant(id="tenant-a"),
            HOST_B: make_tenant(id="tenant-b"),
            HOST_S: make_tenant(TenantStatus.SUSPENDED, id="tenant-s"),
        }

    async def by_host(self, host: str) -> Tenant | None:
        return self._by_host.get(host)


class _Container:
    def __init__(self) -> None:
        self.tenants = _Directory()
        self.clock = FixedClock(EDGE_NOW)
        self.secrets = FixedSecretStore({LINK_TOKEN_SECRET: SECRET, DEVICE_TOKEN_SECRET: SECRET})
        # Each tenant holds its own screens: the unit of work reads the one the host bound.
        self.screens = {
            "tenant-a": {hash_token(TOKEN_A, SECRET): _device("dev-a", TOKEN_A)},
            "tenant-b": {hash_token(TOKEN_B, SECRET): _device("dev-b", TOKEN_B)},
            "tenant-s": {hash_token(TOKEN_A, SECRET): _device("dev-s", TOKEN_A)},
        }

    def uow_factory(self) -> Uow:
        scope = current_scope_or_none()
        assert scope is not None, "the host binder must bind before a unit of work opens"
        return Uow(Links({}), Devices(self.screens[scope.value]), scope)  # type: ignore[arg-type]


def _app() -> FastAPI:
    app = FastAPI()
    app.state.container = _Container()
    install_exception_handlers(app)

    @app.get("/x")
    async def route(device: Annotated[Device, Depends(resolve_active_device)]) -> dict[str, Any]:
        return {"device": device.id, "bound": current_tenant()}

    return app


def _client(app: FastAPI, host: str = HOST_A) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://{host}")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_a_screens_token_resolves_inside_the_tenant_of_the_host() -> None:
    async with _client(_app()) as client:
        response = await client.get("/x", headers=_bearer(TOKEN_A))

    assert response.status_code == 200
    assert response.json() == {"device": "dev-a", "bound": "tenant-a"}


async def test_every_way_of_not_resolving_is_the_same_404_byte_for_byte() -> None:
    app = _app()
    async with _client(app) as client:
        missing_path = await client.get("/nothing-here")
        answers = {
            "no header": await client.get("/x"),
            "not a bearer": await client.get("/x", headers={"Authorization": f"Basic {TOKEN_A}"}),
            "empty bearer": await client.get("/x", headers={"Authorization": "Bearer "}),
            "unknown token": await client.get("/x", headers=_bearer("QqQqQqQqQqQqQqQqQqQqQqQ")),
            "malformed token": await client.get("/x", headers=_bearer("not a token")),
            "another tenant's token": await client.get("/x", headers=_bearer(TOKEN_B)),
        }
    async with _client(app, HOST_S) as client:
        answers["a suspended tenant"] = await client.get("/x", headers=_bearer(TOKEN_A))
    async with _client(app, "unknown.example.test") as client:
        answers["an unknown host"] = await client.get("/x", headers=_bearer(TOKEN_A))

    assert missing_path.status_code == 404
    for name, response in answers.items():
        assert response.status_code == 404, name
        assert response.content == missing_path.content, name
        assert "www-authenticate" not in response.headers, name


async def test_a_forwarded_host_or_tenant_header_does_not_choose_the_tenant() -> None:
    headers = {
        **_bearer(TOKEN_B),
        "X-Forwarded-Host": HOST_B,
        "Forwarded": f"host={HOST_B}",
        "X-Tenant": "tenant-b",
    }
    async with _client(_app(), HOST_A) as client:
        response = await client.get("/x", headers=headers, params={"tenant": "tenant-b"})

    assert response.status_code == 404


async def test_nothing_is_left_bound_after_the_request() -> None:
    async with _client(_app()) as client:
        await client.get("/x", headers=_bearer(TOKEN_A))

    assert current_scope_or_none() is None


async def test_a_token_never_reaches_a_log_line(caplog: pytest.LogCaptureFixture) -> None:
    async with _client(_app()) as client:
        with caplog.at_level(logging.DEBUG):
            await client.get("/x", headers=_bearer(TOKEN_A))
            await client.get("/x", headers=_bearer(TOKEN_B))

    assert TOKEN_A not in caplog.text
    assert TOKEN_B not in caplog.text


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer abc", "abc"),
        ("bearer abc", "abc"),
        ("BEARER   abc  ", "abc"),
    ],
)
def test_the_bearer_is_the_token_after_the_scheme(header: str, expected: str) -> None:
    from starlette.requests import Request

    request = Request(
        {"type": "http", "headers": [(b"authorization", header.encode())], "method": "GET"}
    )

    assert bearer_token(request) == expected


@pytest.mark.parametrize(
    "header", [None, "", "Bearer", "Bearer ", "Basic abc", "abc", "Bearer a b"]
)
def test_a_header_that_is_not_one_bearer_is_refused(header: str | None) -> None:
    from starlette.requests import Request

    headers = [] if header is None else [(b"authorization", header.encode())]
    request = Request({"type": "http", "headers": headers, "method": "GET"})

    with pytest.raises(EntryRefused):
        bearer_token(request)
