"""The support-access ticket flow, end to end against stand-ins (TEN-075, TEN-084, DEC-134 item 5).

A support person asks one tenant for access with a reason; the tenant's administrator approves or
refuses; an approval issues the one-time code of the guard; the support person opens the access
with it. Every step is in the tenant's chain and in the platform's, a request lapses, a code lapses,
an access lapses, and an administrator can take any of them back. Another tenant's administrator
and another support person see and do nothing. The guard is the real one; the store is a recording
stand-in with the real compare and set (`tests/support/ticket_rig.py`).
"""

from datetime import timedelta

import pytest

from diucs.application.cross_tenant_guard import (
    AuthoriseCommand,
    CrossTenantDenied,
    EndAccessCommand,
)
from diucs.application.tenancy import bind_tenant, current_scope_or_none
from diucs.application.use_cases.cross_tenant_tickets import (
    CancelTicketCommand,
    DecideTicketCommand,
    OpenTicketCommand,
    RequestTicketCommand,
    UseTicketCommand,
)
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, InvalidTransition, NotFound, ValidationFailed
from diucs.domain.model.tenant import SuspendMode, SuspendReason, TenantStatus
from diucs.domain.rules.support import SUPPORT_ACCESS_VALID_FOR, SUPPORT_CODE_VALID_FOR
from diucs.domain.rules.support_ticket import PENDING_VALID_FOR, ReasonCode, TicketState
from tests.support.tenant_samples import make_tenant
from tests.support.ticket_rig import (
    NOW,
    OTHER_PRINCIPAL,
    PRINCIPAL,
    REASON,
    REF,
    Rig,
    admin,
    rig,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


def ask(
    tenant: str = "tenant-a", principal: object = PRINCIPAL, **changes: object
) -> RequestTicketCommand:
    base: dict[str, object] = {
        "principal": principal,
        "tenant_id": tenant,
        "reason_code": ReasonCode.SERVICE_FAULT,
        "reason": REASON,
        "reference": "HD-1042",
    }
    return RequestTicketCommand(**{**base, **changes})  # type: ignore[arg-type]


async def requested(r: Rig, tenant: str = "tenant-a", principal: object = PRINCIPAL) -> str:
    return (await r.request.execute(ask(tenant, principal))).id


async def approved(
    r: Rig, tenant: str = "tenant-a", principal: object = PRINCIPAL
) -> tuple[str, str]:
    ticket_id = await requested(r, tenant, principal)
    result = await r.approve(ticket_id, tenant)
    return ticket_id, result.code


def decide(
    ticket_id: str, tenant: str = "tenant-a", role: Role = Role.TENANT_ADMIN
) -> DecideTicketCommand:
    return DecideTicketCommand(actor=admin(tenant, role=role), ticket_id=ticket_id)


# ---------------------------------------------------------------- asking


async def test_a_support_person_asks_one_tenant_and_both_chains_say_so() -> None:
    r = rig()

    ticket = await r.request.execute(ask())

    assert ticket.state is TicketState.PENDING
    assert (ticket.tenant_id, ticket.requested_by_ref) == ("tenant-a", REF)
    assert ticket.valid_until == NOW + PENDING_VALID_FOR
    assert r.world.actions("tenant-a") == ["support-ticket-requested"]
    assert [e.action for e in r.platform.entries] == ["support-ticket-requested"]
    (entry,) = r.world.chain("tenant-a")
    assert entry.entity_ids == (ticket.id,)
    assert entry.snapshot == {"ticket": ticket.id, "reason_code": "service-fault"}
    assert r.world.chain("tenant-b") == []
    assert current_scope_or_none() is None


async def test_the_reason_text_is_in_the_ticket_and_in_neither_chain() -> None:
    r = rig()
    await r.request.execute(ask())

    chains = repr(r.world.chain("tenant-a")) + repr(r.platform.entries)

    assert REASON not in chains and "HD-1042" not in chains


async def test_a_tenant_that_is_not_open_is_refused_and_nothing_is_stored() -> None:
    suspended = make_tenant(
        TenantStatus.SUSPENDED,
        id="tenant-c",
        epoch=2,
        suspend_mode=SuspendMode.BLOCKED,
        suspend_reason=SuspendReason.CONTRACT,
        suspended_at=NOW,
    )
    r = rig(
        {
            "tenant-a": make_tenant(id="tenant-a"),
            "tenant-c": suspended,
            "tenant-p": make_tenant(TenantStatus.PROVISIONING, id="tenant-p"),
        }
    )

    for tenant in ("tenant-c", "tenant-p", "tenant-zz", "net-alliance", "Not A Tenant"):
        with pytest.raises(CrossTenantDenied):
            await r.request.execute(ask(tenant))

    assert r.tickets.rows == {} and r.platform.entries == [] and r.world.chains == {}


@pytest.mark.parametrize("who", ["an admin", "a string", "none"])
async def test_only_a_platform_principal_asks(who: str) -> None:
    r = rig()
    principal = {"an admin": admin(), "a string": REF, "none": None}[who]

    with pytest.raises(CrossTenantDenied):
        await r.request.execute(ask(principal=principal))

    assert r.tickets.rows == {}


@pytest.mark.parametrize(
    "changes",
    [
        {"reason": "too short"},
        {"reason": "Please ring the patient on 07700 900123 about this"},
        {"reason": "x" * 201},
        {"reference": "has space"},
        {"reason_code": "made-up"},
    ],
)
async def test_a_bad_request_is_refused_before_anything_is_stored(
    changes: dict[str, object],
) -> None:
    r = rig()

    with pytest.raises(ValidationFailed):
        await r.request.execute(ask(**changes))

    assert r.tickets.rows == {} and r.platform.entries == []


async def test_one_live_ticket_per_person_and_tenant_but_another_tenant_or_person_may_ask() -> None:
    r = rig()
    await requested(r)

    with pytest.raises(Conflict):
        await r.request.execute(ask())

    assert (await r.request.execute(ask("tenant-b"))).tenant_id == "tenant-b"
    assert (await r.request.execute(ask(principal=OTHER_PRINCIPAL))).requested_by_ref != REF


async def test_a_lapsed_or_cancelled_request_does_not_block_the_next() -> None:
    r = rig()
    first = await requested(r)
    r.clock.advance(PENDING_VALID_FOR + timedelta(seconds=1))

    second = (await r.request.execute(ask())).id
    await r.cancelling.execute(CancelTicketCommand(PRINCIPAL, second))
    third = (await r.request.execute(ask())).id

    assert len({first, second, third}) == 3


async def test_a_request_the_chains_cannot_record_is_withdrawn() -> None:
    r = rig()
    r.platform.fail_next = True

    with pytest.raises(ConnectionError):
        await r.request.execute(ask())

    (ticket,) = r.tickets.rows.values()
    assert ticket.state is TicketState.CANCELLED
    assert r.world.chains == {}


# ---------------------------------------------------------------- who sees what


async def test_each_side_lists_its_own_tickets_and_no_others() -> None:
    r = rig()
    a = await requested(r, "tenant-a")
    b = await requested(r, "tenant-b")
    other = await requested(r, "tenant-a", OTHER_PRINCIPAL)

    mine = await r.listing.for_principal(PRINCIPAL)
    others = await r.listing.for_principal(OTHER_PRINCIPAL)
    with bind_tenant("tenant-a"):
        of_a = await r.listing.for_tenant(admin("tenant-a"))
    with bind_tenant("tenant-b"):
        of_b = await r.listing.for_tenant(admin("tenant-b"))

    assert {v.ticket.id for v in mine} == {a, b}
    assert {v.ticket.id for v in others} == {other}
    assert {v.ticket.id for v in of_a} == {a, other}
    assert {v.ticket.id for v in of_b} == {b}


async def test_another_tenants_administrator_reads_and_decides_nothing_of_this_ticket() -> None:
    r = rig()
    ticket_id = await requested(r, "tenant-a")

    with bind_tenant("tenant-b"):
        with pytest.raises(NotFound):
            await r.reading.for_tenant(admin("tenant-b"), ticket_id)
        with pytest.raises(NotFound):
            await r.approving.execute(decide(ticket_id, "tenant-b"))
        with pytest.raises(NotFound):
            await r.refusing.execute(decide(ticket_id, "tenant-b"))
        with pytest.raises(NotFound):
            await r.revoking.execute(decide(ticket_id, "tenant-b"))

    assert r.tickets.rows[ticket_id].state is TicketState.PENDING
    assert r.cache_names("tenant-a") == frozenset() and r.cache_names("tenant-b") == frozenset()


async def test_another_support_persons_ticket_is_not_theirs() -> None:
    r = rig()
    ticket_id = await requested(r)

    with pytest.raises(CrossTenantDenied):
        await r.reading.for_principal(OTHER_PRINCIPAL, ticket_id)
    with pytest.raises(CrossTenantDenied):
        await r.cancelling.execute(CancelTicketCommand(OTHER_PRINCIPAL, ticket_id))
    with pytest.raises(CrossTenantDenied):
        await r.opening.execute(OpenTicketCommand(OTHER_PRINCIPAL, ticket_id, "AAAA-AAAA"))
    with pytest.raises(CrossTenantDenied):
        await r.reading.for_principal(PRINCIPAL, "no-such-ticket")


@pytest.mark.parametrize("role", [role for role in Role if role is not Role.TENANT_ADMIN])
async def test_no_other_role_decides_or_lists_for_a_tenant(role: Role) -> None:
    r = rig()
    ticket_id = await requested(r)
    actor = admin(role=role)

    with bind_tenant("tenant-a"):
        with pytest.raises(CrossTenantDenied):
            await r.listing.for_tenant(actor)
        with pytest.raises(CrossTenantDenied):
            await r.reading.for_tenant(actor, ticket_id)
        for use_case in (r.approving, r.refusing, r.revoking):
            with pytest.raises(CrossTenantDenied):
                await use_case.execute(DecideTicketCommand(actor=actor, ticket_id=ticket_id))

    assert r.tickets.rows[ticket_id].state is TicketState.PENDING
    assert r.cache_names("tenant-a") == frozenset()


async def test_a_listing_shows_a_live_ticket_whose_time_has_come_as_expired() -> None:
    r = rig()
    ticket_id = await requested(r)
    r.clock.advance(PENDING_VALID_FOR)

    (view,) = await r.listing.for_principal(PRINCIPAL)

    assert view.ticket.id == ticket_id
    assert view.ticket.state is TicketState.PENDING and view.state is TicketState.EXPIRED


# ---------------------------------------------------------------- deciding


async def test_an_approval_issues_the_code_once_and_records_the_decision_in_both_chains() -> None:
    r = rig()
    ticket_id = await requested(r)

    result = await r.approve(ticket_id)

    assert len(result.code) == 9 and result.code[4] == "-"
    assert result.code_expires_at == NOW + SUPPORT_CODE_VALID_FOR
    ticket = r.tickets.rows[ticket_id]
    assert ticket.state is TicketState.APPROVED
    assert ticket.decided_by_ref == "admin-ref-0001"
    assert ticket.valid_until == NOW + SUPPORT_CODE_VALID_FOR
    assert r.world.actions("tenant-a") == [
        "support-ticket-requested",
        "support-access-code-issued",
        "support-ticket-approved",
    ]
    assert [e.action for e in r.platform.entries] == [
        "support-ticket-requested",
        "support-ticket-approved",
    ]
    approval = r.platform.entries[-1]
    assert (approval.principal_ref, approval.tenant_id) == ("admin-ref-0001", "tenant-a")


async def test_the_code_is_in_no_ticket_no_chain_and_no_printed_form() -> None:
    r = rig()
    ticket_id = await requested(r)
    result = await r.approve(ticket_id)
    plain = result.code.replace("-", "")

    everything = (
        repr(r.tickets.rows) + repr(r.world.chains) + repr(r.platform.entries) + repr(result)
    )

    assert result.code not in everything and plain not in everything
    assert r.tickets.rows[ticket_id].grant_hash is not None


async def test_the_approval_of_a_ticket_that_is_not_pending_issues_no_code() -> None:
    r = rig()
    ticket_id, _ = await approved(r)
    names = r.cache_names("tenant-a")

    with bind_tenant("tenant-a"), pytest.raises(InvalidTransition):
        await r.approving.execute(decide(ticket_id))

    assert r.cache_names("tenant-a") == names


async def test_a_request_that_has_lapsed_cannot_be_approved_and_issues_no_code() -> None:
    r = rig()
    ticket_id = await requested(r)
    r.clock.advance(PENDING_VALID_FOR + timedelta(minutes=1))

    with bind_tenant("tenant-a"), pytest.raises(InvalidTransition):
        await r.approving.execute(decide(ticket_id))

    assert r.cache_names("tenant-a") == frozenset()


async def test_an_approval_that_loses_the_race_takes_its_code_back() -> None:
    r = rig()
    ticket_id = await requested(r)
    r.tickets.fail_next_move = True

    with bind_tenant("tenant-a"), pytest.raises(Conflict):
        await r.approving.execute(decide(ticket_id))

    # The code that was made is no longer held: its grant is gone from the tenant's names.
    assert [k for k in r.cache_names("tenant-a") if "support-grant" in k] == []
    assert "support-access-code-withdrawn" in r.world.actions("tenant-a")
    assert r.tickets.rows[ticket_id].state is TicketState.PENDING


async def test_an_approval_that_cannot_be_recorded_does_not_stand() -> None:
    r = rig()
    ticket_id = await requested(r)
    r.world.fail_tenant_audit_on = frozenset({"support-ticket-approved"})

    with bind_tenant("tenant-a"), pytest.raises(ConnectionError):
        await r.approving.execute(decide(ticket_id))

    assert r.tickets.rows[ticket_id].state is TicketState.REVOKED
    assert [k for k in r.cache_names("tenant-a") if "support-grant" in k] == []


async def test_a_refusal_is_final_and_issues_nothing() -> None:
    r = rig()
    ticket_id = await requested(r)

    with bind_tenant("tenant-a"):
        refused = await r.refusing.execute(decide(ticket_id))
        with pytest.raises(InvalidTransition):
            await r.refusing.execute(decide(ticket_id))
        with pytest.raises(InvalidTransition):
            await r.approving.execute(decide(ticket_id))

    assert refused.state is TicketState.REFUSED and refused.decided_by_ref == "admin-ref-0001"
    assert r.cache_names("tenant-a") == frozenset()
    assert r.world.actions("tenant-a") == ["support-ticket-requested", "support-ticket-refused"]
    assert [e.action for e in r.platform.entries][-1] == "support-ticket-refused"


async def test_a_refused_ticket_cannot_be_opened_even_with_a_guess() -> None:
    r = rig()
    ticket_id = await requested(r)
    with bind_tenant("tenant-a"):
        await r.refusing.execute(decide(ticket_id))

    with pytest.raises(CrossTenantDenied):
        await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, "AAAA-AAAA"))


