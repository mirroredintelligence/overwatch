"""The token exchange routes (TEN-043, DEC-522 to DEC-527): the BFF hands the back end the sign-in,
and the back end answers with the tenant-bound token.

    POST /auth/token           {"idToken"}   staff: the host's tenant, the directory's binding, the
                                             tenant's role mapping
    POST /auth/device-token    Bearer <device token>   a paired wall screen
    POST /auth/operator-token  {"idToken"}   the operator console: the operator directory only

No route has a signed token; the staff and device routes take the tenant from the request HOST (the
one binder), the operator route takes none. Every refusal of the staff route is one 403 with one
body, a device refusal is the one 404 of a path that is not there, the source-address limit is
counted before the host is looked at, and no credential, token or id reaches a log line or a body
that is not the token the caller asked for. The token that comes back is accepted by the real REST
edge for the tenant and role it names, and refused as the other audience's.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
import pytest
from fastapi import Depends, FastAPI

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME, current_actor
from diucs.adapters.inbound.fhir_rest.errors import NOT_FOUND_TEXT
from diucs.adapters.inbound.fhir_rest.routes_auth import (
    DEVICE_PATH,
    EXCHANGE_REQUESTS_PER_ADDRESS,
    EXCHANGE_WINDOW,
    FORBIDDEN_TEXT,
    OPERATOR_PATH,
    STAFF_PATH,
    ExchangeDeps,
)
from diucs.adapters.testing.fake_identity_verifier import FakeIdentityVerifier
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import DEVICE_TOKEN_SECRET
from diucs.application.ports.outbound.identity_verifier import Audience, VerifiedIdentity
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.tenancy import current_scope, current_scope_or_none
from diucs.application.use_cases.exchange_token import ACCOUNT_REF_SECRET, SIGNING_SECRET
from diucs.domain.codes import Role
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from diucs.domain.model.tenant import Tenant, TenantStatus
from diucs.domain.model.tenant_records import (
    BindingStatus,
    EntraBinding,
    MappingStatus,
    RoleMapping,
)
from diucs.domain.rules.bff_token import decode_bff_token, decode_operator_token
from diucs.domain.rules.tokens import hash_token
from tests.support.tenant_samples import make_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
SIGNING = b"synthetic-bff-signing-secret-for-the-route-tests-001"
ACCOUNT_KEY = b"synthetic-account-ref-key-for-the-route-tests-0002"
DEVICE_KEY = b"synthetic-device-key-for-the-route-tests-0000003"
HOST_A, HOST_B, HOST_S = "a.example.test", "b.example.test", "s.example.test"
D_A = "11111111-1111-4111-8111-111111111111"
D_B = "22222222-2222-4222-8222-222222222222"
D_OPERATOR = "99999999-9999-4999-8999-999999999999"
OID = "33333333-3333-4333-8333-333333333333"
G_LEAD = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CREDENTIAL = "synthetic-entra-id-token-0001"
DEVICE_TOKEN = "AbCdEfGhIjKlMnOpQrStUvW"
ADDRESS = "203.0.113.9"
JSON = {"Content-Type": "application/json"}


class _Directory:
    def __init__(self) -> None:
        self.by_host_records: dict[str, Tenant] = {
            HOST_A: make_tenant(id="tenant-a", epoch=4),
            HOST_B: make_tenant(id="tenant-b", epoch=2),
            HOST_S: make_tenant(TenantStatus.SUSPENDED, id="tenant-s"),
        }
        self.by_id = {t.id: t for t in self.by_host_records.values()}

    async def by_host(self, host: str) -> Tenant | None:
        return self.by_host_records.get(host)

    async def get(self, tenant_id: str) -> Tenant | None:
        return self.by_id.get(tenant_id)


class _Config:
    def __init__(self, bindings: list[EntraBinding], mappings: list[RoleMapping]) -> None:
        self._bindings, self._mappings = bindings, mappings

    async def bindings(self) -> tuple[EntraBinding, ...]:
        return tuple(self._bindings)

    async def role_mappings(self) -> tuple[RoleMapping, ...]:
        return tuple(self._mappings)


class _Audit:
    def __init__(self) -> None:
        self.entries: list[Any] = []

    async def append(self, entry: Any) -> None:
        self.entries.append(entry)


class _Devices:
    def __init__(self, devices: dict[str, Device]) -> None:
        self._devices = devices

    async def find_by_token_hash(self, token_hash: str) -> Device | None:
        return self._devices.get(token_hash)


class _Unit:
    def __init__(self, container: _Container) -> None:
        self.unit_scope = current_scope()
        scope = str(self.unit_scope)
        self.tenant_config = container.configs[scope]
        self.audit = container.audit
        self.devices = _Devices(container.devices.get(scope, {}))
        self.link_tokens = None

    async def __aenter__(self) -> _Unit:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


def _verified(directory: str) -> EntraBinding:
    return EntraBinding(
        directory_id=directory,
        status=BindingStatus.VERIFIED,
        verified_at=NOW,
        verified_by_ref="operator-ref-1",
    )


def _device() -> Device:
    return Device(
        id="screen-1",
        status=DeviceStatus.ACTIVE,
        name="Ward screen",
        location=None,
        device_type=DeviceType.WALL_DISPLAY,
        token_hash=hash_token(DEVICE_TOKEN, DEVICE_KEY),
        board_scope=BoardScope.TENANT,
    )


class _Container:
    def __init__(self) -> None:
        self.clock = FixedClock(NOW)
        self.ids = SequentialIds()
        self.tenants = _Directory()
        self.platform_slots = InMemoryCache(self.clock)
        self.audit = _Audit()
        self.secrets = FixedSecretStore(
            {DEVICE_TOKEN_SECRET: DEVICE_KEY, LINK_TOKEN_SECRET: DEVICE_KEY}
        )
        self.configs = {
            "tenant-a": _Config(
                [_verified(D_A)], [RoleMapping(G_LEAD, Role.LEAD, MappingStatus.ACTIVE)]
            ),
            "tenant-b": _Config(
                [_verified(D_B)], [RoleMapping(G_LEAD, Role.LEAD, MappingStatus.ACTIVE)]
            ),
            "tenant-s": _Config([], []),
        }
        self.devices = {"tenant-a": {hash_token(DEVICE_TOKEN, DEVICE_KEY): _device()}}

    def uow_factory(self) -> _Unit:
        return _Unit(self)


def _identity(
    directory: str = D_A, groups: tuple[str, ...] = (G_LEAD,), roles: tuple[str, ...] = ()
):
    return VerifiedIdentity(
        directory_id=directory,
        object_id=OID,
        group_ids=frozenset(groups),
        app_roles=frozenset(roles),
    )


class _Owners:
    def __init__(self, *owners: str) -> None:
        self.owners = frozenset(owners)
        self.asked: list[str] = []

    async def owns_active_network(self, tenant_id: str) -> bool:
        self.asked.append(tenant_id)
        return tenant_id in self.owners


def build(
    *,
    verifier: FakeIdentityVerifier | None = None,
    configured: bool = True,
    ownership: _Owners | None = None,
) -> tuple[FastAPI, _Container]:
    container = _Container()
    app = create_app(container)  # type: ignore[arg-type]
    app.state.secrets = FixedSecretStore({SIGNING_SECRET: SIGNING, ACCOUNT_REF_SECRET: ACCOUNT_KEY})
    if configured:
        verifier = verifier or FakeIdentityVerifier()
        app.state.token_exchange = ExchangeDeps(
            verifier=verifier, operator_directory_id=D_OPERATOR, ownership=ownership
        )

    @app.get("/probe")
    async def probe(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, Any]:
        scope = current_scope_or_none()
        return {"scope": None if scope is None else str(scope), "role": actor.role.value}

    return app, container


def accepting(
    who: VerifiedIdentity | None = None, audience: Audience = Audience.STAFF
) -> FakeIdentityVerifier:
    verifier = FakeIdentityVerifier()
    verifier.accepts(CREDENTIAL, who or _identity(), audience)
    return verifier


def client(app: FastAPI, host: str = HOST_A, address: str = ADDRESS) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(address, 4321), raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url=f"http://{host}")


async def staff(c: httpx.AsyncClient, credential: str = CREDENTIAL, **extra: Any) -> httpx.Response:
    return await c.post(STAFF_PATH, json={"idToken": credential, **extra})


# ----------------------------------------------------------------------- staff


async def test_a_signed_in_member_gets_a_token_the_edge_accepts_for_the_hosts_tenant() -> None:
    app, _ = build(verifier=accepting())

    async with client(app) as c:
        response = await staff(c)
        body = response.json()
        probe = await c.get("/probe", headers={"Authorization": f"Bearer {body['token']}"})

    assert response.status_code == 200
    assert set(body) == {"token", "expiresAt", "role"}
    assert body["role"] == "lead"
    assert body["expiresAt"] == "2026-10-30T17:00:00Z"
    claims = decode_bff_token(body["token"], SIGNING, NOW)
    assert (claims.tenant, claims.epoch, claims.role) == ("tenant-a", 4, Role.LEAD)
    assert probe.json() == {"scope": "tenant-a", "role": "lead"}


G_NETWORK = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


def _network_admin_app(ownership: _Owners | None) -> tuple[FastAPI, _Container]:
    app, container = build(verifier=accepting(_identity(groups=(G_NETWORK,))), ownership=ownership)
    container.configs["tenant-a"] = _Config(
        [_verified(D_A)], [RoleMapping(G_NETWORK, Role.NETWORK_ADMIN, MappingStatus.ACTIVE)]
    )
    return app, container


async def test_the_owner_of_a_network_gets_the_network_administrator_token_for_its_own_host() -> (
    None
):
    owners = _Owners("tenant-a")
    app, _ = _network_admin_app(owners)

    async with client(app) as c:
        response = await staff(c)
        probe = await c.get(
            "/probe", headers={"Authorization": f"Bearer {response.json()['token']}"}
        )

    assert response.status_code == 200 and response.json()["role"] == "network-admin"
    assert probe.json() == {"scope": "tenant-a", "role": "network-admin"}
    assert owners.asked == ["tenant-a"]


async def test_another_tenants_ownership_gives_nothing_on_this_tenants_host() -> None:
    owners = _Owners("tenant-b")
    app, _ = _network_admin_app(owners)

    async with client(app) as c:
        response = await staff(c)

    assert response.status_code == 403
    assert response.content == (await _refused_reference()).content
    assert owners.asked == ["tenant-a"]


async def test_a_process_with_no_registry_never_gives_the_network_administrator_role() -> None:
    app, _ = _network_admin_app(None)

    async with client(app) as c:
        response = await staff(c)

    assert response.status_code == 403


async def _refused_reference() -> httpx.Response:
    """The one refusal, as any other cause gives it: an identity of a directory nobody bound."""
    app, _ = build(verifier=accepting(_identity(directory=D_B)))
    async with client(app) as c:
        return await staff(c)


async def test_the_answer_is_never_stored_and_varies_by_host() -> None:
    app, _ = build(verifier=accepting())

    async with client(app) as c:
        response = await staff(c)

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["vary"] == "Host"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_the_token_is_for_the_host_tenant_and_not_for_the_directory_that_signed_in() -> None:
    # Tenant B's directory, tenant A's host: B's member gets nothing on A's host.
    app, _ = build(verifier=accepting(_identity(D_B)))

    async with client(app, HOST_A) as c:
        on_a = await staff(c)
    async with client(app, HOST_B) as c:
        on_b = await staff(c)

    assert on_a.status_code == 403
    assert on_b.status_code == 200
    assert decode_bff_token(on_b.json()["token"], SIGNING, NOW).tenant == "tenant-b"


async def test_a_forwarded_host_or_a_tenant_in_the_body_or_the_query_names_no_tenant() -> None:
    app, _ = build(verifier=accepting(_identity(D_B)))

    async with client(app, HOST_A) as c:
        forwarded = await c.post(
            STAFF_PATH,
            json={"idToken": CREDENTIAL},
            headers={"X-Forwarded-Host": HOST_B, "X-Tenant": "tenant-b"},
            params={"tenant": "tenant-b"},
        )
        in_body = await staff(c, tenant="tenant-b")

    assert forwarded.status_code == 403
    assert in_body.status_code == 400


async def test_every_refusal_is_the_same_403_with_the_same_bytes() -> None:
    cases: dict[str, httpx.Response] = {}
    app, container = build(verifier=accepting())
    async with client(app) as c:
        cases["bad credential"] = await staff(c, "not-the-credential")
    app, container = build(verifier=accepting(_identity(D_B)))
    async with client(app) as c:
        cases["another tenant's directory"] = await staff(c)
    app, container = build(verifier=accepting(_identity(groups=())))
    async with client(app) as c:
        cases["no group"] = await staff(c)
    app, container = build(verifier=accepting(audience=Audience.OPERATOR))
    async with client(app) as c:
        cases["the other audience"] = await staff(c)

    bodies = {name: response.content for name, response in cases.items()}
    assert {r.status_code for r in cases.values()} == {403}
    assert len(set(bodies.values())) == 1, sorted(bodies)
    assert FORBIDDEN_TEXT.encode() in next(iter(bodies.values()))
    assert FORBIDDEN_TEXT == "Your account does not have access."


async def test_an_unknown_or_suspended_host_is_the_404_of_a_path_that_is_not_there() -> None:
    app, _ = build(verifier=accepting())

    async with client(app, "unknown.example.test") as c:
        unknown = await staff(c)
        missing = await c.get("/nothing-here")
    async with client(app, HOST_S) as c:
        suspended = await staff(c)

    assert unknown.status_code == suspended.status_code == 404
    assert unknown.content == suspended.content == missing.content
    assert NOT_FOUND_TEXT.encode() in unknown.content


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"idToken": ""},
        {"idToken": 7},
        {"idToken": None},
        {"idToken": "x" * 8193},
        {"idToken": CREDENTIAL, "role": "lead"},
        {"idToken": CREDENTIAL, "tenant": "tenant-b"},
        {"idToken": CREDENTIAL, "audience": "operator"},
    ],
)
async def test_a_body_that_is_not_exactly_one_credential_is_a_400(body: dict[str, Any]) -> None:
    app, _ = build(verifier=accepting())

    async with client(app) as c:
        response = await c.post(STAFF_PATH, json=body)

    assert response.status_code == 400
    assert CREDENTIAL not in response.text


async def test_a_post_with_no_json_type_is_refused_before_anything_runs() -> None:
    app, _ = build(verifier=accepting())

    async with client(app) as c:
        response = await c.post(
            STAFF_PATH, content=b"idToken=x", headers={"Content-Type": "text/plain"}
        )

    assert response.status_code == 415


async def test_a_get_is_not_allowed() -> None:
    app, _ = build(verifier=accepting())

    async with client(app) as c:
        response = await c.get(STAFF_PATH)

    assert response.status_code == 405


async def test_nothing_is_left_bound_after_the_request() -> None:
    app, _ = build(verifier=accepting())

    async with client(app) as c:
        await staff(c)

    assert current_scope_or_none() is None


# ----------------------------------------------------------------------- the limit and the faults


async def test_the_source_address_is_limited_before_the_host_is_looked_at() -> None:
    app, container = build(verifier=accepting())

    async with client(app, "unknown.example.test") as c:
        statuses = [(await staff(c)).status_code for _ in range(EXCHANGE_REQUESTS_PER_ADDRESS + 1)]
    async with client_other(app) as other_client:
        other = await staff(other_client)

    assert statuses[:-1] == [404] * EXCHANGE_REQUESTS_PER_ADDRESS
    assert statuses[-1] == 429
    assert other.status_code == 404


def client_other(app: FastAPI) -> httpx.AsyncClient:
    return client(app, "unknown.example.test", "198.51.100.4")


async def test_a_limited_answer_says_when_to_try_again_and_is_never_stored() -> None:
    app, _ = build(verifier=accepting())

    async with client(app) as c:
        for _ in range(EXCHANGE_REQUESTS_PER_ADDRESS):
            await staff(c)
        limited = await staff(c)

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == str(int(EXCHANGE_WINDOW.total_seconds()))
    assert limited.headers["cache-control"] == "no-store"


async def test_a_cache_that_cannot_be_reached_is_a_503_and_never_lets_the_request_through() -> None:
    app, container = build(verifier=accepting())

    async def down(name: str, ttl: Any) -> bool:
        raise ConnectionError("cache is down")

    container.platform_slots.platform_take = down  # type: ignore[method-assign]
    async with client(app) as c:
        response = await staff(c)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert container.audit.entries == []


async def test_a_container_with_no_platform_limiter_is_a_500() -> None:
    app, container = build(verifier=accepting())
    container.platform_slots = None  # type: ignore[assignment]

    async with client(app) as c:
        response = await staff(c)

    assert response.status_code == 500


async def test_a_server_with_no_exchange_configuration_is_a_500_and_not_a_refusal() -> None:
    app, _ = build(configured=False)

    async with client(app) as c:
        response = await staff(c)

    assert response.status_code == 500


async def test_a_server_with_no_signing_secret_is_a_500_and_not_a_refusal() -> None:
    app, _ = build(verifier=accepting())
    app.state.secrets = FixedSecretStore({ACCOUNT_REF_SECRET: ACCOUNT_KEY})

    async with client(app) as c:
        response = await staff(c)

    assert response.status_code == 500
    assert FORBIDDEN_TEXT not in response.text


# ----------------------------------------------------------------------- the wall screen


def device_headers(token: str = DEVICE_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **JSON}


async def test_a_paired_screen_gets_a_wall_token_the_edge_accepts() -> None:
    app, _ = build()

    async with client(app) as c:
        response = await c.post(DEVICE_PATH, json={}, headers=device_headers())
        body = response.json()
        probe = await c.get("/probe", headers={"Authorization": f"Bearer {body['token']}"})

    assert response.status_code == 200
    assert (body["role"], body["expiresAt"]) == ("wall", "2026-10-30T10:00:00Z")
    assert probe.json() == {"scope": "tenant-a", "role": "wall"}
    assert response.headers["cache-control"] == "no-store"


async def test_every_way_of_not_resolving_a_screen_is_the_404_of_a_path_that_is_not_there() -> None:
    app, _ = build()

    async with client(app) as c:
        missing = await c.get("/nothing-here")
        answers = {
            "no header": await c.post(DEVICE_PATH, json={}),
            "unknown token": await c.post(
                DEVICE_PATH, json={}, headers=device_headers("QqQqQqQqQqQqQqQqQqQqQqQ")
            ),
            "malformed": await c.post(DEVICE_PATH, json={}, headers=device_headers("not a token")),
        }
    async with client(app, HOST_B) as c:  # tenant A's screen token, tenant B's host
        answers["another tenant's host"] = await c.post(
            DEVICE_PATH, json={}, headers=device_headers()
        )
    async with client(app, HOST_S) as c:
        answers["a suspended tenant"] = await c.post(DEVICE_PATH, json={}, headers=device_headers())

    for name, response in answers.items():
        assert response.status_code == 404, name
        assert response.content == missing.content, name


async def test_a_screen_exchange_takes_no_body_fields() -> None:
    app, _ = build()

    async with client(app) as c:
        response = await c.post(DEVICE_PATH, json={"tenant": "tenant-b"}, headers=device_headers())

    assert response.status_code == 400


# ----------------------------------------------------------------------- the operator


async def test_an_operator_gets_a_token_for_the_operator_door_only() -> None:
    verifier = accepting(_identity(D_OPERATOR, (), ("DIUCS.Support",)), Audience.OPERATOR)
    app, _ = build(verifier=verifier)

    async with client(app, "ops.example.test") as c:
        response = await c.post(OPERATOR_PATH, json={"idToken": CREDENTIAL})
        token = response.json()["token"]
        probe = await c.get("/probe", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["role"] == "support"
    assert decode_operator_token(token, SIGNING, NOW).role is Role.SUPPORT
    assert probe.status_code == 401  # the tenant API refuses the operator audience


async def test_the_operator_route_needs_no_host_and_binds_no_tenant() -> None:
    verifier = accepting(_identity(D_OPERATOR, (), ("DIUCS.Support",)), Audience.OPERATOR)
    app, container = build(verifier=verifier)

    async with client(app, "unknown.example.test") as c:
        response = await c.post(OPERATOR_PATH, json={"idToken": CREDENTIAL})

    assert response.status_code == 200
    assert current_scope_or_none() is None
    assert container.audit.entries == []


async def test_an_operator_role_from_a_customers_directory_is_the_same_403() -> None:
    verifier = accepting(_identity(D_A, (), ("DIUCS.Support",)), Audience.OPERATOR)
    app, _ = build(verifier=verifier)

    async with client(app) as c:
        response = await c.post(OPERATOR_PATH, json={"idToken": CREDENTIAL})

    assert response.status_code == 403
    assert FORBIDDEN_TEXT in response.text


async def test_the_operator_route_has_its_own_address_limit_before_anything_else() -> None:
    app, _ = build(verifier=FakeIdentityVerifier())

    async with client(app) as c:
        statuses = [
            (await c.post(OPERATOR_PATH, json={"idToken": "x"})).status_code
            for _ in range(EXCHANGE_REQUESTS_PER_ADDRESS + 1)
        ]

    assert statuses == [403] * EXCHANGE_REQUESTS_PER_ADDRESS + [429]


async def test_an_operator_exchange_with_no_operator_directory_is_a_500() -> None:
    app, _ = build(verifier=accepting())
    app.state.token_exchange = ExchangeDeps(verifier=accepting(), operator_directory_id=None)

    async with client(app) as c:
        response = await c.post(OPERATOR_PATH, json={"idToken": CREDENTIAL})

    assert response.status_code == 500


# ---- the operator's sign-in is recorded


class _Platform:
    def __init__(self, fail: bool = False) -> None:
        self.entries: list[Any] = []
        self.fail = fail

    async def append(self, entry: Any) -> None:
        if self.fail:
            raise ConnectionError("platform audit is down")
        self.entries.append(entry)


def _operator_app(platform: _Platform | None, role: str = "DIUCS.Support") -> FastAPI:
    verifier = accepting(_identity(D_OPERATOR, (), (role,)), Audience.OPERATOR)
    app, _ = build(verifier=verifier)
    app.state.token_exchange = ExchangeDeps(
        verifier=verifier, operator_directory_id=D_OPERATOR, platform_audit=platform
    )
    return app


async def test_an_operator_sign_in_is_written_to_the_platform_chain_before_the_token_is_given() -> (
    None
):
    platform = _Platform()
    app = _operator_app(platform)

    async with client(app, "ops.example.test") as c:
        response = await c.post(OPERATOR_PATH, json={"idToken": CREDENTIAL})

    claims = decode_operator_token(response.json()["token"], SIGNING, NOW)
    (entry,) = platform.entries
    assert (entry.action, entry.principal_ref) == ("operator-signed-in", claims.sub)
    assert (entry.tenant_id, entry.access_id, entry.at) == (None, None, NOW)
    assert entry.snapshot == {"role": "support"}
    text = repr(entry)
    for secret in (CREDENTIAL, D_OPERATOR, OID, response.json()["token"]):
        assert secret not in text


async def test_a_sign_in_the_platform_chain_cannot_record_gets_no_token() -> None:
    platform = _Platform(fail=True)
    app = _operator_app(platform)

    async with client(app, "ops.example.test") as c:
        response = await c.post(OPERATOR_PATH, json={"idToken": CREDENTIAL})

    assert response.status_code == 503
    assert response.headers["retry-after"]
    assert "token" not in response.text.lower().replace("unavailable", "")
    assert platform.entries == []


async def test_a_refused_operator_exchange_writes_nothing_to_the_platform_chain() -> None:
    platform = _Platform()
    verifier = accepting(_identity(D_A, (), ("DIUCS.Support",)), Audience.OPERATOR)
    app, _ = build(verifier=verifier)
    app.state.token_exchange = ExchangeDeps(
        verifier=verifier, operator_directory_id=D_OPERATOR, platform_audit=platform
    )

    async with client(app) as c:
        response = await c.post(OPERATOR_PATH, json={"idToken": CREDENTIAL})

    assert response.status_code == 403 and platform.entries == []


async def test_a_process_with_no_platform_chain_still_issues_the_token() -> None:
    app = _operator_app(None)

    async with client(app, "ops.example.test") as c:
        response = await c.post(OPERATOR_PATH, json={"idToken": CREDENTIAL})

    assert response.status_code == 200


# ----------------------------------------------------------------------- logs


async def test_no_credential_token_or_id_reaches_a_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app, _ = build(verifier=accepting())

    with caplog.at_level(logging.DEBUG):
        async with client(app) as c:
            ok = await staff(c)
            await staff(c, "not-the-credential")
            await c.post(DEVICE_PATH, json={}, headers=device_headers())

    for text in (
        CREDENTIAL,
        ok.json()["token"],
        D_A,
        OID,
        G_LEAD,
        DEVICE_TOKEN,
        "not-the-credential",
    ):
        assert text not in caplog.text


def test_the_signing_secret_name_is_the_one_the_edge_reads() -> None:
    assert SIGNING_SECRET == BFF_SECRET_NAME
