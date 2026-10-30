"""The collector's allow-list, run for real (O04). Needs the test profile of
infra/docker-compose.yml.

Start the collector first:
    docker compose -f infra/docker-compose.yml --profile test up -d --wait otel-collector
The collector writes what it exports to infra/otel-out/out.json (container path /tmp/otel/out.json).
The collector waits up to 10 s for tail sampling, so each test polls the file for a while.

Tail sampling keeps an error trace every time, but keeps only 10 per cent of the others. The
allow-list tests therefore send error spans: the attribute rules run before sampling, so the span
is still tested, and it is certain to be exported. A plain span would be dropped 9 times in 10.
"""

import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Final

import pytest
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from diucs.adapters.outbound.telemetry.attributes import SERVICE_NAME

pytestmark = [pytest.mark.integration, pytest.mark.infra, pytest.mark.exclusive]

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
INFRA: Final = REPO_ROOT / "infra"
OUT_FILE: Final = INFRA / "otel-out" / "out.json"
ENDPOINT: Final = os.environ.get("DIUCS_OTLP_TEST_ENDPOINT", "http://127.0.0.1:4318/v1/traces")
WAIT_SECONDS: Final = 30.0


def _send_span(name: str, attributes: dict[str, str | int], *, error: bool = False) -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=ENDPOINT)))
    tracer = provider.get_tracer("diucs-collector-test")
    with tracer.start_as_current_span(name, attributes=attributes) as span:
        if error:
            span.set_status(Status(StatusCode.ERROR, "collector test"))
    provider.force_flush()
    provider.shutdown()


def _exported_span(name: str) -> tuple[dict[str, Any], str] | None:
    """The first exported span with this name: its attributes and the raw line that carried it."""
    if not OUT_FILE.exists():
        return None
    for line in OUT_FILE.read_text(encoding="utf-8").splitlines():
        if name not in line:
            continue
        for resource in json.loads(line).get("resourceSpans", []):
            for scope in resource.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    if span.get("name") == name:
                        attributes = {
                            item["key"]: next(iter(item["value"].values()))
                            for item in span.get("attributes", [])
                        }
                        return attributes, line
    return None


def _wait_for_span(name: str) -> tuple[dict[str, Any], str]:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        found = _exported_span(name)
        if found is not None:
            return found
        time.sleep(1.0)
    raise AssertionError(f"the collector did not export span {name} within {WAIT_SECONDS} s")


def test_the_allowed_key_is_kept_and_the_postcode_is_removed() -> None:
    name = f"collector-allow-{uuid.uuid4().hex}"
    _send_span(name, {"service.id": "svc-1", "patient.postcode": "DT4 8XX"}, error=True)

    attributes, raw = _wait_for_span(name)

    assert attributes.get("service.id") == "svc-1"
    assert "patient.postcode" not in attributes
    assert "DT4 8XX" not in raw


def test_query_text_and_parameters_never_leave_the_collector() -> None:
    name = f"collector-query-{uuid.uuid4().hex}"
    _send_span(
        name,
        {
            "db.system": "neo4j",
            "db.statement": "MATCH (n:Patient) RETURN n",
            "db.query.text": "MATCH",
        },
        error=True,
    )

    attributes, raw = _wait_for_span(name)

    assert attributes.get("db.system") == "neo4j"
    assert "db.statement" not in attributes
    assert "db.query.text" not in attributes
    assert "MATCH (n:Patient)" not in raw


def test_free_text_under_name_and_value_never_leaves_the_collector() -> None:
    # `name` and `value` can carry a typed word; the collector keeps neither (O04 integration).
    span = f"collector-freetext-{uuid.uuid4().hex}"
    _send_span(
        span,
        {"service.id": "svc-1", "name": "Sample Patient", "value": "Sample Patient DT4 8XX"},
        error=True,
    )

    attributes, raw = _wait_for_span(span)

    assert attributes.get("service.id") == "svc-1"
    assert "name" not in attributes
    assert "value" not in attributes
    assert "Sample Patient" not in raw


def test_an_error_span_is_kept_by_sampling() -> None:
    name = f"collector-error-{uuid.uuid4().hex}"
    _send_span(name, {"service.id": "svc-1"}, error=True)

    attributes, _ = _wait_for_span(name)

    assert attributes.get("service.id") == "svc-1"


def test_the_collector_config_validates_with_its_pinned_image() -> None:
    compose = (INFRA / "docker-compose.yml").read_text(encoding="utf-8")
    image = next(
        line.split("image:", 1)[1].strip()
        for line in compose.splitlines()
        if "otel/opentelemetry-collector-contrib" in line and "image:" in line
    )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-e",
            "APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=00000000-0000-0000-0000-000000000000",
            "-v",
            f"{INFRA / 'otel-collector.yaml'}:/etc/otelcol/config.yaml:ro",
            image,
            "validate",
            "--config",
            "/etc/otelcol/config.yaml",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
