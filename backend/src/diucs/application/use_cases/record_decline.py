"""RecordDecline and ListDeclinesSince: a declined referral despite capacity (U13). Red stub."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from diucs.application.ports.outbound.audit import AuditRecord
from diucs.domain.codes import DeclineReason


@dataclass(frozen=True, slots=True)
class DeclineRecord:
    service_id: str
    reason: DeclineReason
    at: datetime


def number_seen(effective_available: int | None, used: int | None) -> int | None:
    raise NotImplementedError


def declines_from(records: Sequence[AuditRecord], since: datetime) -> list[DeclineRecord]:
    raise NotImplementedError
