"""Trusted-proxy handling for Cloudflare (deployment-plan item 5, KI-161, KI-166, KI-401, KI-441).

The rate limiters count by the request's client address and the tenant binder reads the request's
Host header. Behind Cloudflare the socket peer is Cloudflare and the Host may be rewritten, so the
serving process takes the visitor's address from `CF-Connecting-IP` and the original host from
`X-Forwarded-Host` (a request-header rule that Cloudflare sets, replacing anything the visitor
sent), and it does so ONLY for a request that comes from Cloudflare:

- the socket peer is inside Cloudflare's published ranges (`CLOUDFLARE_RANGES`) or inside a range the
  operator named as a trusted peer (the ingress of the platform, when it accepts traffic only from
  Cloudflare and so the peer is the ingress), or
- the request carries the origin secret in `X-Edge-Auth`, a header that Cloudflare adds with a
  transform rule and that the secret store holds (the authenticated origin pull of this design,
  because the container ingress does not verify a client certificate).

Every other request keeps its socket peer and its own Host. In every case the edge's headers
(`CF-*`, `True-Client-IP`, `X-Forwarded-*`, `Forwarded`, `X-Edge-Auth`) are removed before the
request reaches a route, so nothing downstream can read a value that a visitor could have forged.
A trusted request whose visitor address is missing or is not one address keeps the peer: that
counts Cloudflare as one address (a shared bucket, never a bypass).

`CLOUDFLARE_RANGES` is a snapshot of https://www.cloudflare.com/ips-v4 and /ips-v6 (taken
2026-10-31). Cloudflare changes them rarely; the operator refreshes the list with the
`DIUCS_EDGE_CLOUDFLARE_RANGES_FILE` setting (one range for each line), without a code change.

Pure ASGI: no framework, no store, no tenant. The secret is compared in constant time and never
shown, logged or put in a message.
"""

import hmac
import ipaddress
import logging
from collections.abc import Iterable, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from diucs.application.ports.outbound.tenants import normalise_host

log = logging.getLogger(__name__)

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

CLIENT_HEADER: Final = "cf-connecting-ip"
HOST_HEADER: Final = "x-forwarded-host"
EDGE_AUTH_HEADER: Final = "x-edge-auth"
"""The header the origin secret arrives in (lower case, as Starlette reads it)."""

# Everything the edge (or a visitor pretending to be it) can say about the client or the host. All
# of it is removed before the request reaches a route.
_REMOVED: Final = frozenset(
    {
        CLIENT_HEADER,
        HOST_HEADER,
        EDGE_AUTH_HEADER,
        "true-client-ip",
        "x-forwarded-for",
        "x-forwarded-proto",
        "x-forwarded-port",
        "x-real-ip",
        "forwarded",
        "cf-ray",
        "cf-ipcountry",
        "cf-visitor",
        "cf-connecting-ipv6",
        "cf-pseudo-ipv4",
        "cdn-loop",
    }
)

_RANGES_V4: Final = (
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
)
_RANGES_V6: Final = (
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
)
_MAX_RANGE_LINE: Final = 64


def parse_ranges(lines: Iterable[str]) -> tuple[IPNetwork, ...]:
    """The networks the lines name. A line that is not a network (or that has anything after it) is
    refused with a message that names no value, so a bad setting stops the process at start-up."""
    found: list[IPNetwork] = []
    for line in lines:
        text = line.strip()
        if not text or len(text) > _MAX_RANGE_LINE or " " in text:
            raise ValueError("a trusted peer range is not a network")
        try:
            found.append(ipaddress.ip_network(text, strict=False))
        except ValueError:
            raise ValueError("a trusted peer range is not a network") from None
    return tuple(found)


CLOUDFLARE_RANGES: Final = parse_ranges((*_RANGES_V4, *_RANGES_V6))


@dataclass(frozen=True, slots=True)
class CloudflareEdge:
    """Who counts as the edge. `trust_cloudflare` False (the setting `none`) trusts only the
    origin secret and the extra peers; with neither, nobody."""

    ranges: Sequence[IPNetwork] = CLOUDFLARE_RANGES
    extra_peers: Sequence[IPNetwork] = ()
    origin_secret: bytes | None = field(default=None, repr=False)
    trust_cloudflare: bool = True

    def peer_is_trusted(self, peer: str) -> bool:
        try:
            address = ipaddress.ip_address(peer)
        except ValueError:
            return False
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped  # a dual-stack socket shows an IPv4 peer this way
        networks = (*self.ranges, *self.extra_peers) if self.trust_cloudflare else self.extra_peers
        return any(address in network for network in networks if network.version == address.version)

    def secret_matches(self, presented: bytes | None) -> bool:
        if self.origin_secret is None or presented is None:
            return False
        return hmac.compare_digest(self.origin_secret, presented)


def _client_address(value: bytes | None) -> str | None:
    if value is None:
        return None
    try:
        return str(ipaddress.ip_address(value.decode("ascii").strip()))
    except UnicodeDecodeError, ValueError:
        return None


def _original_host(value: bytes | None) -> bytes | None:
    """The host name of the header (its port dropped), or None when it is not one."""
    if value is None:
        return None
    try:
        text = value.decode("ascii")
    except UnicodeDecodeError:
        return None
    name = text.rsplit(":", 1)[0] if ":" in text else text
    host = normalise_host(name)
    return None if host is None else host.encode("ascii")


class CloudflareEdgeMiddleware:
    """The outermost middleware: it settles who the client is and what the host is, then removes the
    edge's headers."""

    def __init__(self, app: Any, edge: CloudflareEdge) -> None:
        self._app = app
        self._edge = edge

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        headers: list[tuple[bytes, bytes]] = list(scope.get("headers", ()))
        by_name: dict[bytes, bytes] = {}
        for name, value in headers:
            by_name.setdefault(name.lower(), value)
        client = scope.get("client")
        peer = client[0] if client else None
        trusted = peer is not None and (
            self._edge.peer_is_trusted(peer)
            or self._edge.secret_matches(by_name.get(EDGE_AUTH_HEADER.encode()))
        )
        kept = [(name, value) for name, value in headers if name.lower().decode() not in _REMOVED]
        if trusted:
            visitor = _client_address(by_name.get(CLIENT_HEADER.encode()))
            if visitor is None:
                log.warning("edge request without a usable visitor address")
            else:
                scope["client"] = (visitor, 0)
            host = _original_host(by_name.get(HOST_HEADER.encode()))
            if host is not None:
                kept = [(name, value) for name, value in kept if name.lower() != b"host"]
                kept.append((b"host", host))
        scope["headers"] = kept
        await self._app(scope, receive, send)
