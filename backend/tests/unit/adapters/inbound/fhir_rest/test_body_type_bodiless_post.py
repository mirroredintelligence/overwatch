"""The body-type check judges the Content-Type, not the body (WB4). A POST with no body and no
Content-Type is refused with 415; the same POST that names its type reaches the route. The front
end relies on this: its bodiless POSTs (remind, resend, switch-to-text) must carry the type, and its
test harness models this rule (frontend/test/backend-edge.ts, which reads this source)."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from diucs.adapters.inbound.fhir_rest.errors import BodyTypeMiddleware


async def _ok(request: Request) -> PlainTextResponse:
    return PlainTextResponse(f"reached with {len(await request.body())} bytes")


def _client() -> AsyncClient:
    app = Starlette(routes=[Route("/lead/services/s1/remind", _ok, methods=["POST", "PUT"])])
    app.add_middleware(BodyTypeMiddleware)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize("method", ["POST", "PUT"])
async def test_a_bodiless_request_with_no_content_type_is_a_415(method: str) -> None:
    async with _client() as client:
        response = await client.request(method, "/lead/services/s1/remind")

    assert response.status_code == 415


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "application/fhir+json", "application/fhir+json; fhirVersion=4.3"],
)
async def test_a_bodiless_request_that_names_a_json_type_reaches_the_route(
    content_type: str,
) -> None:
    async with _client() as client:
        response = await client.post(
            "/lead/services/s1/remind", headers={"content-type": content_type}
        )

    assert (response.status_code, response.text) == (200, "reached with 0 bytes")
