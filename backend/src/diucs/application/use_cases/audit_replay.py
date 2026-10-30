"""Audit replay of what the advisor saw (U42). Stub for the red commit (DEC-010)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditRecord
from diucs.domain.codes import Status

REPLAY_USE_CASE = "AuditReplay"


@dataclass(frozen=True, slots=True)
class ReplayRow:
    service_name: str
    status: str
    value_text: str
    data_age_text: str
    criteria_version: int | None


@dataclass(frozen=True, slots=True)
class TimelineItem:
    at: object
    label: str


def status_word(status: Status) -> str:
    raise NotImplementedError


def age_words(seconds: int | None) -> str:
    raise NotImplementedError


def replay_rows(
    snapshot_rows: Sequence[Mapping[str, object]], names: Mapping[str, str]
) -> tuple[ReplayRow, ...]:
    raise NotImplementedError


def timeline_item(record: AuditRecord) -> TimelineItem | None:
    raise NotImplementedError


def options_display(records: Sequence[AuditRecord]) -> AuditRecord | None:
    raise NotImplementedError


def check_replay_role(actor: Actor) -> None:
    raise NotImplementedError
