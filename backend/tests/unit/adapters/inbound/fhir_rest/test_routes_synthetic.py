"""The synthetic test hook (O09, TEN-G04) without a server: off by default, the bearer token, the
tenant from the edge and never from the request, and nothing secret in a response.

The issuer is a recording double of the use case that issues the link. The use case itself runs
against Neo4j in the integration tests, which are not part of this build. All values are synthetic.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.routes_synthetic import SyntheticHook
from diucs.application.tenancy import current_tenant

TOKEN = "test-only-hook-token-0123456789"
TENANT = "synthetic"
LINK = "https://diucs.example/l/SyntheticLinkTokenAbcdefghijk"
PATH = "/test/synthetic/prompt"


class RecordingIssuer:
    def __init__(self) -> None:
        self.tenants: list[str] = []

    async def issue(self) -> str:
        self.tenants.append(current_tenant())
        return LINK


def _app(hook: SyntheticHook | None) -> TestClient:
    container = SimpleNamespace(clock=None, uow_factory=None, ids=None)
    return TestClient(create_app(container, synthetic=hook))  # type: ignore[arg-type]


def _hook(
    *, enabled: bool = True, token: str | None = TOKEN
) -> tuple[SyntheticHook, RecordingIssuer]:
    issuer = RecordingIssuer()
    return SyntheticHook(enabled=enabled, token=token, tenant_id=TENANT, issuer=issuer), issuer


def _post(client: TestClient, authorization: str | None, body: object = None) -> Response:
    headers = {"Content-Type": "application/json"}
    if authorization is not None:
        headers["Authorization"] = authorization
    return client.post(PATH, headers=headers, json={} if body is None else body)


# -- off by default ----------------------------------------------------------------------------


def test_with_no_hook_configured_every_call_is_a_404() -> None:
    response = _post(_app(None), f"Bearer {TOKEN}")
    assert response.status_code == 404


def test_with_the_setting_off_the_right_token_is_still_a_404_and_nothing_is_issued() -> None:
    hook, issuer = _hook(enabled=False)
    response = _post(_app(hook), f"Bearer {TOKEN}")
    assert response.status_code == 404
    assert issuer.tenants == []


def test_with_no_token_configured_nothing_is_accepted() -> None:
    hook, issuer = _hook(token=None)
    response = _post(_app(hook), "Bearer ")
    assert response.status_code == 404
    assert issuer.tenants == []


# -- the bearer token --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Bearer",
        "Bearer wrong-token",
        f"Bearer {TOKEN}x",
        f"Bearer {TOKEN[:-1]}",
        f"Basic {TOKEN}",
        f"Token {TOKEN}",
        TOKEN,
    ],
)
def test_the_wrong_or_missing_token_is_a_404_with_the_same_body(authorization: str | None) -> None:
    hook, issuer = _hook()
    response = _post(_app(hook), authorization)
    assert response.status_code == 404
    assert response.json() == {"error": "not found"}
    assert issuer.tenants == []
    assert TOKEN not in response.text


def test_the_scheme_word_is_not_case_sensitive_but_the_token_is() -> None:
    hook, issuer = _hook()
    client = _app(hook)
    assert _post(client, f"bearer {TOKEN}").status_code == 201
    assert _post(client, f"Bearer {TOKEN.upper()}").status_code == 404
    assert issuer.tenants == [TENANT]


# -- the right token ---------------------------------------------------------------------------


def test_the_right_token_issues_a_link_with_201() -> None:
    hook, issuer = _hook()
    response = _post(_app(hook), f"Bearer {TOKEN}")
    assert response.status_code == 201
    assert response.json() == {"link": LINK}
    assert issuer.tenants == [TENANT]


def test_a_tenant_named_in_the_request_is_ignored_and_the_edge_tenant_is_used() -> None:
    hook, issuer = _hook()
    body = {"tenant_id": "tenant-b", "tenant": "tenant-b", "service": "other"}
    response = _post(_app(hook), f"Bearer {TOKEN}", body=body)
    assert response.status_code == 201
    assert issuer.tenants == [TENANT]


def test_a_tenant_that_is_not_a_valid_tenant_id_is_refused_when_the_hook_is_built() -> None:
    with pytest.raises(ValueError):
        SyntheticHook(enabled=True, token=TOKEN, tenant_id="net-bad", issuer=RecordingIssuer())


def test_the_token_is_not_shown_by_the_hook_object() -> None:
    hook, _ = _hook()
    assert TOKEN not in repr(hook)
