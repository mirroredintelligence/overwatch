"""Booking Tasks over FHIR (R09) and the advisor's acknowledgement of a withdrawal (R17).

POST /fhir/Task                          open a booking request (RequestBooking, U17); advisor or clinical
GET  /fhir/Task/{id}                     read a booking; a reporter sees the projection of their own service
PUT  /fhir/Task/{id}                     refused: booking status changes only through operations (405)
POST /fhir/Task/{id}/$respond            confirm or decline (RespondToBooking, U18); reporter
POST /fhir/Task/{id}/$cancel             cancel (CancelBooking, U20); advisor or clinical
POST /fhir/Task/{id}/$withdraw           withdraw a confirmed booking (WithdrawBooking, U21); reporter
POST /fhir/Task/{id}/$not-reached        report a confirmed patient not reached (ReportNotReached, U21); reporter
POST /fhir/Task/{id}/$acknowledge        the advisor has seen a withdrawal or not-reached (AcknowledgeWithdrawal,
                                         U21); advisor or clinical (R17)

The routes hold no business rule: each one reads the request's shape, calls one use case and writes
the Task it finds afterwards. The tenant is the signed token's and nothing else (TEN-018): a booking
of another tenant, or of another service for a reporter, answers the same 404 as an unknown id.

The pure helpers below read the request bodies. Each refusal is a ValidationFailed that names only
the element, never the value sent.
"""

from dataclasses import dataclass
from typing import Any, Final, Literal

from diucs.domain.codes import BookingStatus, CancelReason, DeclineReason, NotReachedReason, WithdrawReason

BOOKING_REQUEST: Final = "booking-request"
ACKNOWLEDGED_STATUSES: Final = (BookingStatus.WITHDRAWN, BookingStatus.NOT_REACHED)


@dataclass(frozen=True, slots=True)
class BookingRequestBody:
    """The case and the service of a booking request: the focus and the owner of the Task."""

    case_id: str
    service_id: str


def parse_booking_request(body: Any) -> BookingRequestBody:
    raise NotImplementedError


def parameters_by_name(body: Any) -> dict[str, list[dict[str, Any]]]:
    raise NotImplementedError


def decision_of(grouped: dict[str, list[dict[str, Any]]]) -> Literal["confirm", "decline"]:
    raise NotImplementedError


def decline_reason_of(grouped: dict[str, list[dict[str, Any]]]) -> DeclineReason | None:
    raise NotImplementedError


def cancel_reason_of(grouped: dict[str, list[dict[str, Any]]]) -> CancelReason:
    raise NotImplementedError


def withdraw_reason_of(grouped: dict[str, list[dict[str, Any]]]) -> WithdrawReason:
    raise NotImplementedError


def not_reached_reason_of(grouped: dict[str, list[dict[str, Any]]]) -> NotReachedReason:
    raise NotImplementedError


def check_acknowledgement_body(body: Any) -> None:
    raise NotImplementedError


def acknowledgement_path(status: BookingStatus) -> Literal["withdrawn", "not-reached"] | None:
    raise NotImplementedError
