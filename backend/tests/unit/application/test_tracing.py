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
    """Keeps the spans it opens, and the stack of the ones still open: the tracer, not a context
    variable of the application, says which span is current."""

    def __init__(self) -> None:
        self.spans: list[RecordedSpan] = []
        self._open: list[RecordedSpan] = []

    @contextmanager
    def span(self, name: str, attributes: Mapping[str, Any]) -> Iterator[RecordedSpan]:
        recorded = RecordedSpan(name, attributes)
        self.spans.append(recorded)
        self._open.append(recorded)
        try:
            yield recorded
        finally:
            self._open.pop()

    def current_span(self) -> RecordedSpan:
        return self._open[-1] if self._open else RecordedSpan("", {})


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


def test_annotation_lands_on_the_span_the_tracer_has_open(recorder: RecordingTracer) -> None:
    # No decorator here: the span is opened by the tracer, and the annotation must find it there.
    with recorder.span("usecase.Manual", {}):
        annotate_usecase("usecase.idempotent_replay", True)

    [span] = recorder.spans
    assert span.attributes["usecase.idempotent_replay"] is True


async def test_with_the_no_op_tracer_an_annotation_inside_a_use_case_raises_nothing() -> None:
    set_tracer(NoopTracer())

    assert await FakeReportCapacity().execute(object()) == "reported"


def test_the_no_op_tracer_gives_a_span_that_takes_attributes_and_does_nothing() -> None:
    tracer = NoopTracer()

    span = tracer.current_span()
    span.set_attribute("usecase.idempotent_replay", True)
    span.fail("Conflict")

    assert tracer.current_span() is not None
