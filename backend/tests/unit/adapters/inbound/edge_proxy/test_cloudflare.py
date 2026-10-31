"""The trusted-proxy handling for Cloudflare (B1, deployment-plan item 5): the client address and the
original host are read from the edge's headers only when the request comes from Cloudflare, by its
published address ranges or by the origin secret Cloudflare adds. Every other request keeps its
socket peer and its own Host header, and the edge's headers never reach a route. Synthetic
addresses only (documentation ranges and Cloudflare's own published ranges)."""

import ipaddress
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from diucs.adapters.inbound.edge_proxy.cloudflare import (
    CLOUDFLARE_RANGES,
    EDGE_AUTH_HEADER,
    CloudflareEdge,
    CloudflareEdgeMiddleware,
    parse_ranges,
)

CLOUDFLARE_PEER = "173.245.48.10"  # inside 173.245.48.0/20
CLOUDFLARE_PEER_V6 = "2606:4700::1"  # inside 2606:4700::/32
OTHER_PEER = "203.0.113.9"  # documentation range, not Cloudflare
VISITOR = "198.51.100.77"
ORIGIN_SECRET = b"origin-secret-for-tests-0123456789"
HOST = "alpha.example.org"


async def _echo(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "client": None if request.client is None else request.client.host,
            "host": request.headers.get("host"),
            "headers": sorted(request.headers.keys()),
        }
    )


def _app(edge: CloudflareEdge) -> Starlette:
    app = Starlette(routes=[Route("/echo", _echo)])
    app.add_middleware(CloudflareEdgeMiddleware, edge=edge)
    return app


async def _get(
    edge: CloudflareEdge, peer: str, headers: dict[str, str], host: str = "internal:8000"
) -> dict[str, Any]:
    transport = ASGITransport(app=_app(edge), client=(peer, 4321))
    async with AsyncClient(transport=transport, base_url=f"http://{host}") as client:
        response = await client.get("/echo", headers=headers)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _edge(**kwargs: Any) -> CloudflareEdge:
    return CloudflareEdge(**kwargs)


async def test_a_request_from_a_cloudflare_range_takes_the_visitor_address() -> None:
    body = await _get(_edge(), CLOUDFLARE_PEER, {"CF-Connecting-IP": VISITOR})

    assert body["client"] == VISITOR


async def test_an_ipv6_cloudflare_peer_is_trusted_too() -> None:
    body = await _get(_edge(), CLOUDFLARE_PEER_V6, {"CF-Connecting-IP": VISITOR})

    assert body["client"] == VISITOR


async def test_a_request_from_another_peer_keeps_the_socket_address() -> None:
    body = await _get(_edge(), OTHER_PEER, {"CF-Connecting-IP": VISITOR})

    assert body["client"] == OTHER_PEER


async def test_a_forged_edge_header_from_another_peer_is_removed_before_the_route() -> None:
    forged = {
        "CF-Connecting-IP": VISITOR,
        "True-Client-IP": VISITOR,
        "X-Forwarded-For": VISITOR,
        "X-Forwarded-Host": "beta.example.org",
        "X-Forwarded-Proto": "https",
        "Forwarded": f"for={VISITOR}",
        "CF-Ray": "abc",
        EDGE_AUTH_HEADER: "guess",
    }
    body = await _get(_edge(), OTHER_PEER, forged, host=HOST)

    assert body["host"] == HOST
    leaked = {"cf-connecting-ip", "true-client-ip", "x-forwarded-for", "x-forwarded-host"}
    leaked |= {"x-forwarded-proto", "forwarded", "cf-ray", EDGE_AUTH_HEADER}
    assert leaked.isdisjoint(body["headers"])


async def test_the_original_host_comes_from_the_edge_only_when_it_is_trusted() -> None:
    trusted = await _get(
        _edge(), CLOUDFLARE_PEER, {"CF-Connecting-IP": VISITOR, "X-Forwarded-Host": HOST}
    )
    untrusted = await _get(
        _edge(), OTHER_PEER, {"CF-Connecting-IP": VISITOR, "X-Forwarded-Host": HOST}
    )

    assert trusted["host"] == HOST
    assert untrusted["host"] == "internal:8000"


async def test_a_trusted_request_without_a_forwarded_host_keeps_its_host() -> None:
    body = await _get(_edge(), CLOUDFLARE_PEER, {"CF-Connecting-IP": VISITOR}, host=HOST)

    assert body["host"] == HOST


@pytest.mark.parametrize(
    "bad_host", ["", "a b", "evil.example/x", "a" * 300, "x@y", "alpha.example.org, beta.org"]
)
async def test_a_forwarded_host_that_is_not_a_host_name_is_ignored(bad_host: str) -> None:
    body = await _get(
        _edge(),
        CLOUDFLARE_PEER,
        {"CF-Connecting-IP": VISITOR, "X-Forwarded-Host": bad_host},
        host=HOST,
    )

    assert body["host"] == HOST


