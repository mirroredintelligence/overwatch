"""The lead's wall screen list and revoke over HTTP, and the check that ends a revoked screen's
token at once (W9I, TEN-072, TEN-043), through the app on recording stand-ins.

Rules: only the shift lead reaches the list and the revoke (the role matrix: every other role is the
non-revealing 404, the platform operator the edge's 401); no body holds a token, a token hash or a
pairing secret; the revoke needs an Idempotency-Key; a screen of another tenant is a 404; a revoked
or unknown wall screen is refused by every route a wall may read (401, the answer a lapsed token
gets), and a live one is let through and marked seen at most once in the refresh window. Synthetic
values only.
"""

from datetime import timedelta
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import SCREEN_SEEN_EVERY, require_role
from diucs.application.actor import Actor
from diucs.domain.codes import Role
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from tests.support.route_unit import KEY, assert_role_matrix, route_client
from tests.support.screen_stubs import ScreenDevices
from tests.support.w7b_rig import HOST, LEAD, NOW, Rig, bearer

pytestmark = pytest.mark.asyncio(loop_scope="session")

LEAD_AUTH = bearer(Role.LEAD, LEAD)
HASH = "c" * 64
SECRET_WORDS = ("tokenHash", "token_hash", HASH, "screenSecret", "deviceToken")


def _screen(device_id: str, name: str, **changes: Any) -> Device:
    values: dict[str, Any] = {
        "id": device_id,
        "status": DeviceStatus.ACTIVE,
        "name": name,
        "location": "Level 2",
        "device_type": DeviceType.WALL_DISPLAY,
        "token_hash": HASH,
        "board_scope": BoardScope.TENANT,
        "paired_at": NOW - timedelta(days=3),
        "last_seen_at": NOW - timedelta(seconds=40),
    }
    values.update(changes)
    return Device(**values)


def _world() -> tuple[Rig, ScreenDevices]:
    rig = Rig()
    devices = ScreenDevices(rig.units.writes, rig.units.calls)
    rig.units.devices = devices
    devices.screens["s-1"] = _screen("s-1", "Ward 4 corridor")
    devices.screens["s-2"] = _screen(
        "s-2",
        "Day room",
        status=DeviceStatus.PAIRED_UNCLAIMED,
        token_hash=None,
        last_seen_at=None,
        paired_at=NOW - timedelta(minutes=1),
        location=None,
    )
    return rig, devices


def _http(rig: Rig) -> Any:
    from tests.support.w7b_rig import client

    return client(rig)


# ------------------------------------------------------------------------------- the list


async def test_the_list_gives_each_screen_and_no_secret() -> None:
    rig, _ = _world()
    async with _http(rig) as http:
        response = await http.get("/screens", headers=LEAD_AUTH)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["scope"] == "tenant"
    assert body["asOf"] == "2026-10-30T10:00:00Z"
    assert body["screens"] == [
        {
            "deviceId": "s-2",
            "name": "Day room",
            "location": None,
            "status": "waiting",
            "boardScope": "tenant",
            "pairedAt": "2026-10-30T09:59:00Z",
            "lastSeenAt": None,
            "revokedAt": None,
        },
        {
            "deviceId": "s-1",
            "name": "Ward 4 corridor",
            "location": "Level 2",
            "status": "online",
            "boardScope": "tenant",
            "pairedAt": "2026-10-27T10:00:00Z",
            "lastSeenAt": "2026-10-30T09:59:20Z",
            "revokedAt": None,
        },
    ]
    for word in SECRET_WORDS:
        assert word not in response.text


async def test_an_empty_tenant_gets_an_empty_list_not_a_missing_one() -> None:
    rig, devices = _world()
    devices.screens.clear()
    async with _http(rig) as http:
        body = (await http.get("/screens", headers=LEAD_AUTH)).json()
    assert body["screens"] == []


async def test_the_role_matrix_of_the_list_is_the_shift_lead_alone() -> None:
    async with route_client() as client:
        await assert_role_matrix(client, "GET", "/screens", frozenset({Role.LEAD}))


# ------------------------------------------------------------------------------- the revoke


async def test_revoking_answers_the_new_state_and_ends_the_screen() -> None:
    rig, devices = _world()
    async with _http(rig) as http:
        response = await http.post("/screens/s-1/revoke", json={}, headers={**LEAD_AUTH, **KEY})

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "deviceId": "s-1",
        "status": "revoked",
        "revokedAt": "2026-10-30T10:00:00Z",
    }
    assert devices.screens["s-1"].status is DeviceStatus.REVOKED
    assert devices.screens["s-1"].token_hash is None
    assert len(rig.units.audit.entries) == 1
    for word in SECRET_WORDS:
        assert word not in response.text


async def test_the_same_key_twice_is_answered_again_and_audited_once() -> None:
    rig, _ = _world()
    async with _http(rig) as http:
        first = await http.post("/screens/s-1/revoke", json={}, headers={**LEAD_AUTH, **KEY})
        second = await http.post("/screens/s-1/revoke", json={}, headers={**LEAD_AUTH, **KEY})
    assert (first.status_code, second.status_code) == (200, 200)
    assert second.json() == first.json()
    assert len(rig.units.audit.entries) == 1


async def test_revoking_with_no_key_is_refused_and_changes_nothing() -> None:
    rig, devices = _world()
    async with _http(rig) as http:
        response = await http.post("/screens/s-1/revoke", json={}, headers=LEAD_AUTH)
    assert response.status_code == 400
    assert devices.screens["s-1"].status is DeviceStatus.ACTIVE


