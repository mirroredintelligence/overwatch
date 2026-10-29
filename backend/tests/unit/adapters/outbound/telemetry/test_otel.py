"""The OpenTelemetry adapter (O01), tested with the SDK's in-memory exporter. No Docker."""

from collections.abc import Iterator

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from diucs.adapters.outbound.telemetry import otel
from diucs.adapters.outbound.telemetry.otel import (
    OtelTracer,
    build_provider,
    configure_telemetry,
    neo4j_span,
    record_query,
)
from diucs.application import tracing
from diucs.application.tracing import NoopTracer, annotate_usecase, set_tracer, traced_use_case
from diucs.bootstrap.settings import Settings
from diucs.domain.errors import Conflict


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def provider(exporter: InMemorySpanExporter) -> Iterator[TracerProvider]:
    built = build_provider(service_name="diucs-test", release="test-release", exporter=exporter)
    yield built
    built.shutdown()


@pytest.fixture
def traced(provider: TracerProvider) -> Iterator[None]:
    set_tracer(OtelTracer(provider.get_tracer("diucs-test")))
    yield
    set_tracer(NoopTracer())


class FakeReportCapacity:
    def __init__(self, raises: BaseException | None = None) -> None:
        self._raises = raises

    @traced_use_case("ReportCapacity")
    async def execute(self, command: object) -> str:
        if self._raises is not None:
            raise self._raises
        annotate_usecase("usecase.idempotent_replay", False)
        return "reported"


async def test_a_decorated_use_case_produces_a_span_with_outcome_ok(
    traced: None, provider: TracerProvider, exporter: InMemorySpanExporter
) -> None:
    await FakeReportCapacity().execute(object())

    provider.force_flush()
    [span] = exporter.get_finished_spans()
    assert span.name == "usecase.ReportCapacity"
    assert span.attributes["usecase.outcome"] == "ok"
    assert span.attributes["usecase.idempotent_replay"] is False


async def test_a_conflict_sets_the_outcome_to_its_class_and_the_span_status_to_error(
    traced: None, provider: TracerProvider, exporter: InMemorySpanExporter
) -> None:
    with pytest.raises(Conflict):
        await FakeReportCapacity(raises=Conflict("reference taken")).execute(object())

    provider.force_flush()
    [span] = exporter.get_finished_spans()
    assert span.attributes["usecase.outcome"] == "Conflict"
    assert span.status.status_code == StatusCode.ERROR


def test_attributes_outside_the_allow_list_never_reach_the_exporter(
    provider: TracerProvider, exporter: InMemorySpanExporter
) -> None:
    tracer = provider.get_tracer("diucs-test")
    with tracer.start_as_current_span(
        "usecase.CaseOpened",
        attributes={
            "patient.postcode": "DT4 8XX",
            "http.request.body": '{"name": "Sample Patient"}',
            "service.id": "SVC-0042",
            "session.id": "sess-7f3a",
        },
    ) as span:
        span.add_event(
            "exception",
            {"exception.message": "bad postcode DT4 8XX", "exception.stacktrace": "traceback"},
        )

    provider.force_flush()
    [recorded] = exporter.get_finished_spans()
    assert "patient.postcode" not in recorded.attributes
    assert "http.request.body" not in recorded.attributes
    assert recorded.attributes["service.id"] == "SVC-0042"
    assert recorded.attributes["session.id"] == "sess-7f3a"
    [event] = recorded.events
    assert event.name == "exception"
    assert "exception.message" not in event.attributes
    assert "exception.stacktrace" not in event.attributes


def test_a_named_query_span_carries_the_query_id_and_mode_and_no_cypher(
    provider: TracerProvider, exporter: InMemorySpanExporter
) -> None:
    with neo4j_span("Q-BOARD", "read", tracer=provider.get_tracer("diucs-test")):
        pass

    provider.force_flush()
    [recorded] = exporter.get_finished_spans()
    assert recorded.name == "neo4j.query Q-BOARD"
    assert recorded.attributes["db.system"] == "neo4j"
    assert recorded.attributes["db.system.name"] == "neo4j"
    assert recorded.attributes["db.query.id"] == "Q-BOARD"
    assert recorded.attributes["db.access_mode"] == "read"
    assert not any("MATCH" in str(value) for value in recorded.attributes.values())


