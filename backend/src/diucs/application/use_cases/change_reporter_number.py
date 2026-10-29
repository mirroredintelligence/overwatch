"""ChangeReporterNumber: point a service's reports at a new mobile, for cover or until changed
(U16).

STUB (red commit): the names exist so the unit tests fail on their assertions. The build follows in
the next commit.
"""

from datetime import datetime
from enum import StrEnum

from diucs.domain.model.people import PractitionerRole


class CoverDuration(StrEnum):
    TODAY = "today"
    THIS_WEEK = "this-week"
    UNTIL_CHANGED = "until-changed"


def cover_until(duration: CoverDuration, now: datetime) -> datetime | None:
    raise NotImplementedError


def effective_reporter_practitioner_id(role: PractitionerRole, now: datetime) -> str:
    raise NotImplementedError


def check_new_mobile(number: str) -> str:
    raise NotImplementedError