async def test_revoking_a_screen_the_tenant_does_not_hold_is_a_404_and_a_malformed_id_a_400() -> (
    None
):
    rig, _ = _world()
    async with _http(rig) as http:
        response = await http.post("/screens/nowhere/revoke", json={}, headers={**LEAD_AUTH, **KEY})
        malformed = await http.post(
            "/screens/bad id!/revoke", json={}, headers={**LEAD_AUTH, **KEY}
        )
    assert response.status_code == 404
    assert malformed.status_code == 400  # not an id at all: refused before any lookup
    assert rig.units.audit.entries == []


async def test_the_revoke_body_is_never_read() -> None:
    rig, devices = _world()
    async with _http(rig) as http:
        response = await http.post(
            "/screens/s-1/revoke",
            json={"tenant": "other", "deviceId": "s-2"},
            headers={**LEAD_AUTH, **KEY},
        )
    assert response.status_code == 200
    assert devices.screens["s-1"].status is DeviceStatus.REVOKED
    assert devices.screens["s-2"].status is DeviceStatus.PAIRED_UNCLAIMED


async def test_the_role_matrix_of_the_revoke_is_the_shift_lead_alone() -> None:
    async with route_client() as client:
        await assert_role_matrix(
            client, "POST", "/screens/s-1/revoke", frozenset({Role.LEAD}), body={}, headers=KEY
        )


# --------------------------------------------------- a revoked screen's token stops at once


def _probe_app(rig: Rig) -> Any:
    app = create_app(rig)  # type: ignore[arg-type]
    app.state.secrets = rig.secrets
    router = APIRouter()

    @router.get("/probe")
    async def probe(
        _actor: Annotated[Actor, Depends(require_role(Role.WALL, Role.LEAD))],
    ) -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    return app


def _probe_client(rig: Rig) -> Any:
    import httpx

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_probe_app(rig), raise_app_exceptions=False),
        base_url=f"http://{HOST}",
    )


def _wall(device_id: str) -> dict[str, str]:
    return bearer(Role.WALL, device_id, device=device_id)


async def test_a_live_screen_is_let_through_and_marked_seen() -> None:
    rig, devices = _world()
    devices.screens["s-1"] = _screen("s-1", "Ward", last_seen_at=None)
    async with _probe_client(rig) as http:
        response = await http.get("/probe", headers=_wall("s-1"))
    assert response.status_code == 200
    assert devices.screens["s-1"].last_seen_at == NOW


async def test_a_screen_seen_a_moment_ago_is_not_written_again() -> None:
    rig, devices = _world()
    recent = NOW - SCREEN_SEEN_EVERY + timedelta(seconds=1)
    devices.screens["s-1"] = _screen("s-1", "Ward", last_seen_at=recent)
    async with _probe_client(rig) as http:
        assert (await http.get("/probe", headers=_wall("s-1"))).status_code == 200
    assert devices.screens["s-1"].last_seen_at == recent
    assert "devices.seen" not in rig.units.writes.names


async def test_a_screen_not_seen_for_the_refresh_window_is_marked_seen_again() -> None:
    rig, devices = _world()
    devices.screens["s-1"] = _screen(
        "s-1", "Ward", last_seen_at=NOW - SCREEN_SEEN_EVERY - timedelta(seconds=1)
    )
    async with _probe_client(rig) as http:
        assert (await http.get("/probe", headers=_wall("s-1"))).status_code == 200
    assert devices.screens["s-1"].last_seen_at == NOW


@pytest.mark.parametrize(
    "changes",
    [
        {"status": DeviceStatus.REVOKED, "token_hash": None},
        {"status": DeviceStatus.PAIRED_UNCLAIMED, "token_hash": None},
    ],
)
async def test_a_screen_that_is_not_active_is_refused_with_the_401_of_a_lapsed_token(
    changes: dict[str, Any],
) -> None:
    rig, devices = _world()
    devices.screens["s-1"] = _screen("s-1", "Ward", **changes)
    async with _probe_client(rig) as http:
        response = await http.get("/probe", headers=_wall("s-1"))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert devices.screens["s-1"].last_seen_at == NOW - timedelta(seconds=40)


async def test_a_wall_token_for_a_screen_the_tenant_does_not_hold_is_refused() -> None:
    rig, _ = _world()
    async with _probe_client(rig) as http:
        response = await http.get("/probe", headers=_wall("someone-elses-screen"))
    assert response.status_code == 401


async def test_a_staff_token_is_not_checked_against_the_screens() -> None:
    rig, _ = _world()
    async with _probe_client(rig) as http:
        response = await http.get("/probe", headers=LEAD_AUTH)
    assert response.status_code == 200
    assert "devices.confirm_active" not in rig.units.calls


@pytest.mark.parametrize("path", ["/fhir/HealthcareService", "/fhir/HealthcareService/svc-a"])
async def test_the_service_reads_a_wall_may_make_check_the_screen_too(path: str) -> None:
    rig, devices = _world()
    devices.screens["s-1"] = _screen("s-1", "Ward", status=DeviceStatus.REVOKED, token_hash=None)
    async with _probe_client(rig) as http:
        response = await http.get(path, headers=_wall("s-1"))
    assert response.status_code == 401
