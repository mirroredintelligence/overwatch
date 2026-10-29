"""The process start-up for telemetry (O01): nothing is wired without an endpoint."""

from diucs.adapters.outbound.graph_store import driver
from diucs.bootstrap.settings import Settings
from diucs.bootstrap.telemetry import start_telemetry


def test_without_an_endpoint_no_provider_and_no_query_observer() -> None:
    driver.set_query_observer(None)

    assert start_telemetry(Settings(otlp_endpoint="")) is None
    assert driver._observer is None


def test_the_app_hook_is_none_when_the_setting_is_off() -> None:
    from diucs.bootstrap.telemetry import api_instrumentation

    assert api_instrumentation(Settings(otel_instrument_http=False), None) is None


def test_the_app_hook_instruments_the_app_when_the_setting_is_on() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from diucs.adapters.outbound.telemetry.otel import build_provider
    from diucs.bootstrap.telemetry import api_instrumentation

    exporter = InMemorySpanExporter()
    provider = build_provider(service_name="t", release="t", exporter=exporter)
    hook = api_instrumentation(Settings(otel_instrument_http=True), provider)
    assert hook is not None
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    hook(app)
    TestClient(app).get("/ping")
    provider.force_flush()

    assert len(exporter.get_finished_spans()) == 1
