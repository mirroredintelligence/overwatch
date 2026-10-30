"""The FHIR form of a booking Task (P02, R09): the pure mapping used by the Neo4j booking
repository and the booking routes. No I/O. The status mapping is D13's (`to_fhir`)."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

from diucs.domain.codes import BASE_URL, BookingStatus, Coding, code_system_url, coding_for
from diucs.domain.model.booking import Booking
from diucs.domain.rules.booking_state import from_fhir, to_fhir

BOOKING_REFERENCE_SYSTEM: Final = f"{BASE_URL}booking-reference"

_OUTPUT_TYPE_SYSTEM: Final = code_system_url("booking-output-type")

_TASK: Final = "Task"

_INTENT: Final = "order"

_DECISION: Final = "decision"

_REASON: Final = "reason"

_CONFIRMED_AT: Final = "confirmed-at"


def codeable_to_fhir(member: StrEnum) -> dict[str, Any]:
    """A CodeableConcept with one coding for a local code (the coding's system comes from its enum
    class)."""
    coding: Coding = coding_for(member)
    return {"coding": [{"system": coding.system, "code": coding.code, "display": coding.display}]}


def _iso(value: datetime) -> str:
    """UTC, with Z. Microseconds are kept only when present."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _output_type(code: str) -> dict[str, Any]:
    return {"coding": [{"system": _OUTPUT_TYPE_SYSTEM, "code": code}]}


def _output_entries(booking: Booking) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if booking.status is not BookingStatus.REQUESTED:
        entries.append(
            {
                "type": _output_type(_DECISION),
                "valueCodeableConcept": codeable_to_fhir(booking.status),
            }
        )
    if booking.reason is not None:
        entries.append({"type": _output_type(_REASON), "valueString": booking.reason})
    if booking.confirmed_at is not None:
        entries.append(
            {"type": _output_type(_CONFIRMED_AT), "valueDateTime": _iso(booking.confirmed_at)}
        )
    return entries


def booking_to_fhir(booking: Booking) -> dict[str, Any]:
    """The Task for a booking. No meta: the store sets it."""
    task = to_fhir(booking.status)
    status = from_fhir(task.business_status)
    resource: dict[str, Any] = {
        "resourceType": _TASK,
        "id": booking.id,
        "status": task.status,
        "businessStatus": codeable_to_fhir(status),
        "intent": _INTENT,
        "authoredOn": _iso(booking.requested_at),
        "lastModified": _iso(booking.responded_at or booking.requested_at),
        "identifier": [{"system": BOOKING_REFERENCE_SYSTEM, "value": booking.reference}],
        "restriction": {"period": {"end": _iso(booking.reply_by)}},
        "focus": {"reference": f"ServiceRequest/{booking.case_id}"},
        "owner": {"reference": f"HealthcareService/{booking.service_id}"},
        "requester": {"reference": f"Practitioner/{booking.requester_id}"},
    }
    period: dict[str, Any] = {"start": _iso(booking.requested_at)}
    if booking.responded_at is not None:
        period["end"] = _iso(booking.responded_at)
    resource["executionPeriod"] = period
    if task.status_reason is not None:
        resource["statusReason"] = codeable_to_fhir(from_fhir(task.status_reason))
    entries = _output_entries(booking)
    if entries:
        resource["output"] = entries
    return resource
