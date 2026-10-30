"""The echo of a booking reply or cancellation is about the service, never the booking (W2D fix).

The Communication store links a Communication's about id to a HealthcareService with that id, so a
booking id there would create a placeholder service (a unique Resource.id clash). Pure: the sealed
send is a recording stub, so no unit of work is needed.
"""

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from diucs.application import booking_effects
from diucs.application.booking_effects import queue_echo
from diucs.application.ports.outbound.unit_of_work import UnitOfWork
from diucs.application.tenancy import ScopeId
from diucs.domain.codes import BookingStatus, Channel
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.booking import Booking

AT = datetime(2026, 10, 29, 14, 19, tzinfo=UTC)
SCOPE = ScopeId("tenant-a")


def _booking() -> Booking:
    return Booking(
        id="bk-1",
        reference="4821",
        service_id="ucr-west",
        case_id="case-1001",
        requester_id="advisor-1",
        status=BookingStatus.CONFIRMED,
        requested_at=AT,
        reply_by=AT,
    )


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, uow: object, ids: object, sealer: object, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "comm-1"


async def test_the_echo_is_about_the_service_not_the_booking(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(booking_effects, "queue_message", recorder)
    booking = _booking()
    rendered = render(
        MessageId.B4, Channel.TEXT, reference="4821", service="UCR West", confirmed_at="14:19"
    )
    await queue_echo(
        cast(UnitOfWork, object()),
        cast(Any, object()),
        cast(Any, object()),
        scope=SCOPE,
        rendered=rendered,
        booking=booking,
        recipient_role_id="role-1",
        now=AT,
    )
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["about_id"] == "ucr-west"
    assert recorder.calls[0]["about_id"] != booking.id
    assert recorder.calls[0]["recipient_role_id"] == "role-1"
