"""The FHIR body-type check does not apply to the link pages (L01): renewing a link is a POST with
no body, and the link pages answer in their own fixed bodies, never an OperationOutcome. Every
other POST or PUT whose body is not JSON is still refused."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from diucs.adapters.inbound.fhir_rest.errors import BodyTypeMiddleware


async def _ok(request: Request) -> PlainTextResponse:
    return PlainTextResponse("reached")


def _client(*paths: str) -> AsyncClient:
    app = Starlette(routes=[Route(path, _ok, methods=["POST", "PUT"]) for path in paths])
    app.add_middleware(BodyTypeMiddleware)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize("path", ["/links/abc", "/links/abc/renew"])
async def test_a_post_with_no_body_or_a_form_to_a_link_path_reaches_the_route(path: str) -> None:
    async with _client("/links/abc", "/links/abc/renew") as client:
        bare = await client.post(path)
        form = await client.post(
            path, content="a=b", headers={"content-type": "application/x-www-form-urlencoded"}
        )

    assert (bare.status_code, bare.text) == (200, "reached")
    assert (form.status_code, form.text) == (200, "reached")


async def test_a_path_that_only_starts_like_the_link_prefix_is_not_exempt() -> None:
    async with _client("/linksx/a", "/fhir/Task") as client:
        like = await client.post("/linksx/a")
        other = await client.post("/fhir/Task")

    assert (like.status_code, other.status_code) == (415, 415)