async def test_the_support_person_cancels_what_nobody_has_decided_and_nothing_else() -> None:
    r = rig()
    pending = await requested(r, "tenant-a")
    decided, _ = await approved(r, "tenant-b")

    cancelled = await r.cancelling.execute(CancelTicketCommand(PRINCIPAL, pending))
    with pytest.raises(InvalidTransition):
        await r.cancelling.execute(CancelTicketCommand(PRINCIPAL, decided))

    assert cancelled.state is TicketState.CANCELLED
    assert r.world.actions("tenant-a") == ["support-ticket-requested", "support-ticket-cancelled"]


# ---------------------------------------------------------------- opening


async def test_the_code_opens_one_access_for_one_tenant_and_an_hour_and_the_ticket_names_it() -> (
    None
):
    r = rig()
    ticket_id, code = await approved(r)
    r.clock.advance(timedelta(minutes=10))

    opened = await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, code))

    assert opened.ticket.state is TicketState.OPENED
    assert opened.ticket.access_id == opened.elevation.access_id
    assert opened.elevation.tenant_id == "tenant-a"
    assert opened.elevation.expires_at == NOW + timedelta(minutes=10) + SUPPORT_ACCESS_VALID_FOR
    assert opened.ticket.valid_until == opened.elevation.expires_at
    assert r.world.actions("tenant-a") == [
        "support-ticket-requested",
        "support-access-code-issued",
        "support-ticket-approved",
        "support-access-opened",
        "support-ticket-opened",
    ]
    assert [e.action for e in r.platform.entries] == [
        "support-ticket-requested",
        "support-ticket-approved",
        "support-access-opened",
        "support-ticket-opened",
    ]
    assert r.platform.entries[-1].access_id == opened.elevation.access_id


