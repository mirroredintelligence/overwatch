"""The booking timer handlers route each scheduled kind to its use case (U19). Pure: the use cases
are recording stubs here, and the stored behaviour is tested in tests/integration.
"""

from datetime import UTC, datetime
from dataclasses import dataclass, field
from typing import Any

from diucs.application.actor import Actor
from diucs.application.use_cases.booking_timers import (
    SYSTEM_ACTOR,
    BookingPhonePromptCommand,
    ExpireBookingCommand,
    TimerResult,
    booking_timer_handlers,
)
from diucs.application.work import ScheduledWork, WorkKind
from diucs.domain.codes import Role

DUE = datetime(2026, 10, 29, 14, 26, tzinfo=UTC)


@dataclass
class _Recorder:
    commands: list[Any] = field(default_factory=list)

    async def execute(self, command: Any) -> TimerResult:
        self.commands.append(command)
        return TimerResult(acted=True)


def _work(kind: WorkKind, work_id: str = "w-1", about_id: str = "bk-1") -> ScheduledWork:
    return ScheduledWork(
        id=work_id,
        kind=kind,
        due_at=DUE,
        about_id=about_id,
        sequence_number=None,
        status="scheduled",
    )


async def test_the_expiry_work_is_routed_to_expire_booking_with_its_work_and_booking() -> None:
    prompt, expire = _Recorder(), _Recorder()
    handlers = booking_timer_handlers(prompt, expire)
    await handlers[WorkKind.BOOKING_EXPIRE](_work(WorkKind.BOOKING_EXPIRE))
    assert expire.commands == [ExpireBookingCommand(work_id="w-1", booking_id="bk-1")]
    assert prompt.commands == []


async def test_the_phone_prompt_work_is_routed_to_the_phone_prompt() -> None:
    prompt, expire = _Recorder(), _Recorder()
    handlers = booking_timer_handlers(prompt, expire)
    await handlers[WorkKind.BOOKING_PHONE_PROMPT](_work(WorkKind.BOOKING_PHONE_PROMPT, "w-2"))
    assert prompt.commands == [BookingPhonePromptCommand(work_id="w-2", booking_id="bk-1")]
    assert expire.commands == []


def test_exactly_the_two_booking_kinds_have_a_handler() -> None:
    handlers = booking_timer_handlers(_Recorder(), _Recorder())
    assert set(handlers) == {WorkKind.BOOKING_PHONE_PROMPT, WorkKind.BOOKING_EXPIRE}


def test_the_system_actor_is_the_audit_role_on_the_system_channel_with_no_service() -> None:
    assert SYSTEM_ACTOR == Actor(
        role=Role.AUDIT,
        practitioner_id=None,
        device_id=None,
        channel="system",
        service_ids=frozenset(),
    )
