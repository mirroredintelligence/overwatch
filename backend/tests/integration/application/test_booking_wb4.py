"""WB4: the booking use cases against the real Neo4j, for what the gap triage (bundle B4) closes:

- the tenant's own booking policy: reply window, phone prompt and withdrawal escalation (KI-450,
  H-493), and the phone prompt time kept on the booking so a page need not guess it;
- the request message kept on the booking, so the card can say what is known of its delivery
  (H-494);
- the advisor's acknowledgement stored on the booking, with who and when (KI-451), for a withdrawal
  and for a not-reached report;
- the change token issued in the same unit as the confirmation (KI-483);
- a decline reason that replays under its key (KI-356);
- the echoes of B4, B5 and B6 to a service whose reporter is on email or push (H-135, KI-357,
  KI-361);
- an expired booking named by its reference, older than the service's latest (KI-453);
- the bookings of a case, and the withdrawals nobody has acknowledged (W8A-K1, H-496), in the
  tenant only.

Sample values only: UCR West, case 1001, the rig's reporter. No patient data.
"""

import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.tokens import LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.respond_to_booking import (
    ChangeLinkRequest,
    RespondToBooking,
    RespondToBookingCommand,
    SetDeclineReason,
    SetDeclineReasonCommand,
)
from diucs.application.use_cases.tenant_config import (
    ApproveConfigCommand,
    ApproveTenantConfig,
    DraftConfigCommand,
    DraftTenantConfig,
)
from diucs.application.use_cases.withdraw_booking import (
    AcknowledgeWithdrawal,
    AcknowledgeWithdrawalCommand,
    ReportNotReached,
    ReportNotReachedCommand,
    WithdrawBooking,
    WithdrawBookingCommand,
)
from diucs.application.work import WorkKind
from diucs.domain.codes import (
    BookingStatus,
    Channel,
    DeclineReason,
    NotReachedReason,
    ReportSource,
    Role,
    WithdrawReason,
)
from diucs.domain.errors import Conflict
from diucs.domain.model.booking import Booking
from tests.support.actors import ACTOR_TENANT
from tests.support.booking_rig import (
    ADVISOR,
    REPORTER,
    SECRETS,
    SERVICE_ID,
    at,
    open_case,
    request,
    sealer,
    seed_world,
    set_reporter_channel,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

OTHER_ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="advisor-2",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
CHANGE = "booking-change"


def _tag(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", key)


def respond_use_case(
    factory: UnitOfWorkFactory, driver: AsyncDriver, now: datetime, *, tokens: bool = False
) -> RespondToBooking:
    clock = FixedClock(now)

    def issue(repo: object) -> LinkTokenService:
        return LinkTokenService(repo, SECRETS, clock)  # type: ignore[arg-type]

    return RespondToBooking(
        factory,
        DriverIdempotencyStore(driver),
        clock,
        SequentialIds(f"rp{now.hour}{now.minute}"),
        sealer(),
        link_tokens=issue if tokens else None,
    )


def reply(
    key: str,
    booking_id: str,
    decision: str,
    *,
    reason: DeclineReason | None = None,
    change_link: ChangeLinkRequest | None = None,
) -> RespondToBookingCommand:
    return RespondToBookingCommand(
        idempotency_key=key,
        actor=REPORTER,
        booking_id=booking_id,
        decision=decision,  # type: ignore[arg-type]
        reason=reason,
        channel=ReportSource.TEXT,
        change_link=change_link,
    )


async def booking_of(factory: UnitOfWorkFactory, booking_id: str) -> Booking:
    async with factory() as uow:
        booking = await uow.bookings.get(booking_id)
    assert booking is not None
    return booking


async def echoes(factory: UnitOfWorkFactory) -> list[tuple[str, Channel]]:
    """The message id and channel of every queued SendMessage, oldest first."""
    async with factory() as uow:
        messages = await uow.outbox.pending(200)
    return [
        (m.payload["message_id"], Channel(m.payload["channel"]))
        for m in messages
        if m.event_type == "SendMessage"
    ]


async def _confirmed(factory: UnitOfWorkFactory, driver: AsyncDriver, key: str) -> str:
    booked = await request(factory, driver, key)
    await respond_use_case(factory, driver, at(14, 19)).execute(
        reply(f"rp-{key}", booked.booking_id, "confirm")
    )
    return booked.booking_id


async def _withdrawn(factory: UnitOfWorkFactory, driver: AsyncDriver, key: str) -> str:
    booking_id = await _confirmed(factory, driver, key)
    await WithdrawBooking(
        factory, DriverIdempotencyStore(driver), FixedClock(at(14, 41)), SequentialIds(f"wd{key}")
    ).execute(
        WithdrawBookingCommand(
            idempotency_key=f"wd-{key}",
            actor=REPORTER,
            booking_id=booking_id,
            reason=WithdrawReason.STAFFING,
        )
    )
    return booking_id


async def _not_reached(factory: UnitOfWorkFactory, driver: AsyncDriver, key: str) -> str:
    booking_id = await _confirmed(factory, driver, key)
    await ReportNotReached(factory, DriverIdempotencyStore(driver), FixedClock(at(14, 41))).execute(
        ReportNotReachedCommand(
            idempotency_key=f"nr-{key}",
            actor=REPORTER,
            booking_id=booking_id,
            reason=NotReachedReason.NO_ANSWER,
        )
    )
    return booking_id


def acknowledge_use_case(
    factory: UnitOfWorkFactory, driver: AsyncDriver, now: datetime
) -> AcknowledgeWithdrawal:
    return AcknowledgeWithdrawal(factory, DriverIdempotencyStore(driver), FixedClock(now))


def _ack(key: str, booking_id: str, actor: Actor = ADVISOR) -> AcknowledgeWithdrawalCommand:
    return AcknowledgeWithdrawalCommand(idempotency_key=key, actor=actor, booking_id=booking_id)


# -- the tenant's own policy ------------------------------------------------------------------


async def _config_in_force(factory: UnitOfWorkFactory) -> None:
    """A configuration approved by two people other than its author: a reply window of 20 minutes
    (the default is 10), a phone prompt after 8 (5) and an escalation after 30 (10)."""

    def person(ref: str) -> Actor:
        return Actor(
            role=Role.OWNER,
            practitioner_id=ref,
            device_id=None,
            channel="web",
            service_ids=frozenset(),
            tenant_id=ACTOR_TENANT,
        )

    roles = frozenset({Role.OWNER})
    clock = FixedClock(at(14, 0))
    drafted = await DraftTenantConfig(factory, clock, roles).execute(
        DraftConfigCommand(
            person("prac-lead-1"),
            0,
            {
                "bookingReplyWindowMinutes": 20,
                "bookingPhonePromptMinutes": 8,
                "withdrawalEscalateMinutes": 30,
            },
        )
    )
    for approver in ("prac-owner-1", "prac-owner-2"):
        await ApproveTenantConfig(factory, clock, roles).execute(
            ApproveConfigCommand(person(approver), drafted.version)
        )


async def test_a_request_takes_its_reply_window_and_phone_prompt_from_the_tenant(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    await _config_in_force(uow_factory)

    booked = await request(uow_factory, neo4j_driver, "wb4-policy")

    assert booked.reply_by == at(14, 16) + timedelta(minutes=20)
    assert booked.phone_prompt_at == at(14, 16) + timedelta(minutes=8)
    booking = await booking_of(uow_factory, booked.booking_id)
    assert booking.reply_by == booked.reply_by
    assert booking.phone_prompt_at == booked.phone_prompt_at
    async with uow_factory() as uow:
        timers = {w.kind: w.due_at for w in await uow.scheduled_work.for_about(booking.id)}
    assert timers[WorkKind.BOOKING_EXPIRE] == booked.reply_by
    assert timers[WorkKind.BOOKING_PHONE_PROMPT] == booked.phone_prompt_at


async def test_a_tenant_with_no_configuration_keeps_the_ten_and_five_minutes(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)

    booked = await request(uow_factory, neo4j_driver, "wb4-default")

    assert booked.reply_by == at(14, 26)
    assert booked.phone_prompt_at == at(14, 21)
    assert (await booking_of(uow_factory, booked.booking_id)).phone_prompt_at == at(14, 21)


async def test_the_other_tenant_does_not_get_this_tenants_policy(
    uow_factory: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    clean_graph: None,
) -> None:
    from diucs.application.tenant_settings import read_policy
    from diucs.domain.model.tenant_policy import DEFAULT_POLICY

    await seed_world(uow_factory, neo4j_driver)
    await _config_in_force(uow_factory)

    async with uow_factory_b() as uow_b:
        policy_b = await read_policy(uow_b)
    async with uow_factory() as uow_a:
        policy_a = await read_policy(uow_a)

    assert policy_a.booking_reply_window == timedelta(minutes=20)
    assert policy_b == DEFAULT_POLICY


async def test_a_withdrawal_escalates_at_the_tenants_own_window(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    await _config_in_force(uow_factory)
    booked = await request(uow_factory, neo4j_driver, "wb4-escalate")
    await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
        reply("rp-wb4-escalate", booked.booking_id, "confirm")
    )

    result = await WithdrawBooking(
        uow_factory,
        DriverIdempotencyStore(neo4j_driver),
        FixedClock(at(14, 41)),
        SequentialIds("wd"),
    ).execute(
        WithdrawBookingCommand(
            idempotency_key="wd-wb4-escalate",
            actor=REPORTER,
            booking_id=booked.booking_id,
            reason=WithdrawReason.STAFFING,
        )
    )

    assert result.escalation_due_at == at(14, 41) + timedelta(minutes=30)


# -- what the card needs to know of the request (H-494) ----------------------------------------


async def test_the_booking_keeps_the_id_of_the_message_that_asked_the_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)

    booked = await request(uow_factory, neo4j_driver, "wb4-message")

    booking = await booking_of(uow_factory, booked.booking_id)
    assert booking.request_message_id is not None
    async with uow_factory() as uow:
        communication = await uow.communications.get(booking.request_message_id)
    assert communication is not None
    assert communication.message_id == "B1"
    assert communication.about_id == SERVICE_ID


# -- the acknowledgement is stored (KI-451) ----------------------------------------------------


async def test_acknowledging_a_withdrawal_stores_who_and_when_on_the_booking(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booking_id = await _withdrawn(uow_factory, neo4j_driver, "wb4-ack-w")

    await acknowledge_use_case(uow_factory, neo4j_driver, at(14, 45)).execute(
        _ack("ack-1", booking_id, OTHER_ADVISOR)
    )

    booking = await booking_of(uow_factory, booking_id)
    assert booking.acknowledged_at == at(14, 45)
    assert booking.acknowledged_by == "advisor-2"
    assert booking.status is BookingStatus.WITHDRAWN


async def test_acknowledging_a_not_reached_report_stores_it_too(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booking_id = await _not_reached(uow_factory, neo4j_driver, "wb4-ack-n")

    await acknowledge_use_case(uow_factory, neo4j_driver, at(14, 46)).execute(
        _ack("ack-2", booking_id)
    )

    booking = await booking_of(uow_factory, booking_id)
    assert (booking.acknowledged_at, booking.acknowledged_by) == (at(14, 46), "advisor-1")


async def test_a_second_acknowledgement_by_another_advisor_keeps_the_first(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booking_id = await _withdrawn(uow_factory, neo4j_driver, "wb4-ack-twice")
    await acknowledge_use_case(uow_factory, neo4j_driver, at(14, 45)).execute(
        _ack("ack-3", booking_id)
    )

    await acknowledge_use_case(uow_factory, neo4j_driver, at(14, 50)).execute(
        _ack("ack-4", booking_id, OTHER_ADVISOR)
    )

    booking = await booking_of(uow_factory, booking_id)
    assert (booking.acknowledged_at, booking.acknowledged_by) == (at(14, 45), "advisor-1")


# -- the change token is issued with the confirmation (KI-483) ---------------------------------


async def test_a_confirmation_issues_the_change_token_in_the_same_unit(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "wb4-token")
    change = ChangeLinkRequest(CHANGE, "ab" * 32, timedelta(hours=24))

    result = await respond_use_case(uow_factory, neo4j_driver, at(14, 19), tokens=True).execute(
        reply("rp-wb4-token", booked.booking_id, "confirm", change_link=change)
    )

    assert result.change_token
    async with uow_factory() as uow:
        record = await LinkTokenService(uow.link_tokens, SECRETS, FixedClock(at(14, 20))).resolve(
            result.change_token
        )
    assert record is not None
    assert (record.purpose, record.about_id) == (CHANGE, booked.booking_id)
    assert record.expires_at == at(14, 19) + timedelta(hours=24)


async def test_a_confirmation_that_fails_leaves_no_token_and_no_confirmation(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    """The token and the confirmation commit together or not at all: a crash cannot leave a
    confirmed booking with no change link, or a change link for a booking not confirmed."""
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "wb4-token-fail")
    change = ChangeLinkRequest(CHANGE, "ab" * 32, timedelta(hours=24))

    class Exploding:
        def seal(self, *args: object, **kwargs: object) -> str:
            raise RuntimeError("the sealer failed after the token was issued")

    use_case = RespondToBooking(
        uow_factory,
        DriverIdempotencyStore(neo4j_driver),
        FixedClock(at(14, 19)),
        SequentialIds("rpfail"),
        Exploding(),  # type: ignore[arg-type]
        link_tokens=lambda repo: LinkTokenService(repo, SECRETS, FixedClock(at(14, 19))),
    )
    with pytest.raises(RuntimeError):
        await use_case.execute(
            reply("rp-wb4-token-fail", booked.booking_id, "confirm", change_link=change)
        )

    assert (await booking_of(uow_factory, booked.booking_id)).status is BookingStatus.REQUESTED
    async with uow_factory() as uow:
        assert await uow.link_tokens.open_for_phone(CHANGE, "ab" * 32, at(14, 20)) is None


async def test_a_replayed_confirmation_returns_no_token_and_the_bearer_is_never_stored(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "wb4-token-replay")
    change = ChangeLinkRequest(CHANGE, "ab" * 32, timedelta(hours=24))
    use_case = respond_use_case(uow_factory, neo4j_driver, at(14, 19), tokens=True)
    command = reply("rp-wb4-token-replay", booked.booking_id, "confirm", change_link=change)

    first = await use_case.execute(command)
    second = await use_case.execute(command)

    assert first.change_token and second.change_token is None
    assert (first.status, first.responded_at) == (second.status, second.responded_at)


async def test_a_decline_issues_no_token(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "wb4-no-token")
    change = ChangeLinkRequest(CHANGE, "ab" * 32, timedelta(hours=24))

    result = await respond_use_case(uow_factory, neo4j_driver, at(14, 19), tokens=True).execute(
        reply("rp-wb4-no-token", booked.booking_id, "decline", change_link=change)
    )

    assert result.change_token is None


# -- a decline reason replays (KI-356) ---------------------------------------------------------


def _reason(key: str, booking_id: str, reason: DeclineReason) -> SetDeclineReasonCommand:
    return SetDeclineReasonCommand(
        idempotency_key=key, actor=REPORTER, booking_id=booking_id, reason=reason
    )


def _set_reason_use_case(
    factory: UnitOfWorkFactory, driver: AsyncDriver, now: datetime
) -> SetDeclineReason:
    return SetDeclineReason(factory, DriverIdempotencyStore(driver), FixedClock(now))


async def test_the_same_reason_under_the_same_key_replays_and_is_not_a_conflict(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "wb4-reason")
    await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
        reply("rp-wb4-reason", booked.booking_id, "decline")
    )
    use_case = _set_reason_use_case(uow_factory, neo4j_driver, at(14, 21))
    await use_case.execute(_reason("dr-wb4", booked.booking_id, DeclineReason.FULL))

    await use_case.execute(_reason("dr-wb4", booked.booking_id, DeclineReason.FULL))

    assert (await booking_of(uow_factory, booked.booking_id)).reason == "full"


async def test_the_same_key_for_a_different_reason_is_a_conflict_and_changes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "wb4-reason-2")
    await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
        reply("rp-wb4-reason-2", booked.booking_id, "decline")
    )
    use_case = _set_reason_use_case(uow_factory, neo4j_driver, at(14, 21))
    await use_case.execute(_reason("dr-wb4-2", booked.booking_id, DeclineReason.FULL))

    with pytest.raises(Conflict):
        await use_case.execute(_reason("dr-wb4-2", booked.booking_id, DeclineReason.OTHER))

    assert (await booking_of(uow_factory, booked.booking_id)).reason == "full"


# -- the echoes on email and push (H-135) ------------------------------------------------------


@pytest.mark.parametrize("channel", [Channel.EMAIL, Channel.PUSH])
async def test_a_confirmation_is_echoed_on_the_channel_of_the_reporter(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None, channel: Channel
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    await set_reporter_channel(uow_factory, channel)
    booked = await request(uow_factory, neo4j_driver, f"wb4-echo-b4-{channel.value}")
    await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
        reply(f"rp-b4-{channel.value}", booked.booking_id, "confirm")
    )

    sent = await echoes(uow_factory)

    assert sent[-1] == ("B4", channel)


@pytest.mark.parametrize("channel", [Channel.EMAIL, Channel.PUSH])
async def test_a_decline_is_echoed_on_the_channel_of_the_reporter(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None, channel: Channel
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    await set_reporter_channel(uow_factory, channel)
    booked = await request(uow_factory, neo4j_driver, f"wb4-echo-b5-{channel.value}")
    await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
        reply(f"rp-b5-{channel.value}", booked.booking_id, "decline")
    )

    assert (await echoes(uow_factory))[-1] == ("B5", channel)


@pytest.mark.parametrize("channel", [Channel.EMAIL, Channel.PUSH])
async def test_a_cancellation_is_echoed_on_the_channel_of_the_reporter(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None, channel: Channel
) -> None:
    from diucs.application.use_cases.cancel_booking import CancelBooking, CancelBookingCommand
    from diucs.domain.codes import CancelReason

    await seed_world(uow_factory, neo4j_driver)
    await set_reporter_channel(uow_factory, channel)
    booked = await request(uow_factory, neo4j_driver, f"wb4-echo-b6-{channel.value}")
    await CancelBooking(
        uow_factory,
        DriverIdempotencyStore(neo4j_driver),
        FixedClock(at(14, 18)),
        SequentialIds("cb"),
        sealer(),
    ).execute(
        CancelBookingCommand(
            idempotency_key=f"cb-{channel.value}",
            actor=ADVISOR,
            booking_id=booked.booking_id,
            reason=CancelReason.NO_LONGER_NEEDED,
        )
    )

    assert (await echoes(uow_factory))[-1] == ("B6", channel)


async def test_a_text_reporter_still_gets_the_text_echo(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "wb4-echo-text")
    await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
        reply("rp-wb4-echo-text", booked.booking_id, "confirm")
    )

    assert (await echoes(uow_factory))[-1] == ("B4", Channel.TEXT)


# -- the bookings of a case, and the withdrawals nobody has acknowledged ----------------------


def _ids(bookings: Sequence[Booking]) -> list[str]:
    return [b.id for b in bookings]


async def test_the_bookings_of_a_case_are_listed_newest_first_and_only_that_cases(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    async with uow_factory() as uow:
        await uow.cases.add(open_case("case-1002"))
        await uow.commit()
    first = await request(uow_factory, neo4j_driver, "wb4-case-a")
    await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
        reply("rp-wb4-case-a", first.booking_id, "decline")
    )
    second = await request(uow_factory, neo4j_driver, "wb4-case-b", now=at(14, 30))

    async with uow_factory() as uow:
        for_case = await uow.bookings.for_case("case-1001")
        none = await uow.bookings.for_case("case-1002")
        unknown = await uow.bookings.for_case("no-such-case")

    assert _ids(for_case) == [second.booking_id, first.booking_id]
    assert (none, unknown) == ([], [])


async def test_the_withdrawals_nobody_has_acknowledged_are_listed_until_one_is(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    withdrawn_id = await _withdrawn(uow_factory, neo4j_driver, "wb4-open-w")
    async with uow_factory() as uow:
        before = await uow.bookings.unacknowledged_exceptions()
    assert _ids(before) == [withdrawn_id]

    await acknowledge_use_case(uow_factory, neo4j_driver, at(14, 45)).execute(
        _ack("ack-open", withdrawn_id)
    )

    async with uow_factory() as uow:
        after = await uow.bookings.unacknowledged_exceptions()
    assert after == []


async def test_a_confirmed_or_requested_booking_is_not_an_open_alert(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    await _confirmed(uow_factory, neo4j_driver, "wb4-open-c")

    async with uow_factory() as uow:
        assert await uow.bookings.unacknowledged_exceptions() == []


async def test_the_other_tenant_sees_neither_the_bookings_of_a_case_nor_the_open_alerts(
    uow_factory: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    clean_graph: None,
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booking_id = await _withdrawn(uow_factory, neo4j_driver, "wb4-open-t")

    async with uow_factory_b() as uow_b:
        for_case = await uow_b.bookings.for_case("case-1001")
        alerts = await uow_b.bookings.unacknowledged_exceptions()
    async with uow_factory() as uow_a:
        mine = await uow_a.bookings.unacknowledged_exceptions()

    assert (for_case, alerts) == ([], [])
    assert _ids(mine) == [booking_id]


# -- an expired booking named by its reference, older than the latest (KI-453) -----------------


async def test_a_reply_that_names_an_old_expired_booking_is_told_it_expired(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    from tests.integration.application.test_handle_inbound_text_booking import say

    await seed_world(uow_factory, neo4j_driver)
    old = await request(uow_factory, neo4j_driver, "wb4-old")
    async with uow_factory() as uow:
        waiting = await uow.bookings.get(old.booking_id)
        assert waiting is not None
        await uow.bookings.save(waiting.with_status(BookingStatus.EXPIRED, at(14, 27)))
        await uow.commit()
    # A newer booking of the same service, already closed, with a reference of its own (the rig's
    # random numbers repeat, and a reference may be reused once only closed bookings hold it).
    old_booking = await booking_of(uow_factory, old.booking_id)
    async with uow_factory() as uow:
        await uow.bookings.add(
            replace(
                old_booking,
                id="bk-wb4-newer",
                reference="9876",
                status=BookingStatus.CANCELLED_BEFORE,
                requested_at=at(14, 40),
                reply_by=at(14, 50),
                responded_at=at(14, 41),
            )
        )
        await uow.commit()

    result = await say(
        uow_factory,
        neo4j_driver,
        f"CONFIRMED {old_booking.reference}",
        at(14, 45),
        "in-wb4-453",
    )

    assert result.outcome == "booking-expired"
    assert (await booking_of(uow_factory, old.booking_id)).status is BookingStatus.EXPIRED