async def test_a_code_opens_once() -> None:
    r = rig()
    ticket_id, code = await approved(r)
    await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, code))

    with pytest.raises(CrossTenantDenied):
        await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, code))


async def test_a_ticket_nobody_approved_opens_nothing_and_does_not_touch_the_guard() -> None:
    r = rig()
    ticket_id = await requested(r)

    with pytest.raises(CrossTenantDenied):
        await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, "AAAA-AAAA"))

    assert r.platform.entries[-1].action == "support-ticket-requested"
    assert r.cache_names("tenant-a") == frozenset()


async def test_a_wrong_code_opens_nothing_and_leaves_the_ticket_approved() -> None:
    r = rig()
    ticket_id, _ = await approved(r)

    with pytest.raises(CrossTenantDenied):
        await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, "AAAA-AAAA"))
    with pytest.raises(CrossTenantDenied):
        await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, "not a code"))

    assert r.tickets.rows[ticket_id].state is TicketState.APPROVED
    assert "support-access-refused" in [e.action for e in r.platform.entries]


async def test_a_code_that_has_lapsed_opens_nothing() -> None:
    r = rig()
    ticket_id, code = await approved(r)
    r.clock.advance(SUPPORT_CODE_VALID_FOR)

    with pytest.raises(CrossTenantDenied):
        await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, code))

    (view,) = await r.listing.for_principal(PRINCIPAL)
    assert view.state is TicketState.EXPIRED


