"""The FHIR app's request tracing (O01, the setting-driven hook): with no hook the app is not
instrumented, with one it is instrumented once, and a request gets one server span under its route
template. The container is a stand-in with a fixed clock and no store; /fhir/metadata needs no
store. /health is excluded from tracing on purpose (probes are not traced)."""

from types import SimpleNamespace

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.outbound.telemetry.otel import build_provider, instrument_fastapi
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.bootstrap.container import TEST_NOW


def _container() -> SimpleNamespace:
    return SimpleNamespace(clock=FixedClock(TEST_NOW), uow_factory=None, ids=None)


def test_with_no_hook_the_app_answers_and_records_no_span() -> None:
    exporter = InMemorySpanExporter()
    provider = build_provider(service_name="t", release="t", exporter=exporter)

    app = create_app(_container())
    response = TestClient(app).get("/fhir/metadata")
    provider.force_flush()

    assert response.status_code == 200
    assert exporter.get_finished_spans() == ()


def test_with_the_hook_a_request_records_one_span_under_the_route_template() -> None:
    exporter = InMemorySpanExporter()
    provider = build_provider(service_name="t", release="t", exporter=exporter)
    calls: list[object] = []

    def hook(app: object) -> None:
        calls.append(app)
        instrument_fastapi(app, provider)

    app = create_app(_container(), instrument=hook)
    response = TestClient(app).get("/fhir/metadata")
    provider.force_flush()

    assert response.status_code == 200
    assert len(calls) == 1
    [span] = exporter.get_finished_spans()
    assert span.attributes is not None
    assert span.attributes.get("http.route") == "/fhir/metadata"
    assert "url.full" not in span.attributes
    assert "http.target" not in span.attributes
