"""The process start-up for telemetry (O01): nothing is wired without an endpoint."""

from diucs.adapters.outbound.graph_store import driver
from diucs.bootstrap.settings import Settings
from diucs.bootstrap.telemetry import start_telemetry


def test_without_an_endpoint_no_provider_and_no_query_observer() -> None:
    driver.set_query_observer(None)

    assert start_telemetry(Settings(otlp_endpoint="")) is None
    assert driver._observer is None
