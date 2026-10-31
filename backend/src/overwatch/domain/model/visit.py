"""A visit offered to a practitioner, and the practitioner's own settings (DEC-1306 to DEC-1309).

A visiting service goes out to the patient. When an advisor offers a requested booking to the people
on the service's round, each of them gets one `VisitOffer`: what is needed, the postcode SECTOR of
the area (never the address), when the answer is wanted by, and the address and contact sealed so
that only the practitioner who accepts can read them. The offer follows the visit to its end
(accepted, on the way, arrived, done or not reached) or to a refusal (declined, expired, withdrawn).

Minimisation (DEC-067, DEC-398, DEC-1308):
- the sector is kept only while the visit can still happen; every end state reduces it to the
  district, which is all a case keeps;
- the sealed details are erased by every end state (done and not reached included), so nothing
  outlives the visit;
- an estimated arrival is one instant that is overwritten, never a series, and is erased on arrival;
- nothing here is a score: no field ranks, times or compares practitioners.

Every datetime must be timezone-aware (lesson L52). Pure: no I/O.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final

from overwatch.domain.codes import Urgency
from overwatch.domain.errors import InvalidTransition, ValidationFailed

ADDRESS_MAX: Final = 200
CONTACT_MAX: Final = 120
ETA_MAX_MINUTES: Final = 240


class VisitState(StrEnum):
    OFFERED = "offered"
    ACCEPTED = "accepted"
    ON_MY_WAY = "on-my-way"
    ARRIVED = "arrived"
    DONE = "done"
    NOT_REACHED = "not-reached"
    DECLINED = "declined"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


ACTIVE_STATES: Final = frozenset({VisitState.ACCEPTED, VisitState.ON_MY_WAY, VisitState.ARRIVED})
"""The visit is the practitioner's to carry out: the address and contact are shown."""

END_STATES: Final = frozenset(
    {
        VisitState.DONE,
        VisitState.NOT_REACHED,
        VisitState.DECLINED,
        VisitState.EXPIRED,
        VisitState.WITHDRAWN,
    }
)

PRACTITIONER_STATUSES: Final = (
    VisitState.ON_MY_WAY,
    VisitState.ARRIVED,
    VisitState.DONE,
    VisitState.NOT_REACHED,
)
"""The four answers of the status list on the accepted-visit screen, in screen order."""

_ALLOWED: Final[dict[VisitState, frozenset[VisitState]]] = {
    VisitState.OFFERED: frozenset(
        {VisitState.ACCEPTED, VisitState.DECLINED, VisitState.EXPIRED, VisitState.WITHDRAWN}
    ),
    VisitState.ACCEPTED: frozenset(
        {
            VisitState.ON_MY_WAY,
            VisitState.ARRIVED,
            VisitState.DONE,
            VisitState.NOT_REACHED,
            VisitState.WITHDRAWN,
        }
    ),
    VisitState.ON_MY_WAY: frozenset(
        {
            VisitState.ON_MY_WAY,
            VisitState.ARRIVED,
            VisitState.DONE,
            VisitState.NOT_REACHED,
            VisitState.WITHDRAWN,
        }
    ),
    VisitState.ARRIVED: frozenset({VisitState.DONE, VisitState.NOT_REACHED, VisitState.WITHDRAWN}),
    **{state: frozenset[VisitState]() for state in END_STATES},
}
"""Forward only. `on-my-way` to `on-my-way` is allowed so that an estimate can be refreshed. A visit
under way can be withdrawn (by the close of a visit nobody finished, or cancelled)."""


def transition(current: VisitState, target: VisitState) -> VisitState:
    """`target`, when the move is allowed; otherwise InvalidTransition (a fixed message)."""
    if not isinstance(current, VisitState) or not isinstance(target, VisitState):
        raise ValidationFailed("state", "not a visit state")
    if target not in _ALLOWED[current]:
        raise InvalidTransition("this visit cannot move to that state")
    return target


class ShiftStatus(StrEnum):
    AVAILABLE = "available"
    ON_A_VISIT = "on-a-visit"
    BREAK = "break"
    OFF_SHIFT = "off-shift"


class LocationChoice(StrEnum):
    TRAVEL = "travel"
    """Share an estimated arrival, only while travelling to a visit."""
    NEVER = "never"


def _aware(field: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must be timezone-aware")


def district_of_sector(sector: str) -> str:
    """The district (outward code) a sector 'DT4 8' belongs to, which is what a case keeps."""
    return sector.split(" ", 1)[0]


@dataclass(frozen=True, slots=True)
class VisitOffer:
    id: str
    booking_id: str
    reference: str
    """The booking's four-digit reference, which the screen calls the visit's number."""
    service_id: str
    practitioner_id: str
    need: str
    """The needs in plain words (`need_words`), never a code and never free text."""
    sector: str
    """The postcode sector, 'DT4 8', while the visit can still happen; the district afterwards."""
    urgency: Urgency
    offered_at: datetime
    expires_at: datetime
    state: VisitState
    state_at: datetime
    sealed_details: str | None = None
    """The address and contact, sealed for this offer, this tenant and this practitioner."""
    eta_at: datetime | None = None
    """When the practitioner expects to arrive: one instant, overwritten, erased on arrival."""

    def __post_init__(self) -> None:
        _aware("offered_at", self.offered_at)
        _aware("expires_at", self.expires_at)
        _aware("state_at", self.state_at)
        if self.eta_at is not None:
            _aware("eta_at", self.eta_at)

    def with_state(self, target: VisitState, at: datetime) -> VisitOffer:
        """The offer after a move to `target` at `at`. An end state erases what the visit no longer
        needs (details, estimate) and reduces the sector to its district; an arrival erases the
        estimate."""
        _aware("at", at)
        state = transition(self.state, target)
        moved = replace(self, state=state, state_at=at)
        if state in END_STATES:
            return replace(
                moved,
                sealed_details=None,
                eta_at=None,
                sector=district_of_sector(self.sector),
            )
        if state is VisitState.ARRIVED:
            return replace(moved, eta_at=None)
        return moved

    def with_eta(self, eta_at: datetime | None) -> VisitOffer:
        if eta_at is not None:
            _aware("eta_at", eta_at)
        return replace(self, eta_at=eta_at)


@dataclass(frozen=True, slots=True)
class VisitSettings:
    """One practitioner's optional shift status and location choice (screens 1 and 4)."""

    practitioner_id: str
    status: ShiftStatus | None
    status_at: datetime | None
    location: LocationChoice

    def __post_init__(self) -> None:
        if self.status_at is not None:
            _aware("status_at", self.status_at)


def default_settings(practitioner_id: str) -> VisitSettings:
    """No status, and the location is not shared (the screen's promise)."""
    return VisitSettings(practitioner_id, None, None, LocationChoice.NEVER)
