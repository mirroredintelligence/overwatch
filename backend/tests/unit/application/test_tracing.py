"""The application's tracing seam (O01). A pure recording tracer stands in for the OpenTelemetry
adapter, so the application tests need no SDK."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import pytest

from diucs.application.tracing import (
    NoopTracer,
    annotate_usecase,
    get_tracer,
    set_tracer,
    traced_use_case,
)
from diucs.domain.errors import Conflict


class RecordedSpan:
    def __init__(self, name: str, attributes: Mapping[str, Any]) -> None:
        self.name = name
        self.attributes: dict[str, Any] = dict(attributes)
        self.error_type: str | None = None

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def fail(self, error_type: str) -> None:
        self.error_type = error_type


class RecordingTracer:
    def __init__(self) -> None:
        self.spans: list[RecordedSpan] = []

    @contextmanager
    def span(self, name: str, attributes: Mapping[str, Any]) -> Iterator[RecordedSpan]:
        recorded = RecordedSpan(name, attributes)
        self.spans.append(recorded)
        yield recorded


@pytest.fixture
def recorder() -> Iterator[RecordingTracer]:
    tracer = RecordingTracer()
    set_tracer(tracer)
    yield tracer
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


async def test_a_use_case_is_one_span_named_after_it_with_outcome_ok(
    recorder: RecordingTracer,
) -> None:
    result = await FakeReportCapacity().execute(object())

    assert result == "reported"
    [span] = recorder.spans
    assert span.name == "usecase.ReportCapacity"
    assert span.attributes["usecase.outcome"] == "ok"
    assert span.error_type is None


async def test_a_failing_use_case_records_its_exception_class_and_reraises(
    recorder: RecordingTracer,
) -> None:
    with pytest.raises(Conflict):
        await FakeReportCapacity(raises=Conflict("reference taken")).execute(object())

    [span] = recorder.spans
    assert span.name == "usecase.ReportCapacity"
    assert span.attributes["usecase.outcome"] == "Conflict"
    assert span.error_type == "Conflict"


async def test_the_use_case_can_annotate_its_own_span(recorder: RecordingTracer) -> None:
    await FakeReportCapacity().execute(object())

    [span] = recorder.spans
    assert span.attributes["usecase.idempotent_replay"] is False


def test_annotation_refuses_a_key_outside_the_usecase_namespace(
    recorder: RecordingTracer,
) -> None:
    with pytest.raises(ValueError):
        annotate_usecase("patient.postcode", "DT4 8XX")


def test_annotation_outside_a_use_case_does_nothing(recorder: RecordingTracer) -> None:
    annotate_usecase("usecase.idempotent_replay", True)

    assert recorder.spans == []


async def test_without_a_tracer_the_use_case_still_runs() -> None:
    set_tracer(NoopTracer())

    assert await FakeReportCapacity().execute(object()) == "reported"
    assert isinstance(get_tracer(), NoopTracer)
