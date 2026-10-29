"""Resolve report flags for the shift lead (U39). Stub for the red commit (DEC-010)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from diucs.application.actor import Actor
from diucs.domain.codes import ReportFlagReason
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import ReportFlag


def check_lead(actor: Actor) -> None:
    raise NotImplementedError


def resolved_status(outcome: str) -> str:
    raise NotImplementedError


def check_resolution(outcome: str, phoned_value: int | None) -> None:
    raise NotImplementedError


def sequence_of(reports: Sequence[CapacityReport]) -> str:
    raise NotImplementedError


def describe_flag(
    flag: ReportFlag,
    *,
    service_name: str,
    usual_range: tuple[int, int],
    report: CapacityReport,
    window: Sequence[CapacityReport],
) -> str:
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ReportFlagView:
    flag_id: str
    service_id: str
    service_name: str
    reason: ReportFlagReason
    description: str
    raised_at: datetime


@dataclass(frozen=True, slots=True)
class ResolveReportFlagCommand:
    idempotency_key: str
    actor: Actor
    flag_id: str
    outcome: Literal["checked", "accepted", "phoned"]
    phoned_value: int | None = None


@dataclass(frozen=True, slots=True)
class ResolveReportFlagResult:
    flag_id: str
    status: str
    outcome: str
    phoned_report_id: str | None = None
