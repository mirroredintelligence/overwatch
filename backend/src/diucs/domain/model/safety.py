"""A safety concern or a problem report, as the graph holds it (U41).

The record holds no free text: a concern's text is in the protected store and the record keeps only
its handle. A concern carries its reference and its owner (the clinical safety officer role); a
problem report carries whether the session was shared.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.safety_report import (
    REPORT_CODES,
    SAFETY_CONCERN_CODE,
    ProblemCategory,
    SafetyConcernCategory,
)

_REFERENCE = re.compile(r"SC-[0-9]{4,}")


def _text(field: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(field, "must be text, not empty")


@dataclass(frozen=True, slots=True)
class SafetyReport:
    id: str
    code: str
    requester_id: str
    category: str
    created_at: datetime
    reference: str | None = None
    focus_id: str | None = None
    text_handle: str | None = None
    owner_role_id: str | None = None
    session_shared: bool | None = None

    def __post_init__(self) -> None:
        _text("id", self.id)
        _text("requester_id", self.requester_id)
        if self.code not in REPORT_CODES:
            raise ValidationFailed("code", "must be a safety concern or a problem report")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValidationFailed("created_at", "must be a timezone-aware datetime")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
        if self.code == SAFETY_CONCERN_CODE:
            self._check_concern()
        else:
            self._check_problem()

    def _check_concern(self) -> None:
        if not isinstance(self.reference, str) or _REFERENCE.fullmatch(self.reference) is None:
            raise ValidationFailed("reference", "a concern has an SC- reference")
        if self.owner_role_id is None:
            raise ValidationFailed("owner_role_id", "a concern has the safety officer as owner")
        if self.session_shared is not None:
            raise ValidationFailed("session_shared", "only a problem report says this")
        try:
            SafetyConcernCategory(self.category)
        except ValueError:
            raise ValidationFailed("category", "not a safety concern category") from None

    def _check_problem(self) -> None:
        if self.reference is not None:
            raise ValidationFailed("reference", "a problem report has no reference")
        if not isinstance(self.session_shared, bool):
            raise ValidationFailed("session_shared", "a problem report says whether it was shared")
        try:
            ProblemCategory(self.category)
        except ValueError:
            raise ValidationFailed("category", "not a problem category") from None
