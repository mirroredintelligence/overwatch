"""The support-access ticket: its record, its moves and its time (TEN-075, TEN-084).

A ticket is the request and the decision, not the access. These tests pin what the domain rule
allows: who a ticket is for, the moves that exist and the ones that do not, that every live state
ends by itself (an elapsed ticket reads `expired` whatever was stored), that the reason is a plain
sentence that names no one, and that a code issued for one ticket opens nothing under another.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from diucs.domain.errors import InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.rules.support_ticket import (
    LIVE_STATES,
    PENDING_VALID_FOR,
    EndedBy,
    ReasonCode,
    SupportTicket,
    TicketState,
    approve,
    cancel,
    check_reason,
    effective_state,
    end_access,
    new_ticket,
    open_access,
    refuse,
    revoke,
)

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
SUPPORT = "ref-support-person-0123456789"
ADMIN = "admin-ref-0001"
HASH = "a" * 64
OTHER_HASH = "b" * 64
REASON = "A reporter cannot sign in on the tenant host."


def pending(**changes: object) -> SupportTicket:
    base = new_ticket(
        ticket_id="st-1",
        tenant_id="tenant-a",
        requested_by_ref=SUPPORT,
        reason_code=ReasonCode.SERVICE_FAULT,
        reason=REASON,
        reference="HD-1042",
        now=NOW,
    )
    return replace(base, **changes) if changes else base


def approved(ticket: SupportTicket | None = None) -> SupportTicket:
    return approve(
        ticket or pending(),
        decided_by_ref=ADMIN,
        grant_hash=HASH,
        grant_expires_at=NOW + timedelta(hours=4),
        now=NOW + timedelta(minutes=5),
    )


def opened(ticket: SupportTicket | None = None) -> SupportTicket:
    return open_access(
        ticket or approved(),
        access_id="access-1",
        grant_hash=HASH,
        opened_at=NOW + timedelta(minutes=10),
        expires_at=NOW + timedelta(minutes=70),
    )


# ---------------------------------------------------------------- a new ticket


def test_a_new_ticket_is_pending_and_lapses_after_a_day() -> None:
    ticket = pending()

    assert ticket.state is TicketState.PENDING
    assert ticket.requested_at == NOW
    assert ticket.valid_until == NOW + PENDING_VALID_FOR == NOW + timedelta(hours=24)
    assert (ticket.decided_by_ref, ticket.grant_hash, ticket.access_id) == (None, None, None)


@pytest.mark.parametrize(
    "tenant",
    ["", "Tenant-A", "net-alliance", "platform", "a b", "x" * 40, None, 5],
)
def test_a_ticket_names_a_valid_tenant(tenant: object) -> None:
    with pytest.raises(ValidationFailed):
        pending(tenant_id=tenant)


@pytest.mark.parametrize("ref", ["", "short", "has space in it", "x" * 129, None, 7])
def test_a_ticket_names_its_support_person_by_an_account_reference(ref: object) -> None:
    with pytest.raises(ValidationFailed):
        pending(requested_by_ref=ref)


@pytest.mark.parametrize("moment", [datetime(2026, 10, 30, 9, 0), "2026-10-30", None])
def test_a_ticket_needs_a_timezone_aware_request_time(moment: object) -> None:
    with pytest.raises(ValidationFailed):
        new_ticket(
            ticket_id="st-1",
            tenant_id="tenant-a",
            requested_by_ref=SUPPORT,
            reason_code=ReasonCode.OTHER,
            reason=REASON,
            reference=None,
            now=moment,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------- the reason names no one


@pytest.mark.parametrize(
    "text",
    [
        "Too short",
        "x" * 201,
        "",
        "Contains a <script> tag in it.",
        "Line one\nline two of the reason",
        "Ring Sample Patient on 07700 900123 to check",
        "The postcode DT4 8XX is wrong on a record",
        "Email someone@example.test about the fault",
        "Born on 01/02/1950 and cannot sign in now",
    ],
)
def test_a_reason_that_is_not_a_plain_sentence_or_names_someone_is_refused(text: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_reason(text)

    assert not text or text not in str(refused.value)


def test_a_reason_of_plain_words_is_accepted() -> None:
    assert check_reason(REASON) == REASON
    assert check_reason("Board shows Not updated for every service since the morning.") is not None


@pytest.mark.parametrize("reference", ["HD-1042", "A", "x" * 32, None])
def test_a_helpdesk_reference_is_letters_digits_and_hyphens(reference: str | None) -> None:
    assert pending(reference=reference).reference == reference


@pytest.mark.parametrize("reference", ["", "-start", "has space", "x" * 33, "a/b", 5])
def test_any_other_reference_is_refused(reference: object) -> None:
    with pytest.raises(ValidationFailed):
        pending(reference=reference)


# ---------------------------------------------------------------- the moves


def test_the_tenants_administrator_approves_a_pending_ticket_and_the_code_sets_its_time() -> None:
    ticket = approved()

    assert ticket.state is TicketState.APPROVED
    assert ticket.decided_by_ref == ADMIN
    assert ticket.decided_at == NOW + timedelta(minutes=5)
    assert ticket.grant_hash == HASH
    assert ticket.valid_until == NOW + timedelta(hours=4)


def test_a_refusal_is_final_and_records_who_decided() -> None:
    ticket = refuse(pending(), decided_by_ref=ADMIN, now=NOW + timedelta(minutes=1))

    assert ticket.state is TicketState.REFUSED
    assert ticket.decided_by_ref == ADMIN
    assert ticket.grant_hash is None
    for move in (
        lambda t: approve(
            t,
            decided_by_ref=ADMIN,
            grant_hash=HASH,
            grant_expires_at=NOW + timedelta(hours=4),
            now=NOW + timedelta(minutes=2),
        ),
        lambda t: cancel(t, now=NOW + timedelta(minutes=2)),
        lambda t: revoke(t, now=NOW + timedelta(minutes=2)),
    ):
        with pytest.raises(InvalidTransition):
            move(ticket)


def test_the_support_person_can_withdraw_a_request_nobody_has_decided() -> None:
    ticket = cancel(pending(), now=NOW + timedelta(minutes=3))

    assert ticket.state is TicketState.CANCELLED
    assert (ticket.ended_at, ticket.ended_by) == (NOW + timedelta(minutes=3), EndedBy.SUPPORT)


def test_a_decided_ticket_cannot_be_withdrawn_by_the_request() -> None:
    with pytest.raises(InvalidTransition):
        cancel(approved(), now=NOW + timedelta(minutes=6))


def test_opening_records_the_access_and_the_hour_it_lasts() -> None:
    ticket = opened()

    assert ticket.state is TicketState.OPENED
    assert ticket.access_id == "access-1"
    assert ticket.opened_at == NOW + timedelta(minutes=10)
    assert ticket.valid_until == NOW + timedelta(minutes=70)


def test_a_code_issued_for_another_ticket_opens_nothing_under_this_one() -> None:
    with pytest.raises(NotAllowed):
        open_access(
            approved(),
            access_id="access-1",
            grant_hash=OTHER_HASH,
            opened_at=NOW + timedelta(minutes=10),
            expires_at=NOW + timedelta(minutes=70),
        )


def test_a_pending_ticket_cannot_be_opened() -> None:
    with pytest.raises(InvalidTransition):
        open_access(
            pending(),
            access_id="access-1",
            grant_hash=HASH,
            opened_at=NOW + timedelta(minutes=10),
            expires_at=NOW + timedelta(minutes=70),
        )


def test_the_support_person_ends_an_open_access() -> None:
    ticket = end_access(opened(), by=EndedBy.SUPPORT, now=NOW + timedelta(minutes=30))

    assert ticket.state is TicketState.ENDED
    assert (ticket.ended_at, ticket.ended_by) == (NOW + timedelta(minutes=30), EndedBy.SUPPORT)


def test_the_administrator_revokes_an_approved_code_or_an_open_access() -> None:
    for before in (approved(), opened()):
        ticket = revoke(before, now=NOW + timedelta(minutes=20))

        assert ticket.state is TicketState.REVOKED
        assert ticket.ended_by is EndedBy.TENANT_ADMIN
        assert ticket.ended_at == NOW + timedelta(minutes=20)


def test_a_pending_ticket_cannot_be_revoked_and_an_approved_one_cannot_be_ended() -> None:
    with pytest.raises(InvalidTransition):
        revoke(pending(), now=NOW + timedelta(minutes=1))
    with pytest.raises(InvalidTransition):
        end_access(approved(), by=EndedBy.SUPPORT, now=NOW + timedelta(minutes=6))


@pytest.mark.parametrize("final", ["refused", "cancelled", "ended", "revoked"])
def test_a_finished_ticket_moves_nowhere(final: str) -> None:
    ticket = {
        "refused": lambda: refuse(pending(), decided_by_ref=ADMIN, now=NOW + timedelta(minutes=1)),
        "cancelled": lambda: cancel(pending(), now=NOW + timedelta(minutes=1)),
        "ended": lambda: end_access(opened(), by=EndedBy.SUPPORT, now=NOW + timedelta(minutes=30)),
        "revoked": lambda: revoke(approved(), now=NOW + timedelta(minutes=30)),
    }[final]()
    later = NOW + timedelta(minutes=40)

    for move in (
        lambda t: cancel(t, now=later),
        lambda t: revoke(t, now=later),
        lambda t: end_access(t, by=EndedBy.SUPPORT, now=later),
        lambda t: refuse(t, decided_by_ref=ADMIN, now=later),
    ):
        with pytest.raises(InvalidTransition):
            move(ticket)


# ---------------------------------------------------------------- no standing access


def test_every_live_state_ends_by_itself() -> None:
    assert {TicketState.PENDING, TicketState.APPROVED, TicketState.OPENED} == LIVE_STATES
    for ticket in (pending(), approved(), opened()):
        assert effective_state(ticket, ticket.valid_until - timedelta(seconds=1)) is ticket.state
        assert effective_state(ticket, ticket.valid_until) is TicketState.EXPIRED
        assert effective_state(ticket, ticket.valid_until + timedelta(days=30)) is (
            TicketState.EXPIRED
        )


def test_a_finished_ticket_never_reads_as_expired() -> None:
    ticket = revoke(approved(), now=NOW + timedelta(minutes=10))

    assert effective_state(ticket, NOW + timedelta(days=30)) is TicketState.REVOKED


def test_an_expired_ticket_moves_nowhere_whatever_it_was_stored_as() -> None:
    late = NOW + timedelta(hours=25)
    with pytest.raises(InvalidTransition):
        approve(
            pending(),
            decided_by_ref=ADMIN,
            grant_hash=HASH,
            grant_expires_at=late + timedelta(hours=4),
            now=late,
        )
    with pytest.raises(InvalidTransition):
        open_access(
            approved(),
            access_id="access-1",
            grant_hash=HASH,
            opened_at=NOW + timedelta(hours=5),
            expires_at=NOW + timedelta(hours=6),
        )
    with pytest.raises(InvalidTransition):
        end_access(opened(), by=EndedBy.SUPPORT, now=NOW + timedelta(hours=3))


def test_effective_state_needs_an_aware_time() -> None:
    with pytest.raises(ValidationFailed):
        effective_state(pending(), datetime(2026, 10, 30, 9, 0))


# ---- the record holds what a state needs


def test_a_record_cannot_say_approved_without_a_code_or_opened_without_an_access() -> None:
    with pytest.raises(ValidationFailed):
        pending(state=TicketState.APPROVED, decided_by_ref=ADMIN, decided_at=NOW)
    with pytest.raises(ValidationFailed):
        replace(approved(), state=TicketState.OPENED)
    with pytest.raises(ValidationFailed):
        replace(approved(), decided_by_ref=None)


def test_expired_is_never_stored() -> None:
    with pytest.raises(ValidationFailed):
        pending(state=TicketState.EXPIRED)


def test_a_grant_hash_is_a_hash_and_an_access_id_is_an_id() -> None:
    with pytest.raises(ValidationFailed):
        replace(approved(), grant_hash="not-a-hash")
    with pytest.raises(ValidationFailed):
        replace(opened(), access_id="has space")
