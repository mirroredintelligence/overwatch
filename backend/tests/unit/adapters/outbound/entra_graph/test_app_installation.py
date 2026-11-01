"""The Graph check of the staff app in an organisation's directory (DEC-1316 item 5).

No network: every call goes to an httpx MockTransport that stands in for the token endpoint and
Graph. Proves the calls made (token in the organisation's own directory, then the service principal
by app id, then its role assignments and the roles' names), the answers, and that no secret, token
or body is logged or put in an error.
"""

import logging
from collections.abc import Callable
from urllib.parse import parse_qs

import httpx
import pytest

from overwatch.adapters.outbound.entra_graph.app_installation import (
    CLIENT_SECRET_NAME,
    GraphAppInstallationCheck,
)
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.application.ports.outbound.admin_consent import GraphUnavailable

DIRECTORY = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"
CLIENT = "7fb43bde-6a6d-4aed-9cac-9118de48ab52"
CLIENT_SECRET = b"client-secret-canary-0123456789"
BEARER = "app-token-canary-abcdef"
SP_ID = "11111111-2222-3333-4444-555555555555"
GRAPH_ID = "99999999-8888-7777-6666-555555555555"
ROLE_GROUP = "aaaaaaaa-0000-0000-0000-000000000001"
ROLE_USER = "aaaaaaaa-0000-0000-0000-000000000002"
ROLE_OTHER = "aaaaaaaa-0000-0000-0000-000000000003"

Handler = Callable[[httpx.Request], httpx.Response]


def _graph(
    *,
    assigned: tuple[str, ...] = (ROLE_GROUP, ROLE_USER),
    principal_status: int = 200,
    token_response: httpx.Response | None = None,
) -> tuple[Handler, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url)
        if "oauth2/v2.0/token" in url:
            return token_response or httpx.Response(200, json={"access_token": BEARER})
        if request.headers.get("authorization") != f"Bearer {BEARER}":
            return httpx.Response(401, json={})
        if "servicePrincipals(appId=" in url:
            if principal_status != 200:
                return httpx.Response(principal_status, json={"error": {"code": "x"}})
            return httpx.Response(200, json={"id": SP_ID})
        if url.endswith("/appRoleAssignments"):
            return httpx.Response(
                200,
                json={"value": [{"appRoleId": role, "resourceId": GRAPH_ID} for role in assigned]},
            )
        if f"/servicePrincipals/{GRAPH_ID}" in url:
            return httpx.Response(
                200,
                json={
                    "appRoles": [
                        {"id": ROLE_GROUP, "value": "Group.ReadWrite.All"},
                        {"id": ROLE_USER, "value": "User.Read.All"},
                        {"id": ROLE_OTHER, "value": "Mail.Send"},
                    ]
                },
            )
        return httpx.Response(404, json={})

    return handler, seen


def _check(handler: Handler, secret: bytes | None = CLIENT_SECRET) -> GraphAppInstallationCheck:
    store = FixedSecretStore({} if secret is None else {CLIENT_SECRET_NAME: secret})
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GraphAppInstallationCheck(http, store, CLIENT)


async def test_an_installed_app_reports_the_permissions_it_holds_by_name() -> None:
    handler, seen = _graph()
    found = await _check(handler).check(DIRECTORY)

    assert found.installed
    assert found.granted_roles == {"Group.ReadWrite.All", "User.Read.All"}
    token_request = seen[0]
    assert str(token_request.url) == (
        f"https://login.microsoftonline.com/{DIRECTORY}/oauth2/v2.0/token"
    )
    form = parse_qs(token_request.content.decode())
    assert form["grant_type"] == ["client_credentials"]
    assert form["scope"] == ["https://graph.microsoft.com/.default"]
    assert form["client_id"] == [CLIENT]
    assert f"servicePrincipals(appId='{CLIENT}')" in str(seen[1].url)
    assert str(seen[2].url).endswith(f"/servicePrincipals/{SP_ID}/appRoleAssignments")
    assert all(r.url.host in ("login.microsoftonline.com", "graph.microsoft.com") for r in seen)


async def test_a_role_that_was_not_granted_is_not_reported() -> None:
    handler, _ = _graph(assigned=(ROLE_USER,))
    found = await _check(handler).check(DIRECTORY)
    assert found.installed and found.granted_roles == {"User.Read.All"}


async def test_a_directory_that_refuses_the_app_token_for_want_of_it_means_not_installed() -> None:
    refused = httpx.Response(
        400,
        json={"error": "unauthorized_client", "error_codes": [700016], "error_description": "x"},
    )
    handler, seen = _graph(token_response=refused)
    found = await _check(handler).check(DIRECTORY)

    assert not found.installed and found.reason
    assert len(seen) == 1  # no Graph call without a token


async def test_no_service_principal_in_the_directory_means_not_installed() -> None:
    handler, _ = _graph(principal_status=404)
    found = await _check(handler).check(DIRECTORY)
    assert not found.installed and found.granted_roles == frozenset()


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_any_other_refusal_of_the_token_is_unavailable_not_not_installed(status: int) -> None:
    handler, _ = _graph(token_response=httpx.Response(status, json={"error": "x"}))
    with pytest.raises(GraphUnavailable):
        await _check(handler).check(DIRECTORY)


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_a_graph_failure_is_unavailable(status: int) -> None:
    handler, _ = _graph(principal_status=status)
    with pytest.raises(GraphUnavailable):
        await _check(handler).check(DIRECTORY)


async def test_a_body_that_is_not_what_graph_sends_is_unavailable() -> None:
    handler, _ = _graph(token_response=httpx.Response(200, text="<html>"))
    with pytest.raises(GraphUnavailable):
        await _check(handler).check(DIRECTORY)


async def test_a_transport_failure_is_unavailable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(GraphUnavailable):
        await _check(boom).check(DIRECTORY)


async def test_a_missing_client_secret_is_unavailable_and_nothing_is_sent() -> None:
    handler, seen = _graph()
    with pytest.raises(GraphUnavailable) as refused:
        await _check(handler, secret=None).check(DIRECTORY)
    assert seen == [] and CLIENT_SECRET_NAME not in str(refused.value)


async def test_the_secret_the_token_and_the_bodies_are_never_logged_or_in_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler, _ = _graph(principal_status=500)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(GraphUnavailable) as refused:
        await _check(handler).check(DIRECTORY)

    shown = caplog.text + str(refused.value)
    for canary in (CLIENT_SECRET.decode(), BEARER, DIRECTORY):
        assert canary not in shown


async def test_a_next_link_off_graph_is_never_followed() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url)
        if "oauth2/v2.0/token" in url:
            return httpx.Response(200, json={"access_token": BEARER})
        if "servicePrincipals(appId=" in url:
            return httpx.Response(200, json={"id": SP_ID})
        return httpx.Response(
            200, json={"value": [], "@odata.nextLink": "https://evil.example/steal"}
        )

    found = await _check(handler).check(DIRECTORY)
    assert found.installed and all(r.url.host != "evil.example" for r in seen)