async def test_a_code_issued_for_another_ticket_opens_nothing_under_this_one() -> None:
    r = rig()
    mine, _ = await approved(r, "tenant-a", PRINCIPAL)
    theirs, their_code = await approved(r, "tenant-a", OTHER_PRINCIPAL)

    with pytest.raises(CrossTenantDenied):
        await r.opening.execute(OpenTicketCommand(PRINCIPAL, mine, their_code))

    assert r.tickets.rows[mine].state is TicketState.APPROVED
    # The access that the guard opened for the wrong code was ended at once.
    assert "support-access-ended" in r.world.actions("tenant-a")
    assert r.tickets.rows[theirs].state is TicketState.APPROVED


async def test_an_access_the_ticket_cannot_take_is_ended() -> None:
    r = rig()
    ticket_id, code = await approved(r)
    r.tickets.fail_next_move = True

    with pytest.raises(Conflict):
        await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, code))

    assert r.tickets.rows[ticket_id].state is TicketState.APPROVED
    assert "support-access-ended" in r.world.actions("tenant-a")
    assert [k for k in r.cache_names("tenant-a") if "support-access:" in k] == []


async def test_a_ticket_for_one_tenant_never_opens_another() -> None:
    r = rig()
    a, code_a = await approved(r, "tenant-a")
    b, code_b = await approved(r, "tenant-b")

    # Each code is a grant in its own tenant's names: crossed over they open nothing.
    with pytest.raises(CrossTenantDenied):
        await r.opening.execute(OpenTicketCommand(PRINCIPAL, a, code_b))
    with pytest.raises(CrossTenantDenied):
        await r.opening.execute(OpenTicketCommand(PRINCIPAL, b, code_a))

    assert (
        await r.opening.execute(OpenTicketCommand(PRINCIPAL, a, code_a))
    ).elevation.tenant_id == ("tenant-a")