@pytest.mark.parametrize("bad_address", ["", "not-an-address", "999.1.1.1", "1.2.3.4, 5.6.7.8"])
async def test_a_visitor_address_that_is_not_an_address_leaves_the_peer(bad_address: str) -> None:
    body = await _get(_edge(), CLOUDFLARE_PEER, {"CF-Connecting-IP": bad_address})

    assert body["client"] == CLOUDFLARE_PEER


async def test_a_trusted_request_with_no_visitor_address_keeps_the_peer() -> None:
    body = await _get(_edge(), CLOUDFLARE_PEER, {})

    assert body["client"] == CLOUDFLARE_PEER


async def test_the_edge_headers_are_removed_from_a_trusted_request_too() -> None:
    headers = {
        "CF-Connecting-IP": VISITOR,
        "X-Forwarded-Host": HOST,
        "X-Forwarded-For": VISITOR,
        "CF-Ray": "abc",
    }
    body = await _get(_edge(), CLOUDFLARE_PEER, headers)

    assert {"cf-connecting-ip", "x-forwarded-host", "x-forwarded-for", "cf-ray"}.isdisjoint(
        body["headers"]
    )


async def test_the_origin_secret_trusts_a_peer_outside_the_ranges() -> None:
    edge = _edge(origin_secret=ORIGIN_SECRET)

    body = await _get(
        edge,
        OTHER_PEER,
        {"CF-Connecting-IP": VISITOR, EDGE_AUTH_HEADER: ORIGIN_SECRET.decode()},
    )

    assert body["client"] == VISITOR
    assert EDGE_AUTH_HEADER not in body["headers"]


async def test_a_wrong_or_missing_origin_secret_trusts_nobody() -> None:
    edge = _edge(origin_secret=ORIGIN_SECRET)

    wrong = await _get(edge, OTHER_PEER, {"CF-Connecting-IP": VISITOR, EDGE_AUTH_HEADER: "no"})
    missing = await _get(edge, OTHER_PEER, {"CF-Connecting-IP": VISITOR})

    assert wrong["client"] == OTHER_PEER
    assert missing["client"] == OTHER_PEER


async def test_without_an_origin_secret_the_header_trusts_nobody() -> None:
    body = await _get(
        _edge(), OTHER_PEER, {"CF-Connecting-IP": VISITOR, EDGE_AUTH_HEADER: "anything"}
    )

    assert body["client"] == OTHER_PEER


async def test_an_extra_trusted_peer_is_trusted_like_a_range() -> None:
    edge = _edge(extra_peers=parse_ranges(["10.0.0.0/8"]))

    inside = await _get(edge, "10.1.2.3", {"CF-Connecting-IP": VISITOR})
    outside = await _get(edge, "11.1.2.3", {"CF-Connecting-IP": VISITOR})

    assert inside["client"] == VISITOR
    assert outside["client"] == "11.1.2.3"


async def test_a_none_edge_trusts_nobody_even_from_a_cloudflare_range() -> None:
    edge = _edge(trust_cloudflare=False)

    body = await _get(edge, CLOUDFLARE_PEER, {"CF-Connecting-IP": VISITOR})

    assert body["client"] == CLOUDFLARE_PEER


async def test_a_request_with_no_peer_is_not_trusted() -> None:
    seen: dict[str, Any] = {}

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen["client"] = scope.get("client")
        seen["headers"] = [name for name, _ in scope["headers"]]

    middleware = CloudflareEdgeMiddleware(app, edge=_edge())
    scope = {
        "type": "http",
        "client": None,
        "headers": [(b"cf-connecting-ip", VISITOR.encode()), (b"host", b"x")],
    }

    await middleware(scope, None, None)  # type: ignore[arg-type]

    assert seen["client"] is None
    assert seen["headers"] == [b"host"]


async def test_other_scope_types_pass_through_untouched() -> None:
    seen: list[str] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    middleware = CloudflareEdgeMiddleware(app, edge=_edge())

    await middleware({"type": "lifespan"}, None, None)  # type: ignore[arg-type]

    assert seen == ["lifespan"]


def test_the_published_ranges_parse_and_cover_both_families() -> None:
    families = {network.version for network in CLOUDFLARE_RANGES}

    assert families == {4, 6}
    assert ipaddress.ip_address(CLOUDFLARE_PEER) in ipaddress.ip_network("173.245.48.0/20")
    assert all(network.prefixlen >= 8 for network in CLOUDFLARE_RANGES)


@pytest.mark.parametrize("bad", ["", "nonsense", "1.2.3.4/99", "10.0.0.0/8 extra"])
def test_a_range_that_is_not_a_network_is_refused_at_start_up(bad: str) -> None:
    with pytest.raises(ValueError, match="trusted peer"):
        parse_ranges([bad])


def test_the_edge_shows_no_secret_in_its_repr() -> None:
    assert "origin-secret" not in repr(CloudflareEdge(origin_secret=ORIGIN_SECRET))
