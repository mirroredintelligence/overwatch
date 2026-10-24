"""Local FHIR code systems. RED STUB (DEC-010): names and signatures only, no behaviour."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

BASE_URL = ""


class Status(StrEnum):
    pass


class Measure(StrEnum):
    pass


class ReportSource(StrEnum):
    pass


class ReportType(StrEnum):
    pass


class ServiceCategory(StrEnum):
    pass


class NeedCategory(StrEnum):
    pass


class Urgency(StrEnum):
    pass


class AgeBand(StrEnum):
    pass


class AcuityMethod(StrEnum):
    pass


class BookingStatus(StrEnum):
    pass


class DeclineReason(StrEnum):
    pass


class WithdrawReason(StrEnum):
    pass


class NotReachedReason(StrEnum):
    pass


class CancelReason(StrEnum):
    pass


class RegistrationStatus(StrEnum):
    pass


class CriteriaStatus(StrEnum):
    pass


class Channel(StrEnum):
    pass


class AlertKind(StrEnum):
    pass


class Cadence(StrEnum):
    pass


class Role(StrEnum):
    pass


class ScopeFlag(StrEnum):
    pass


class ReportFlagReason(StrEnum):
    pass


class Outcome(StrEnum):
    pass


class BestFitNotUsedReason(StrEnum):
    pass


class ReferrerType(StrEnum):
    pass


CODE_SYSTEM_NAMES: Mapping[type[StrEnum], str] = {}


def code_system_url(name: str) -> str:
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class Coding:
    system: str
    code: str
    display: str


def display(member: StrEnum) -> str:
    raise NotImplementedError


def coding_for(member: StrEnum) -> Coding:
    raise NotImplementedError


def parse_code[E: StrEnum](enum_cls: type[E], code: str) -> E:
    raise NotImplementedError