# ---------------------------------------------------------------- using and ending


async def test_a_call_under_the_access_is_checked_and_recorded_in_both_chains() -> None:
    r = rig()
    ticket_id, code = await approved(r)
    opened = await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, code))

    elevation = await r.using.execute(UseTicketCommand(PRINCIPAL, ticket_id, "read-session"))

    assert elevation.access_id == opened.elevation.access_id
    assert r.world.actions("tenant-a")[-1] == "support-access-used"
    assert r.platform.entries[-1].action == "support-access-used"
    assert r.platform.entries[-1].snapshot == {"action": "read-session"}


async def test_nothing_may_be_used_before_the_ticket_is_open_or_after_it_is_over() -> None:
    r = rig()
    ticket_id, code = await approved(r)
    with pytest.raises(CrossTenantDenied):
        await r.using.execute(UseTicketCommand(PRINCIPAL, ticket_id, "read-session"))
    await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, code))

    r.clock.advance(SUPPORT_ACCESS_VALID_FOR)

    with pytest.raises(CrossTenantDenied):
        await r.using.execute(UseTicketCommand(PRINCIPAL, ticket_id, "read-session"))
    (view,) = await r.listing.for_principal(PRINCIPAL)
    assert view.state is TicketState.EXPIRED


async def test_the_support_person_ends_the_access_and_it_is_gone() -> None:
    r = rig()
    ticket_id, code = await approved(r)
    opened = await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, code))
    r.clock.advance(timedelta(minutes=20))

    ended = await r.ending.execute(CancelTicketCommand(PRINCIPAL, ticket_id))

    assert ended.state is TicketState.ENDED and ended.ended_by.value == "support"  # type: ignore[union-attr]
    assert r.world.actions("tenant-a")[-2:] == ["support-access-ended", "support-ticket-ended"]
    assert [e.action for e in r.platform.entries][-2:] == [
        "support-access-ended",
        "support-ticket-ended",
    ]
    with pytest.raises(CrossTenantDenied):
        await r.guard.authorise(
            AuthoriseCommand(
                principal=PRINCIPAL,
                tenant_id="tenant-a",
                access_id=opened.elevation.access_id,
                action="read-session",
            )
        )
    with pytest.raises(InvalidTransition):
        await r.ending.execute(CancelTicketCommand(PRINCIPAL, ticket_id))


