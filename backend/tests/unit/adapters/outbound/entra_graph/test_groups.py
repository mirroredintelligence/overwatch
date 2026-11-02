"""The Graph adapter of the organisation's groups (DEC-1317).

No network: every call goes to an httpx MockTransport standing in for the token endpoint and Graph.
Proves the calls made (an application token in the organisation's own directory, the OData
filters, group creation as a security group with mail off, the app role assignment, member add and
remove), the idempotent answers, the refusals (more than one match, a bad id), and that no secret,
token, address or body is logged or put in an error.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from overwatch.adapters.outbound.entra_graph.groups import (
    CLIENT_SECRET_NAME,
    GraphEntraGroups,
)
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.application.ports.outbound.admin_consent import GraphUnavailable
from overwatch.application.ports.outbound.entra_groups import GroupMissing

DIRECTORY = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"
CLIENT = "7fb43bde-6a6d-4aed-9cac-9118de48ab52"
CLIENT_SECRET = b"client-secret-canary-0123456789"
BEARER = "app-token-canary-abcdef"
SP = "11111111-2222-4333-8444-555555555555"
GROUP = "aaaaaaaa-0000-4000-8000-000000000001"
USER = "bbbbbbbb-0000-4000-8000-000000000002"
ROLE = "52475a88-b5cd-4e30-9090-316d1c29672f"
ADDRESS = "jane.member@example-trust.test"

Handler = Callable[[httpx.Request], httpx.Response]


def _adapter(
    handler: Handler, secret: bytes | None = CLIENT_SECRET, sleep: Any = None
) -> tuple[GraphEntraGroups, list]:
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "oauth2/v2.0/token" in str(request.url):
            return httpx.Response(200, json={"access_token": BEARER, "expires_in": 3600})
        if request.headers.get("authorization") != f"Bearer {BEARER}":
            return httpx.Response(401, json={})
        return handler(request)

    store = FixedSecretStore({} if secret is None else {CLIENT_SECRET_NAME: secret})
    http = httpx.AsyncClient(transport=httpx.MockTransport(recording))
    extra = {} if sleep is None else {"sleep": sleep}
    return GraphEntraGroups(http, store, CLIENT, **extra), seen


def _graph_calls(seen: list[httpx.Request]) -> list[httpx.Request]:
    return [r for r in seen if r.url.host == "graph.microsoft.com"]


async def test_a_group_is_found_by_its_exact_name_with_an_application_token_for_the_directory() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"value": [{"id": GROUP.upper(), "displayName": "F81044_overwatch_lead"}]}
        )

    adapter, seen = _adapter(handler)
    assert await adapter.find_group(DIRECTORY, "F81044_overwatch_lead") == GROUP

    token = seen[0]
    assert str(token.url) == f"https://login.microsoftonline.com/{DIRECTORY}/oauth2/v2.0/token"
    assert b"client_credentials" in token.content and b"graph.microsoft.com%2F.default" in (
        token.content
    )
    [call] = _graph_calls(seen)
    assert call.url.params["$filter"] == "displayName eq 'F81044_overwatch_lead'"


async def test_no_group_of_that_name_is_none_and_a_near_match_does_not_count() -> None:
    adapter, _ = _adapter(
        lambda r: httpx.Response(
            200, json={"value": [{"id": GROUP, "displayName": "f81044_overwatch_LEAD"}]}
        )
    )
    assert await adapter.find_group(DIRECTORY, "F81044_overwatch_lead") is None


async def test_two_groups_with_the_name_are_refused_not_picked_between() -> None:
    adapter, _ = _adapter(
        lambda r: httpx.Response(
            200,
            json={
                "value": [
                    {"id": GROUP, "displayName": "F81044_overwatch_lead"},
                    {"id": USER, "displayName": "F81044_overwatch_lead"},
                ]
            },
        )
    )
    with pytest.raises(GraphUnavailable):
        await adapter.find_group(DIRECTORY, "F81044_overwatch_lead")


@pytest.mark.parametrize("name", ["", "a b", "x'y", "x or 1 eq 1", "../groups", "x" * 130])
async def test_a_name_we_would_never_make_never_reaches_a_url(name: str) -> None:
    adapter, seen = _adapter(lambda r: httpx.Response(200, json={"value": []}))
    with pytest.raises(GraphUnavailable):
        await adapter.find_group(DIRECTORY, name)
    with pytest.raises(GraphUnavailable):
        await adapter.create_group(DIRECTORY, name, "x")
    assert _graph_calls(seen) == []


async def test_a_group_is_made_as_a_security_group_with_mail_off() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": GROUP})

    adapter, seen = _adapter(handler)
    assert (
        await adapter.create_group(DIRECTORY, "F81044_overwatch_lead", "Overwatch: lead") == GROUP
    )

    [request] = _graph_calls(seen)
    assert (
        request.method == "POST" and str(request.url) == "https://graph.microsoft.com/v1.0/groups"
    )
    assert bodies == [
        {
            "displayName": "F81044_overwatch_lead",
            "description": "Overwatch: lead",
            "mailEnabled": False,
            "mailNickname": "F81044_overwatch_lead",
            "securityEnabled": True,
        }
    ]


async def test_the_role_assignment_is_posted_to_the_service_principals_app_role_assigned_to() -> (
    None
):
    posted: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"value": []})
        posted.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "x"})

    adapter, seen = _adapter(handler)
    assert await adapter.assign_app_role(DIRECTORY, SP, GROUP, ROLE) is True

    post = _graph_calls(seen)[-1]
    assert post.method == "POST"
    assert (
        str(post.url)
        == f"https://graph.microsoft.com/v1.0/servicePrincipals/{SP}/appRoleAssignedTo"
    )
    assert posted == [{"principalId": GROUP, "resourceId": SP, "appRoleId": ROLE}]


def _bad_request() -> httpx.Response:
    return httpx.Response(400, json={"error": {"code": "Request_BadRequest", "message": "x"}})


async def test_a_new_group_not_yet_visible_is_assigned_after_waiting_and_trying_again() -> None:
    # Graph answers 400 Request_BadRequest to an assignment for a group made a moment ago (seen on
    # the pilot): the assignment waits and tries again, and the third answer is the success.
    posts: list[int] = []
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"value": []})
        posts.append(1)
        return _bad_request() if len(posts) < 3 else httpx.Response(201, json={"id": "x"})

    adapter, _ = _adapter(handler, sleep=sleep)
    assert await adapter.assign_app_role(DIRECTORY, SP, GROUP, ROLE) is True
    assert len(posts) == 3 and sleeps == [5.0, 5.0]


async def test_an_assignment_that_is_always_refused_gives_up_after_six_tries() -> None:
    posts: list[int] = []
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"value": []})
        posts.append(1)
        return _bad_request()

    adapter, _ = _adapter(handler, sleep=sleep)
    with pytest.raises(GraphUnavailable):
        await adapter.assign_app_role(DIRECTORY, SP, GROUP, ROLE)
    assert len(posts) == 6 and len(sleeps) == 5


async def test_any_other_refusal_of_an_assignment_is_not_retried() -> None:
    posts: list[int] = []
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"value": []})
        posts.append(1)
        return httpx.Response(403, json={"error": {"code": "Authorization_RequestDenied"}})

    adapter, _ = _adapter(handler, sleep=sleep)
    with pytest.raises(GraphUnavailable):
        await adapter.assign_app_role(DIRECTORY, SP, GROUP, ROLE)
    assert len(posts) == 1 and sleeps == []


async def test_a_role_assignment_that_exists_is_left_and_nothing_is_posted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200, json={"value": [{"principalId": GROUP.upper(), "appRoleId": ROLE}]}
        )

    adapter, seen = _adapter(handler)
    assert await adapter.assign_app_role(DIRECTORY, SP, GROUP, ROLE) is False
    assert all(r.method == "GET" for r in _graph_calls(seen))


async def test_a_user_is_found_by_mail_or_user_principal_name_with_the_address_quoted() -> None:
    adapter, seen = _adapter(lambda r: httpx.Response(200, json={"value": [{"id": USER}]}))
    assert await adapter.find_user(DIRECTORY, "o'brien@example-trust.test") == USER

    [call] = _graph_calls(seen)
    assert call.url.params["$filter"] == (
        "mail eq 'o''brien@example-trust.test' "
        "or userPrincipalName eq 'o''brien@example-trust.test'"
    )


async def test_a_user_who_is_not_found_is_none_and_two_users_are_refused() -> None:
    none, _ = _adapter(lambda r: httpx.Response(200, json={"value": []}))
    assert await none.find_user(DIRECTORY, ADDRESS) is None
    two, _ = _adapter(lambda r: httpx.Response(200, json={"value": [{"id": USER}, {"id": GROUP}]}))
    with pytest.raises(GraphUnavailable):
        await two.find_user(DIRECTORY, ADDRESS)


@pytest.mark.parametrize("address", ["", "a b@x", "x'); drop@x", "no-at-sign", "a@b c"])
async def test_something_that_is_not_an_address_never_reaches_a_url(address: str) -> None:
    adapter, seen = _adapter(lambda r: httpx.Response(200, json={"value": []}))
    with pytest.raises(GraphUnavailable):
        await adapter.find_user(DIRECTORY, address)
    assert _graph_calls(seen) == []


async def test_a_member_is_added_by_reference_and_already_a_member_is_not_an_error() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(204)
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "Request_BadRequest",
                    "message": "One or more added object references already exist for the "
                    "following modified properties: 'members'.",
                }
            },
        )

    adapter, seen = _adapter(handler)
    assert await adapter.add_member(DIRECTORY, GROUP, USER) is True
    assert await adapter.add_member(DIRECTORY, GROUP, USER) is False
    first = _graph_calls(seen)[0]
    assert str(first.url) == f"https://graph.microsoft.com/v1.0/groups/{GROUP}/members/$ref"
    assert bodies[0] == {"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{USER}"}


async def test_adding_to_a_group_that_is_gone_is_group_missing() -> None:
    adapter, _ = _adapter(lambda r: httpx.Response(404, json={"error": {"code": "x"}}))
    with pytest.raises(GroupMissing):
        await adapter.add_member(DIRECTORY, GROUP, USER)


async def test_a_member_is_removed_and_one_who_was_not_in_is_false_when_the_group_exists() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(
                204 if "bbbbbbbb-0000-4000-8000-000000000002" in str(request.url) else 404
            )
        return httpx.Response(200, json={"displayName": "F81044_overwatch_lead"})

    adapter, seen = _adapter(handler)
    assert await adapter.remove_member(DIRECTORY, GROUP, USER) is True
    assert await adapter.remove_member(DIRECTORY, GROUP, GROUP) is False
    assert str(_graph_calls(seen)[0].url) == (
        f"https://graph.microsoft.com/v1.0/groups/{GROUP}/members/{USER}/$ref"
    )


async def test_removing_from_a_group_that_is_gone_is_group_missing() -> None:
    adapter, _ = _adapter(lambda r: httpx.Response(404, json={}))
    with pytest.raises(GroupMissing):
        await adapter.remove_member(DIRECTORY, GROUP, USER)


async def test_the_members_of_a_group_are_read_across_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "page=2" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "value": [{"id": GROUP, "displayName": "Sam", "userPrincipalName": "s@x.test"}]
                },
            )
        return httpx.Response(
            200,
            json={
                "value": [{"id": USER, "displayName": "Jane", "mail": ADDRESS}],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/groups/x/members?page=2",
            },
        )

    adapter, _ = _adapter(handler)
    members = await adapter.members(DIRECTORY, GROUP)
    assert [(m.object_id, m.display_name, m.mail) for m in members] == [
        (USER, "Jane", ADDRESS),
        (GROUP, "Sam", "s@x.test"),
    ]


async def test_a_next_link_that_leaves_graph_is_not_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"value": [], "@odata.nextLink": "https://evil.example/steal"}
        )

    adapter, seen = _adapter(handler)
    assert await adapter.members(DIRECTORY, GROUP) == ()
    assert all(r.url.host != "evil.example" for r in seen)


async def test_the_group_name_is_the_directorys_own_and_a_missing_group_says_so() -> None:
    ok, _ = _adapter(lambda r: httpx.Response(200, json={"displayName": "F81044_overwatch_lead"}))
    assert await ok.group_name(DIRECTORY, GROUP) == "F81044_overwatch_lead"
    gone, _ = _adapter(lambda r: httpx.Response(404, json={}))
    with pytest.raises(GroupMissing):
        await gone.group_name(DIRECTORY, GROUP)


@pytest.mark.parametrize("bad", ["", "x", "../x", f"{GROUP}/members", "g" * 36])
async def test_an_id_that_is_not_a_guid_never_reaches_a_url_path(bad: str) -> None:
    adapter, seen = _adapter(lambda r: httpx.Response(200, json={}))
    with pytest.raises(GraphUnavailable):
        await adapter.group_name(DIRECTORY, bad)
    with pytest.raises(GraphUnavailable):
        await adapter.add_member(DIRECTORY, GROUP, bad)
    assert _graph_calls(seen) == []


async def test_the_token_is_kept_for_its_life_not_asked_for_on_every_call() -> None:
    adapter, seen = _adapter(lambda r: httpx.Response(200, json={"value": []}))
    await adapter.find_user(DIRECTORY, ADDRESS)
    await adapter.find_user(DIRECTORY, ADDRESS)
    assert sum("oauth2/v2.0/token" in str(r.url) for r in seen) == 1


async def test_a_missing_client_secret_is_graph_unavailable_and_no_call_is_made() -> None:
    adapter, seen = _adapter(lambda r: httpx.Response(200, json={}), secret=None)
    with pytest.raises(GraphUnavailable):
        await adapter.find_user(DIRECTORY, ADDRESS)
    assert seen == []


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
async def test_a_refusal_or_a_failure_is_graph_unavailable_with_fixed_words(status: int) -> None:
    adapter, _ = _adapter(
        lambda r: httpx.Response(status, json={"error": {"message": "secret body"}})
    )
    with pytest.raises(GraphUnavailable) as failed:
        await adapter.find_user(DIRECTORY, ADDRESS)
    assert "secret body" not in str(failed.value)


async def test_a_body_that_is_not_what_graph_sends_is_graph_unavailable() -> None:
    adapter, _ = _adapter(lambda r: httpx.Response(200, text="<html>nope</html>"))
    with pytest.raises(GraphUnavailable):
        await adapter.find_user(DIRECTORY, ADDRESS)
    odd, _ = _adapter(lambda r: httpx.Response(200, json={"value": "no"}))
    with pytest.raises(GraphUnavailable):
        await odd.find_user(DIRECTORY, ADDRESS)


async def test_an_unreachable_directory_is_graph_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    adapter, _ = _adapter(handler)
    with pytest.raises(GraphUnavailable):
        await adapter.find_user(DIRECTORY, ADDRESS)


async def test_a_refusal_logs_what_was_asked_and_graphs_error_code_but_no_message_or_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"code": "Request_BadRequest", "message": "Jane Member is not welcome"}},
            headers={"request-id": "cccccccc-0000-4000-8000-000000000003"},
        )

    caplog.set_level(logging.WARNING)
    adapter, _ = _adapter(handler)
    with pytest.raises(GraphUnavailable):
        await adapter.create_group(DIRECTORY, "F81044_overwatch_lead", "Overwatch: lead")

    text = caplog.text
    assert "graph refused: POST /groups status 400 code Request_BadRequest" in text
    assert "request-id cccccccc-0000-4000-8000-000000000003" in text
    assert "Jane Member" not in text and BEARER not in text


async def test_no_secret_token_address_or_body_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    adapter, _ = _adapter(lambda r: httpx.Response(500, json={"error": {"message": "body canary"}}))
    with pytest.raises(GraphUnavailable):
        await adapter.find_user(DIRECTORY, ADDRESS)
    ok, _ = _adapter(lambda r: httpx.Response(200, json={"value": [{"id": USER}]}))
    await ok.find_user(DIRECTORY, ADDRESS)

    text = caplog.text
    for canary in (CLIENT_SECRET.decode(), BEARER, ADDRESS, "body canary", DIRECTORY):
        assert canary not in text
