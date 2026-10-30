"""Every route of the network API, by template, with who may use it (TEN-062).

The table is what the role matrix and the privacy scan run over, and `discovered` reads the same
list from the app's own route table, so a network route added to the API and left out of the tests
fails the completeness test instead of going unscanned. A route is a network route when its path is
`/networks`, starts with `/network/`, or is a wall screen's own network read
(`/screens/me/network-...`). The administration of networks (members, grants, listings) is the
network administrator's and is listed apart, with its own roles.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final

from fastapi import FastAPI
from fastapi.routing import APIRoute, _IncludedRouter

from diucs.application.network_access import NETWORK_VIEW_ROLES
from diucs.application.use_cases.network_week_summary import READERS
from diucs.domain.codes import Role


@dataclass(frozen=True, slots=True)
class NetworkRoute:
    method: str
    template: str
    roles: frozenset[Role]
    streams: bool = False
    needs_week: bool = False
    json_keys_are_scanned: bool = True


VIEW: Final = frozenset(NETWORK_VIEW_ROLES)
WALL: Final = frozenset({Role.WALL})

ROUTES: Final[tuple[NetworkRoute, ...]] = (
    # `/networks` names the network and its settings, so its own `name` key is expected
    NetworkRoute("GET", "/networks", VIEW, json_keys_are_scanned=False),
    NetworkRoute("GET", "/network/{network_id}/board", VIEW),
    NetworkRoute("GET", "/network/{network_id}/directory", VIEW),
    NetworkRoute("GET", "/network/{network_id}/criteria", VIEW),
    NetworkRoute("GET", "/network/{network_id}/events", VIEW, streams=True),
    NetworkRoute("GET", "/network/{network_id}/system-now", VIEW),
    NetworkRoute("GET", "/network/{network_id}/phones", VIEW),
    NetworkRoute("GET", "/network/{network_id}/week", frozenset(READERS), needs_week=True),
    NetworkRoute("GET", "/screens/me/network-board", WALL),
    NetworkRoute("GET", "/screens/me/network-events", WALL, streams=True),
)

# Routes that read or write the sharing of a network, not its board: the network administrator's
# and the tenant administrator's (TEN-077 to TEN-079). They are not scanned here.
ADMIN_PREFIXES: Final = ("/network-admin", "/admin/")


def is_network_route(path: str) -> bool:
    if path.startswith(ADMIN_PREFIXES):
        return False
    return path == "/networks" or path.startswith(("/network/", "/screens/me/network"))


@dataclass(frozen=True, slots=True)
class _Effective:
    path: str
    methods: frozenset[str]


def _effective(routes: Any) -> Iterator[Any]:
    """Every route with its full path. FastAPI includes a router lazily (`_IncludedRouter`), so the
    walk goes through its effective candidates, as `test_edge_binding.py` does; a kind of route it
    does not know fails instead of being missed."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_route") and hasattr(route, "path"):
            # an effective route: the route with its full path (prefix included)
            yield _Effective(route.path, frozenset(route.original_route.methods))
        elif isinstance(route, _IncludedRouter):
            yield from _effective(route.effective_candidates())
            yield from _effective(route.effective_low_priority_routes())
        else:
            raise AssertionError(f"a route of a kind this scan does not know: {route!r}")


def discovered(app: FastAPI) -> set[tuple[str, str]]:
    """The (method, template) of every network route the app serves."""
    found: set[tuple[str, str]] = set()
    for route in _effective(app.routes):
        if is_network_route(route.path):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                found.add((method, route.path))
    return found


def url(route: NetworkRoute, network_id: str) -> str:
    return route.template.replace("{network_id}", network_id)