async def test_an_access_cannot_be_ended_before_it_is_open() -> None:
    r = rig()
    ticket_id, _ = await approved(r)

    with pytest.raises(InvalidTransition):
        await r.ending.execute(CancelTicketCommand(PRINCIPAL, ticket_id))


# ---------------------------------------------------------------- taking it back


async def test_the_administrator_takes_back_a_code_before_it_is_used() -> None:
    r = rig()
    ticket_id, code = await approved(r)

    with bind_tenant("tenant-a"):
        revoked = await r.revoking.execute(decide(ticket_id))

    assert revoked.state is TicketState.REVOKED and revoked.ended_by.value == "tenant-admin"  # type: ignore[union-attr]
    with pytest.raises(CrossTenantDenied):
        await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, code))
    assert r.world.actions("tenant-a")[-2:] == [
        "support-access-code-withdrawn",
        "support-ticket-revoked",
    ]
    assert r.platform.entries[-1].action == "support-ticket-revoked"


async def test_the_administrator_ends_an_open_access_at_once() -> None:
    r = rig()
    ticket_id, code = await approved(r)
    await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, code))

    with bind_tenant("tenant-a"):
        revoked = await r.revoking.execute(decide(ticket_id))

    assert revoked.state is TicketState.REVOKED
    with pytest.raises(CrossTenantDenied):
        await r.using.execute(UseTicketCommand(PRINCIPAL, ticket_id, "read-session"))
    assert r.world.actions("tenant-a")[-2:] == ["support-access-revoked", "support-ticket-revoked"]
    assert [e.action for e in r.platform.entries][-2:] == [
        "support-access-revoked",
        "support-ticket-revoked",
    ]


async def test_a_ticket_whose_access_is_already_gone_is_still_marked_revoked() -> None:
    r = rig()
    ticket_id, code = await approved(r)
    opened = await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, code))
    await r.guard.end(
        EndAccessCommand(
            principal=PRINCIPAL, tenant_id="tenant-a", access_id=opened.elevation.access_id
        )
    )

    with bind_tenant("tenant-a"):
        revoked = await r.revoking.execute(decide(ticket_id))

    assert revoked.state is TicketState.REVOKED


async def test_nothing_that_has_not_been_approved_or_has_lapsed_can_be_revoked() -> None:
    r = rig()
    pending = await requested(r, "tenant-a")
    ticket_id, _ = await approved(r, "tenant-b")
    r.clock.advance(SUPPORT_CODE_VALID_FOR)

    with bind_tenant("tenant-a"), pytest.raises(InvalidTransition):
        await r.revoking.execute(decide(pending, "tenant-a"))
    with bind_tenant("tenant-b"), pytest.raises(InvalidTransition):
        await r.revoking.execute(decide(ticket_id, "tenant-b"))


async def test_no_access_stands_once_every_time_has_passed() -> None:
    r = rig()
    ticket_id, code = await approved(r)
    await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, code))

    r.clock.advance(timedelta(days=2))

    with pytest.raises(CrossTenantDenied):
        await r.using.execute(UseTicketCommand(PRINCIPAL, ticket_id, "read-session"))
    with pytest.raises(CrossTenantDenied):
        await r.opening.execute(OpenTicketCommand(PRINCIPAL, ticket_id, code))
    (view,) = await r.listing.for_principal(PRINCIPAL)
    assert view.state is TicketState.EXPIRED
