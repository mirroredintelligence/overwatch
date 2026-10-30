"""The projection ports (TEN-053): a writer and a reader, kept apart on purpose."""

import dataclasses
import typing

import pytest

from diucs.application.ports.outbound.projection import (
    GrantRef,
    NetworkView,
    ProjectedRow,
    ProjectionEndReason,
    ProjectionRecordInvalid,
    ProjectionWriter,
    SourceState,
    SourceStatus,
)


def test_the_writer_and_the_reader_share_no_method() -> None:
    writer = typing.get_protocol_members(ProjectionWriter)
    reader = typing.get_protocol_members(NetworkView)
    assert writer == {
        "open_source",
        "end_source",
        "upsert_service",
        "upsert_capacity",
        "upsert_criteria",
        "mark_ended",
    }
    assert reader == {"source", "sources", "services", "capacities", "criteria"}
    assert not writer & reader


def test_the_reasons_a_row_stops_being_live_are_these_three() -> None:
    assert {r.value for r in ProjectionEndReason} == {"left", "grant-ended", "replaced"}
    assert {s.value for s in SourceStatus} == {"active", "ended"}


def test_the_records_are_frozen() -> None:
    ref = GrantRef("grant-1", 1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.grant_id = "x"  # type: ignore[misc]
    for record in (SourceState, ProjectedRow):
        assert dataclasses.is_dataclass(record)
        assert record.__dataclass_params__.frozen  # type: ignore[attr-defined]


def test_a_record_fault_is_a_runtime_error() -> None:
    assert issubclass(ProjectionRecordInvalid, RuntimeError)
