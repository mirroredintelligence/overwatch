"""Makes the API fixtures (tests/support/api.py) and the network fixtures
(tests/support/network_fixtures.py: `connection`, `world`, `net_app`) available to the FHIR REST
route tests."""

from tests.support.api import api_app, api_client, edge_tenants, test_container
from tests.support.network_fixtures import bare_world, connection, net_app, world

__all__ = [
    "api_app",
    "api_client",
    "bare_world",
    "connection",
    "edge_tenants",
    "net_app",
    "test_container",
    "world",
]
