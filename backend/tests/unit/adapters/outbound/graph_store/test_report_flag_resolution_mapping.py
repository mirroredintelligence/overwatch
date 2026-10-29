"""Pure round trip of a report flag's resolution (U39): the practitioner who resolved a flag is kept
when the flag is stored and read back, and an unresolved flag reads back with no resolver. The
store keeps no null property (lesson L74), so an absent value must read back as absent, never as
an empty text. Synthetic values only."""

from datetime import UTC, datetime

from diucs.adapters.outbound.graph_store.flag_repository import _report_flag, _report_props
from diucs.domain.codes import ReportFlagReason
from diucs.domain.model.flags import REPORT_FLAG_CHECKED, REPORT_FLAG_OPEN, ReportFlag

CREATED = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
RESOLVED = datetime(2026, 10, 23, 13, 30, tzinfo=UTC)


class _DriverDateTime:
    """What the driver returns for a stored datetime: it converts to the native type."""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def to_native(self) -> datetime:
        return self.value


def _as_read(stored: dict[str, object]) -> dict[str, object]:
    return {
        key: _DriverDateTime(value) if isinstance(value, datetime) else value
        for key, value in stored.items()
    }


def _flag(**overrides: object) -> ReportFlag:
    base: dict[str, object] = {
        "id": "flag-1",
        "report_id": "obs-2",
        "service_id": "ucr-east",
        "reason": ReportFlagReason.OUT_OF_RANGE_TWICE,
        "status": REPORT_FLAG_OPEN,
        "created_at": CREATED,
    }
    base.update(overrides)
    return ReportFlag(**base)  # type: ignore[arg-type]


def test_a_resolved_flag_keeps_the_practitioner_who_resolved_it() -> None:
    resolved = _flag(
        status=REPORT_FLAG_CHECKED,
        resolved_at=RESOLVED,
        outcome="checked",
        resolved_by="prac-lead",
    )
    stored = _report_props(resolved)
    assert stored["resolvedBy"] == "prac-lead"
    assert _report_flag(_as_read(stored), "obs-2") == resolved


def test_a_flag_resolved_by_nobody_reads_back_with_no_resolver() -> None:
    flag = _flag()
    stored = _report_props(flag)
    assert "resolvedBy" not in stored
    assert _report_flag(_as_read(stored), "obs-2").resolved_by is None


def test_a_resolver_given_as_empty_text_is_refused_by_the_model() -> None:
    import pytest

    from diucs.domain.errors import ValidationFailed

    with pytest.raises(ValidationFailed):
        _flag(status=REPORT_FLAG_CHECKED, resolved_at=RESOLVED, outcome="checked", resolved_by=" ")
