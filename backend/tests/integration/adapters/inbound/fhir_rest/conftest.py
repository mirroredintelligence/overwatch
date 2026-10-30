"""Makes the API fixtures (tests/support/api.py) available to the FHIR REST route tests."""

from tests.support.api import api_app, api_client, edge_tenants, test_container

__all__ = ["api_app", "api_client", "edge_tenants", "test_container"]