def test_the_query_observer_records_rows_and_duration_on_a_finished_span(
    provider: TracerProvider, exporter: InMemorySpanExporter
) -> None:
    record_query("Q-BOARD", "read", 7, 12.5, tracer=provider.get_tracer("diucs-test"))

    provider.force_flush()
    [recorded] = exporter.get_finished_spans()
    assert recorded.attributes["db.query.id"] == "Q-BOARD"
    assert recorded.attributes["db.row_count"] == 7
    assert recorded.end_time - recorded.start_time == 12_500_000  # nanoseconds


def test_a_tenant_id_is_allow_listed_and_survives(
    provider: TracerProvider, exporter: InMemorySpanExporter
) -> None:
    tracer = provider.get_tracer("diucs-test")
    with tracer.start_as_current_span("usecase.ReportCapacity", attributes={"tenant.id": "T-A"}):
        pass

    provider.force_flush()
    [recorded] = exporter.get_finished_spans()
    assert recorded.attributes["tenant.id"] == "T-A"


def test_an_empty_endpoint_installs_no_exporter_and_nothing_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("no exporter may be built without an endpoint")

    monkeypatch.setattr(otel, "OTLPSpanExporter", refuse)
    set_tracer(NoopTracer())

    assert configure_telemetry(Settings(otlp_endpoint="")) is None
    assert isinstance(tracing.get_tracer(), NoopTracer)


def test_an_endpoint_builds_one_exporter_for_that_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[str] = []

    class RecordingExporter:
        def __init__(self, endpoint: str) -> None:
            built.append(endpoint)

        def export(self, spans: object) -> object:
            return None

        def shutdown(self) -> None:
            return None

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    monkeypatch.setattr(otel, "OTLPSpanExporter", RecordingExporter)
    monkeypatch.setattr(otel, "_install_global_provider", lambda provider: None)
    set_tracer(NoopTracer())

    provider = configure_telemetry(
        Settings(otlp_endpoint="http://collector:4318/v1/traces", release="2026.10.29")
    )

    assert provider is not None
    assert built == ["http://collector:4318/v1/traces"]
    set_tracer(NoopTracer())


def test_fastapi_spans_carry_the_route_template_and_no_raw_url(
    provider, exporter: InMemorySpanExporter
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/fhir/HealthcareService/{service_id}")
    def read_service(service_id: str) -> dict[str, str]:
        return {"id": service_id}

    otel.instrument_fastapi(app, provider)
    client = TestClient(app)

    response = client.get("/fhir/HealthcareService/SVC-0042?name=Sample+Patient")

    assert response.status_code == 200
    provider.force_flush()
    server_spans = [span for span in exporter.get_finished_spans() if span.attributes]
    assert server_spans
    for span in server_spans:
        assert span.attributes.get("http.route") in (None, "/fhir/HealthcareService/{service_id}")
        assert not any("SVC-0042" in str(value) for value in span.attributes.values())
        assert not any("Sample" in str(value) for value in span.attributes.values())
        assert "url.full" not in span.attributes
        assert "http.target" not in span.attributes


def test_instrumenting_an_app_twice_gives_each_request_one_server_span(
    provider, exporter: InMemorySpanExporter
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    otel.instrument_fastapi(app, provider)
    otel.instrument_fastapi(app, provider)
    response = TestClient(app).get("/ping")

    assert response.status_code == 200
    provider.force_flush()
    assert len(exporter.get_finished_spans()) == 1


def test_an_annotation_lands_on_the_span_the_otel_tracer_has_open(
    provider, exporter: InMemorySpanExporter
) -> None:
    # The span is opened by the adapter, not by the decorator: the OpenTelemetry context says which
    # span is current, and the annotation must land on it.
    tracer = OtelTracer(provider.get_tracer("diucs-test"))
    with tracer.span("usecase.ManualOpen", {}):
        annotate_usecase("usecase.idempotent_replay", True)

    provider.force_flush()
    [span] = exporter.get_finished_spans()
    assert span.attributes["usecase.idempotent_replay"] is True
