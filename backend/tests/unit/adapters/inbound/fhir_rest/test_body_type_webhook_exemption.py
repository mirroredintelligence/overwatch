"""The FHIR body-type check does not apply to the Twilio webhook (I07): Twilio posts a form, which
the check would answer with 415. Every other POST or PUT body that is not JSON is still refused."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from diucs.adapters.inbound.fhir_rest.errors import BodyTypeMiddleware


async def _ok(request: Request) -> PlainTextResponse:
    return PlainTextResponse("reached")


def _client() -> AsyncClient:
    paths = ["/webhooks/sms/twilio", "/webhooks/sms/twilio/status", "/fhir/Task", "/other"]
    app = Starlette(routes=[Route(path, _ok, methods=["POST", "PUT"]) for path in paths])
    app.add_middleware(BodyTypeMiddleware)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


FORM = {"content-type": "application/x-www-form-urlencoded"}


@pytest.mark.parametrize("path", ["/webhooks/sms/twilio", "/webhooks/sms/twilio/status"])
async def test_a_form_post_to_a_webhook_path_reaches_the_route(path: str) -> None:
    async with _client() as client:
        response = await client.post(path, content="a=b", headers=FORM)
    assert response.status_code == 200
    assert response.text == "reached"


@pytest.mark.parametrize("path", ["/fhir/Task", "/other"])
@pytest.mark.parametrize("method", ["post", "put"])
async def test_a_form_body_anywhere_else_is_still_415(path: str, method: str) -> None:
    async with _client() as client:
        response = await client.request(method.upper(), path, content="a=b", headers=FORM)
    assert response.status_code == 415


async def test_a_path_that_only_starts_like_the_webhook_prefix_is_not_exempt() -> None:
    app = Starlette(routes=[Route("/webhooksx/a", _ok, methods=["POST"])])
    app.add_middleware(BodyTypeMiddleware)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhooksx/a", content="a=b", headers=FORM)
    assert response.status_code == 415
