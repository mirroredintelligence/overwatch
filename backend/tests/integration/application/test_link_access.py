"""Integration tests for link access (L01, DEC-167), against the real Neo4j the harness starts.

A reporter is texted a link (a real prompt, sent by SendPrompts); opening it shows what is on
record and changes nothing; pressing a button records a confirm, a number or "closed" through
ReportCapacity or ConfirmCapacity, exactly once, and a Y never makes an old figure current (H-31,
H-32). A link that is unknown, another tenant's, expired or for another purpose answers as an
expired one. Every assertion reads back through a fresh unit of work or the harness helpers.
Values are synthetic: no patient data.
"""

import asyncio
import re
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.tokens import LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, TenantNotBound, bind_scope, bind_tenant
from diucs.application.use_cases import link_access
from diucs.application.use_cases.link_access import (
    CAPACITY_PURPOSE,
    CsrfRejected,
    LinkGone,
    LinkOutOfRange,
    LinkRateLimited,
    RespondViaLink,
    RespondViaLinkCommand,
    SendTheNumber,
    UnitOfWorkIdempotency,
)
from diucs.application.use_cases.link_access import LinkAction as Action
from diucs.application.use_cases.report_capacity import ReportCapacityResult
from diucs.domain.codes import Channel, ReportFlagReason, ReportSource, ReportType, Status
from diucs.domain.errors import (
    ConfirmLimitReached,
    Conflict,
    LatestReportChanged,
    NotAllowed,
    NotFound,
    NothingToConfirm,
    ValidationFailed,
)
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from tests.support.ladder_rig import PHONE_HASH_1, SECRET, london, reporter, seed_people
from tests.support.link_rig import (
    ANSWER_AT,
    BASE_URL_A,
    CLIENT,
    OTHER_CLIENT,
    PROMPT_AT,
    REPLY_BY,
    LinkRig,
    build_link_rig,
    new_secrets,
    token_hash_of,
    ucr_west,
)
from tests.support.neo4j import read_tx
from tests.support.uow import uow_factory_on

pytestmark = pytest.mark.asyncio(loop_scope="session")

OTHER_PHONE = "cd" * 32


@pytest.fixture
def links(uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str) -> LinkRig:
    """The rig on the run tenant. The unit of work stamps writes with the rig's clock, so the clock
    is shared with the factory."""
    clock = FixedClock(ANSWER_AT)
    return build_link_rig(uow_factory_on(neo4j_driver, clock), neo4j_driver, tenant_id, clock=clock)


async def _prompted(links: LinkRig, **seed: Any) -> str:
    """The service, its reporter and a figure on record, a 10:00 prompt, and the link it carried.
    The clock is left at 10:05, inside the reply window."""
    await links.seed(**seed)
    token = await links.prompt()
    links.clock.set(ANSWER_AT)
    return token


# -- looking at a link -----------------------------------------------------------------------------


async def test_a_link_shows_what_is_recorded_and_changes_nothing(links: LinkRig) -> None:
    token = await _prompted(links)
    before = await links.counts()

    page = await links.view(token)

    assert page.purpose == "capacity-reply"
    assert dict(page.body) == {
        "state": "ok",
        "purpose": "capacity-reply",
        "serviceName": "UCR West",
        "unitLabel": "referrals in the next 2 hrs",
        "recordedValue": 3,
        "asOf": "2026-10-23T07:15:00Z",
        "usualMin": 0,
        "usualMax": 8,
        "replyBy": "2026-10-23T09:30:00Z",
        "nextDue": "2026-10-23T11:00:00Z",
        "csrfToken": links.csrf(token),
    }
    assert await links.counts() == before
    node = await links.token_node(token)
    assert "usedAt" not in node and "burnKey" not in node


async def test_opening_a_link_twice_gives_the_same_page_and_still_changes_nothing(
    links: LinkRig,
) -> None:
    token = await _prompted(links)

    first = await links.view(token)
    second = await links.view(token)

    assert dict(first.body) == dict(second.body)
    assert (await links.latest()).report_type is ReportType.NUMBER


async def test_a_link_for_a_service_with_no_figure_shows_none(links: LinkRig) -> None:
    token = await _prompted(links, figure=None)

    page = await links.view(token)

    assert page.body["recordedValue"] is None
    assert page.body["asOf"] is None
    assert page.body["serviceName"] == "UCR West"


async def test_a_link_opens_until_its_reply_by_time_and_then_is_expired(links: LinkRig) -> None:
    token = await _prompted(links)
    links.clock.set(REPLY_BY - timedelta(seconds=1))
    assert (await links.view(token)).body["state"] == "ok"

    links.clock.set(REPLY_BY)
    with pytest.raises(LinkGone) as gone:
        await links.view(token)

    assert gone.value.state == "expired"


async def test_a_used_link_is_used_before_it_is_expired(links: LinkRig) -> None:
    token = await _prompted(links)
    await links.respond(token, "confirm")
    links.clock.set(REPLY_BY + timedelta(hours=1))

    with pytest.raises(LinkGone) as gone:
        await links.view(token)

    assert gone.value.state == "used"


@pytest.mark.parametrize(
    "token",
    [
        "A" * 23,  # well formed, unknown
        "A" * 22,  # an old base64url-length link, unknown
        "not a token!",  # not URL-safe text
        "",  # nothing
        "A" * 65,  # longer than any token
        "AbC-_9" * 3,  # URL-safe, unknown
    ],
)
async def test_an_unknown_or_malformed_link_is_an_expired_one(links: LinkRig, token: str) -> None:
    await links.seed()

    with pytest.raises(LinkGone) as gone:
        await links.view(token)

    assert gone.value.state == "expired"


async def test_a_link_for_another_purpose_is_an_expired_one(links: LinkRig) -> None:
    await links.seed()
    token = await links.issue(about_id="whatever", purpose="booking-request")

    with pytest.raises(LinkGone) as gone:
        await links.view(token)

    assert gone.value.state == "expired"


@pytest.mark.parametrize(
    "case",
    [
        "no-prompt",
        "no-phone",
        "inactive-service",
        "role-ended",
        "two-people-one-phone",
        "other-role",
    ],
)
async def test_a_link_whose_prompt_service_or_reporter_is_gone_is_an_expired_one(
    links: LinkRig, uow_factory: UnitOfWorkFactory, case: str
) -> None:
    token = await _prompted(links)
    record = await links.token_node(token)
    if case == "no-prompt":
        token = await links.issue(about_id="no-such-communication")
    elif case == "no-phone":
        token = await links.issue(about_id=record["aboutId"], phone_hash=None)
    elif case == "inactive-service":
        async with links.factory() as uow:
            profile = await uow.services.get(links.service_id)
            assert profile is not None
            await uow.services.save(replace(profile, active=False))
            await uow.commit()
    elif case == "role-ended":
        async with links.factory() as uow:
            role = (await uow.people.reporter_roles_for_service(links.service_id, ANSWER_AT))[0]
            await uow.people.save_role(replace(role, period_end=PROMPT_AT))
            await uow.commit()
    elif case == "two-people-one-phone":
        await seed_people(links.factory, reporter(2, PHONE_HASH_1, links.service_id, "dup-"))
    else:  # a token for a prompt that was sent to a different role
        async with links.factory() as uow:
            communication = await uow.communications.get(record["aboutId"])
            assert communication is not None
            await uow.communications.add(
                replace(communication, id="other-role-prompt", recipient_role_id="role-elsewhere")
            )
            await uow.commit()
        token = await links.issue(about_id="other-role-prompt")

    with pytest.raises(LinkGone) as gone:
        await links.view(token)

    assert gone.value.state == "expired"


@pytest.mark.no_tenant
async def test_a_link_cannot_be_looked_at_with_no_tenant_bound(links: LinkRig) -> None:
    with pytest.raises(TenantNotBound):
        await links.view("A" * 23)


# -- answering a link -----------------------------------------------------------------------------


async def test_a_confirm_records_a_confirmed_figure_burns_the_link_and_says_so(
    links: LinkRig,
) -> None:
    token = await _prompted(links)

    response = await links.respond(token, "confirm")

    assert dict(response.body) == {
        "serviceName": "UCR West",
        "value": 3,
        "unitLabel": "referrals in the next 2 hrs",
        "recordedAt": "2026-10-23T09:05:00Z",
        "nextDue": "2026-10-23T11:00:00Z",
    }
    latest = await links.latest()
    assert latest.report_type is ReportType.CONFIRMED
    assert latest.source is ReportSource.LINK
    assert latest.value == 3
    assert latest.performer_role_id == "role-1"
    assert latest.derived_from == "seed-report-1"
    node = await links.token_node(token)
    assert node["usedAt"] is not None
    async with links.factory() as uow:
        audit = [
            r.entry for r in await uow.audit.records() if r.entry.use_case == "ConfirmCapacity"
        ]
    assert [(e.actor.channel, e.actor.role.value) for e in audit] == [("link", "reporter")]


async def test_a_new_number_is_recorded_as_a_number_from_the_link(links: LinkRig) -> None:
    token = await _prompted(links)

    response = await links.respond(token, "number", 5)

    assert response.body["value"] == 5
    latest = await links.latest()
    assert (latest.report_type, latest.source, latest.value) == (
        ReportType.NUMBER,
        ReportSource.LINK,
        5,
    )
    assert (await links.token_node(token))["usedAt"] is not None


async def test_closed_records_the_figure_zero(links: LinkRig) -> None:
    token = await _prompted(links)

    response = await links.respond(token, "closed")

    assert response.body["value"] == 0
    assert (await links.latest()).value == 0


async def test_a_link_answer_goes_through_the_same_use_case_as_a_text(links: LinkRig) -> None:
    """The one audit entry a link answer writes is ReportCapacity's own, naming the link channel;
    the use case writes the status events and the outbox messages as it does for a text."""
    token = await _prompted(links)
    before = await links.counts()

    await links.respond(token, "number", 6)

    after = await links.counts()
    assert after["Observation"] == before["Observation"] + 1
    assert after["AuditEvent"] == before["AuditEvent"] + 1
    assert after["OutboxMessage"] > before["OutboxMessage"]  # CapacityReported
    assert after["Communication"] == before["Communication"]  # no text echo for a link


async def test_a_second_answer_is_used_and_records_nothing(links: LinkRig) -> None:
    token = await _prompted(links)
    await links.respond(token, "number", 5)
    before = await links.counts()

    for action, value in (("number", 5), ("number", 7), ("confirm", None), ("closed", None)):
        with pytest.raises(LinkGone) as gone:
            await links.respond(token, action, value)
        assert gone.value.state == "used"

    assert await links.counts() == before


async def test_an_answer_after_the_reply_by_time_is_expired_and_records_nothing(
    links: LinkRig,
) -> None:
    token = await _prompted(links)
    before = await links.counts()
    links.clock.set(REPLY_BY)

    with pytest.raises(LinkGone) as gone:
        await links.respond(token, "number", 5)

    assert gone.value.state == "expired"
    assert await links.counts() == before


async def test_a_number_outside_the_usual_range_needs_confirming_and_records_nothing(
    links: LinkRig,
) -> None:
    token = await _prompted(links)
    before = await links.counts()

    with pytest.raises(LinkOutOfRange) as refused:
        await links.respond(token, "number", 40)

    assert (refused.value.usual_min, refused.value.usual_max) == (0, 8)
    assert await links.counts() == before
    assert "usedAt" not in await links.token_node(token)  # the link is still open
    assert (await links.view(token)).body["state"] == "ok"


async def test_a_number_outside_the_usual_range_is_recorded_when_confirmed_and_is_flagged(
    links: LinkRig,
) -> None:
    token = await _prompted(links)

    response = await links.respond(token, "number", 40, out_of_range=True)

    assert response.body["value"] == 40
    assert (await links.latest()).value == 40
    async with links.factory() as uow:
        flags = await uow.flags.open_report_flags(links.service_id)
    assert [flag.reason for flag in flags] == [ReportFlagReason.OUT_OF_RANGE_TWICE]


async def test_a_number_inside_the_range_with_confirm_out_of_range_is_not_flagged(
    links: LinkRig,
) -> None:
    token = await _prompted(links)

    await links.respond(token, "number", 4, out_of_range=True)

    async with links.factory() as uow:
        assert await uow.flags.open_report_flags(links.service_id) == []


async def test_closed_for_a_service_whose_usual_range_starts_above_zero_needs_confirming(
    links: LinkRig,
) -> None:
    token = await _prompted(links, profile=ucr_west(usual_range=(2, 8)))

    with pytest.raises(LinkOutOfRange):
        await links.respond(token, "closed")
    response = await links.respond(token, "closed", out_of_range=True)

    assert response.body["value"] == 0


async def test_a_number_within_the_correction_window_is_recorded_as_a_correction(
    links: LinkRig,
) -> None:
    """The same rule as a text: a figure that follows an accepted one within the correction window
    is a correction. The reporter texted 4 at 10:02 and taps 5 at 10:05."""
    token = await _prompted(links)
    await links.rig.report(london(10, 2), value=4)
    links.clock.set(ANSWER_AT)

    response = await links.respond(token, "number", 5)

    assert response.body["value"] == 5
    assert (await links.latest()).value == 5


# -- a Y never makes an old figure current ------------------------------------------------------


async def test_a_y_for_a_figure_older_than_two_hours_at_the_prompt_records_nothing_h31(
    links: LinkRig,
) -> None:
    token = await _prompted(links, figure_at=london(7, 30))  # 2 h 30 min old at 10:00
    before = await links.counts()

    with pytest.raises(SendTheNumber) as refused:
        await links.respond(token, "confirm")

    assert refused.value.reason == "stale"
    assert await links.counts() == before
    assert (await links.latest()).report_type is ReportType.NUMBER
    assert "usedAt" not in await links.token_node(token)
    # The link is still open for the number.
    assert (await links.respond(token, "number", 4)).body["value"] == 4


async def test_a_y_for_a_figure_exactly_two_hours_old_at_the_prompt_is_recorded(
    links: LinkRig,
) -> None:
    token = await _prompted(links, figure_at=london(8, 0))

    response = await links.respond(token, "confirm")

    assert response.body["value"] == 3
    assert (await links.latest()).report_type is ReportType.CONFIRMED


async def test_a_y_after_a_number_was_reported_since_the_prompt_records_nothing_h32(
    links: LinkRig,
) -> None:
    token = await _prompted(links)
    await links.rig.report(london(10, 2), value=6)  # a text number, after the prompt
    links.clock.set(ANSWER_AT)
    before = await links.counts()

    with pytest.raises(SendTheNumber) as refused:
        await links.respond(token, "confirm")

    assert refused.value.reason == "stale"
    assert await links.counts() == before
    assert (await links.latest()).value == 6


async def test_a_y_with_no_figure_on_record_asks_for_the_number(links: LinkRig) -> None:
    token = await _prompted(links, figure=None)
    before = await links.counts()

    with pytest.raises(SendTheNumber) as refused:
        await links.respond(token, "confirm")

    assert refused.value.reason == "no-figure"
    assert await links.counts() == before


async def test_a_third_confirmation_in_a_row_is_refused_and_the_link_stays_open(
    links: LinkRig,
) -> None:
    token = await _prompted(links)
    for minute in (1, 2):  # two earlier Ys by text, for this figure
        await links.text_confirm(f"confirm-{minute}", london(10, minute))
    links.clock.set(ANSWER_AT)
    before = await links.counts()

    with pytest.raises(SendTheNumber) as refused:
        await links.respond(token, "confirm")

    assert refused.value.reason == "limit"
    assert await links.counts() == before
    assert "usedAt" not in await links.token_node(token)


class _Refuses:
    """A stand-in for ReportCapacity or ConfirmCapacity that refuses, for the races a test cannot
    make happen on cue."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def execute(self, command: object) -> object:
        raise self._error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LatestReportChanged("changed", 3, ANSWER_AT), ("send", "changed")),
        (ConfirmLimitReached("limit"), ("send", "limit")),
        (NothingToConfirm("nothing"), ("send", "no-figure")),
        (NotFound("gone"), ("gone", "expired")),
        (NotAllowed("no"), ("gone", "expired")),
        (Conflict("another answer"), ("gone", "used")),
    ],
)
async def test_what_the_use_case_refuses_is_what_the_reporter_is_told(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    error: Exception,
    expected: tuple[str, str],
) -> None:
    clock = FixedClock(ANSWER_AT)
    links = build_link_rig(
        uow_factory_on(neo4j_driver, clock),
        neo4j_driver,
        tenant_id,
        clock=clock,
        reports=_Refuses(error),
        confirms=_Refuses(error),
    )
    token = await _prompted(links)

    for action, value in (("confirm", None), ("number", 5)):
        with pytest.raises(LinkGone if expected[0] == "gone" else SendTheNumber) as refused:
            await links.respond(token, action, value)
        assert getattr(refused.value, "state", None) == expected[1] or (
            getattr(refused.value, "reason", None) == expected[1]
        )
    assert "usedAt" not in await links.token_node(token)  # nothing was recorded, so not burned


# -- once, and only once -------------------------------------------------------------------------


async def test_two_different_answers_at_once_record_exactly_one(links: LinkRig) -> None:
    token = await _prompted(links)
    before = await links.counts()

    outcomes = await asyncio.gather(
        links.respond(token, "confirm"),
        links.respond(token, "number", 5),
        return_exceptions=True,
    )

    recorded = [o for o in outcomes if not isinstance(o, BaseException)]
    refused = [o for o in outcomes if isinstance(o, LinkGone)]
    assert len(recorded) == 1 and len(refused) == 1
    assert refused[0].state == "used"
    after = await links.counts()
    assert after["Observation"] == before["Observation"] + 1
    assert after["AuditEvent"] == before["AuditEvent"] + 1


async def test_the_same_answer_sent_twice_at_once_is_recorded_once(links: LinkRig) -> None:
    token = await _prompted(links)
    before = await links.counts()

    outcomes = await asyncio.gather(
        links.respond(token, "number", 5),
        links.respond(token, "number", 5),
        return_exceptions=True,
    )

    assert all(not isinstance(o, BaseException) for o in outcomes)
    assert outcomes[0].body == outcomes[1].body  # type: ignore[union-attr]
    assert (await links.counts())["Observation"] == before["Observation"] + 1


class _BurnFails(LinkTokenService):
    async def burn(self, token: str, key: str) -> None:
        raise RuntimeError("the burn did not happen")


async def test_a_figure_that_was_stored_before_the_burn_failed_cannot_be_answered_again(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    clock = FixedClock(ANSWER_AT)
    links = build_link_rig(
        uow_factory_on(neo4j_driver, clock),
        neo4j_driver,
        tenant_id,
        clock=clock,
        tokens_class=_BurnFails,
    )
    token = await _prompted(links)

    with pytest.raises(RuntimeError, match="the burn did not happen"):
        await links.respond(token, "number", 5)
    before = await links.counts()

    # The figure is on record, and the link is read as used from then on, burned or not.
    assert (await links.latest()).value == 5
    for action, value in (("number", 6), ("confirm", None)):
        with pytest.raises(LinkGone) as gone:
            await links.respond(token, action, value)
        assert gone.value.state == "used"
    with pytest.raises(LinkGone) as viewed:
        await links.view(token)
    assert viewed.value.state == "used"
    assert await links.counts() == before


# -- the CSRF token --------------------------------------------------------------------------------


@pytest.mark.parametrize("csrf", [None, " ", "0" * 64, "not hex", "é"])
async def test_a_missing_or_wrong_csrf_token_is_refused_and_records_nothing(
    links: LinkRig, csrf: str | None
) -> None:
    token = await _prompted(links)
    before = await links.counts()

    with pytest.raises(CsrfRejected):
        await links.respond(token, "confirm", csrf=csrf)

    assert await links.counts() == before


async def test_another_links_csrf_token_is_refused(links: LinkRig) -> None:
    token = await _prompted(links)
    other = await links.issue(about_id="x")

    with pytest.raises(CsrfRejected):
        await links.respond(token, "confirm", csrf=links.csrf(other))


async def test_the_csrf_token_is_checked_before_anything_is_read(
    links: LinkRig,
) -> None:
    """A wrong token and an unknown link both answer 403, so the check is made from the token text
    alone. The unit of work given here fails if it is ever opened."""

    def unopened() -> Any:
        raise AssertionError("the unit of work was opened")

    use_case = RespondViaLink(
        unopened,
        links.clock,
        links.secrets,
        links.cache,
        lambda repo: LinkTokenService(repo, links.secrets, links.clock),
        links.purposes,
    )

    for token in ("A" * 23, "not a token!", "A" * 65):
        with pytest.raises(CsrfRejected):
            await use_case.execute(
                RespondViaLinkCommand(token, "0" * 64, Action("confirm"), CLIENT)
            )


async def test_a_malformed_answer_is_refused_before_the_cache_or_the_store_is_touched(
    links: LinkRig,
) -> None:
    token = await _prompted(links)
    before = await links.counts()

    with pytest.raises(ValidationFailed):
        await links.respond(token, "number", 1000)

    assert await links.counts() == before


# -- rate limits -----------------------------------------------------------------------------------


async def test_a_tenant_may_make_only_so_many_link_requests_a_minute(
    links: LinkRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(link_access, "REQUESTS_PER_WINDOW", 3)
    token = await _prompted(links)

    for _ in range(3):
        await links.view(token)
    with pytest.raises(LinkRateLimited) as limited:
        await links.view(token)

    assert limited.value.retry_after_seconds == 60
    links.clock.advance(timedelta(seconds=60))
    assert (await links.view(token)).body["state"] == "ok"


async def test_one_address_may_miss_only_so_many_times_and_a_link_that_exists_costs_nothing(
    links: LinkRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(link_access, "BAD_ATTEMPTS_PER_ADDRESS", 3)
    token = await _prompted(links)
    for _ in range(5):  # a real link, however often it is opened, spends no bad attempt
        await links.view(token)

    for _ in range(3):
        with pytest.raises(LinkGone):
            await links.view("A" * 23)
    with pytest.raises(LinkRateLimited) as limited:
        await links.view("B" * 23)

    assert limited.value.retry_after_seconds == 600
    with pytest.raises(LinkRateLimited):
        await links.view(token)  # a good link does not get past a spent address either
    assert (await links.view(token, client=OTHER_CLIENT)).body["state"] == "ok"
    links.clock.advance(timedelta(minutes=10))
    assert (await links.view(token)).body["state"] == "ok"


async def test_a_wrong_csrf_token_spends_a_bad_attempt(
    links: LinkRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(link_access, "BAD_ATTEMPTS_PER_ADDRESS", 2)
    token = await _prompted(links)

    for _ in range(2):
        with pytest.raises(CsrfRejected):
            await links.respond(token, "confirm", csrf="0" * 64)
    with pytest.raises(LinkRateLimited):
        await links.respond(token, "confirm")


async def test_the_budgets_of_two_tenants_are_separate(
    links: LinkRig,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    other_tenant_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(link_access, "REQUESTS_PER_WINDOW", 2)
    token = await _prompted(links)
    other = build_link_rig(
        uow_factory_b,
        neo4j_driver,
        other_tenant_id,
        clock=links.clock,
        secrets=links.secrets,
        cache=links.cache,
        ids=SequentialIds.scoped(other_tenant_id),
        service_id="ucr-west-b",
        prefix="b-",
        phone=OTHER_PHONE,
    )
    await other.seed()
    with bind_tenant(other_tenant_id):
        other_token = await other.prompt()
    links.clock.set(ANSWER_AT)

    for _ in range(2):
        await links.view(token)
    with pytest.raises(LinkRateLimited):
        await links.view(token)
    with bind_tenant(other_tenant_id):
        assert (await other.view(other_token)).body["state"] == "ok"
        assert (await other.view(other_token)).body["state"] == "ok"
        with pytest.raises(LinkRateLimited):
            await other.view(other_token)


# -- renewing an expired link ---------------------------------------------------------------------


async def _expired(links: LinkRig, **seed: Any) -> str:
    token = await _prompted(links, **seed)
    links.clock.set(REPLY_BY + timedelta(minutes=3))
    return token


async def _sent(links: LinkRig) -> list[dict[str, Any]]:
    """The text of every SendMessage in the outbox, opened as the sender opens it."""
    return [
        {"id": m.id, "message_id": m.payload["message_id"], **links.rig.opened(m)}
        for m in await links.rig.events("SendMessage")
    ]


async def test_renewing_an_expired_link_queues_a_fresh_prompt_with_a_new_link(
    links: LinkRig,
) -> None:
    token = await _expired(links)
    before = await links.counts()
    sent_before = len(await _sent(links))

    await links.renew(token)

    after = await links.counts()
    assert after["LinkToken"] == before["LinkToken"] + 1
    assert after["Communication"] == before["Communication"] + 1
    assert after["OutboxMessage"] == before["OutboxMessage"] + 1
    assert after["AuditEvent"] == before["AuditEvent"] + 1
    sent = await _sent(links)
    assert len(sent) == sent_before + 1
    fresh = sent[-1]
    assert fresh["message_id"] == "C1"
    assert fresh["text"].startswith("DIUCS")
    found = re.search(rf"{re.escape(BASE_URL_A)}/([A-Za-z]{{23}})", fresh["text"])
    assert found is not None
    # The new link works, for a window that starts now, and the old one still does not.
    new_token = found.group(1)
    page = await links.view(new_token)
    assert page.body["replyBy"] == "2026-10-23T10:03:00Z"  # 11:03 London, a window from now
    with pytest.raises(LinkGone):
        await links.view(token)
    async with links.factory() as uow:
        entries = [r.entry for r in await uow.audit.records() if r.entry.use_case == "RenewLink"]
    assert [(e.actor.channel, e.actor.role.value) for e in entries] == [("link", "reporter")]


async def test_the_fresh_prompt_goes_to_the_same_role_and_its_text_is_sealed_for_this_tenant(
    links: LinkRig,
) -> None:
    token = await _expired(links)

    await links.renew(token)

    message = (await links.rig.events("SendMessage"))[-1]
    assert message.payload["recipient_role_id"] == "role-1"
    assert "text" not in message.payload  # the link is only in the sealed content
    assert "sealed_content" in message.payload
    opened = links.sealer.unseal(
        message.payload["sealed_content"],
        message_id=message.id,
        tenant_id=links.tenant,
        recipient_role_id="role-1",
    )
    assert BASE_URL_A in opened
    new_token = re.search(rf"{re.escape(BASE_URL_A)}/([A-Za-z]{{23}})", opened)
    assert new_token is not None
    assert await _nodes_holding(links, new_token.group(1)) == 0  # no record holds the new token


async def test_renewing_twice_queues_one_prompt(links: LinkRig) -> None:
    token = await _expired(links)
    await links.renew(token)
    before = await links.counts()

    await links.renew(token)
    await links.renew(token)

    assert await links.counts() == before


async def test_renewing_the_old_link_after_a_fresh_one_was_sent_does_nothing(
    links: LinkRig,
) -> None:
    token = await _expired(links)
    await links.renew(token)
    links.clock.advance(timedelta(minutes=40))  # the fresh link has expired too
    before = await links.counts()

    await links.renew(token)

    assert await links.counts() == before


@pytest.mark.parametrize(
    "case",
    ["open", "used", "unknown", "other-purpose", "suspended", "no-window-no-figure", "gone"],
)
async def test_a_renewal_that_is_not_called_for_queues_nothing_and_says_nothing(
    links: LinkRig, case: str
) -> None:
    if case == "no-window-no-figure":
        # A prompt that U03 would not send (nothing can be worded for it) but that is the latest.
        await links.seed(figure=None, profile=ucr_west(unit_label="beds"))
        async with links.factory() as uow:
            await uow.communications.add(
                Communication(
                    id="prompt-by-hand",
                    message_id="C1",
                    channel=Channel.TEXT,
                    recipient_role_id="role-1",
                    about_id=links.service_id,
                    payload_text="A prompt written by the test.",
                    sent_at=PROMPT_AT,
                    delivery_status="sent",
                )
            )
            await uow.commit()
        token = await links.issue(about_id="prompt-by-hand")
    else:
        token = await _prompted(links)
    links.clock.set(REPLY_BY + timedelta(minutes=3))
    if case == "open":
        links.clock.set(ANSWER_AT)
    elif case == "used":
        links.clock.set(ANSWER_AT)
        await links.respond(token, "number", 5)
        links.clock.set(REPLY_BY + timedelta(minutes=3))
    elif case == "unknown":
        token = "A" * 23
    elif case == "other-purpose":
        token = await links.issue(about_id="x", purpose="booking-request", expires_at=PROMPT_AT)
    elif case == "suspended":
        async with links.factory() as uow:
            await uow.flags.set_service_flag(
                ServiceFlag(
                    service_id=links.service_id,
                    code=SERVICE_FLAG_SUSPENDED,
                    active=True,
                    reason="staffing",
                    actor_id="lead-1",
                    at=PROMPT_AT,
                )
            )
            await uow.commit()
    else:  # the reporter has left the post
        async with links.factory() as uow:
            role = (await uow.people.reporter_roles_for_service(links.service_id, PROMPT_AT))[0]
            await uow.people.save_role(replace(role, period_end=PROMPT_AT))
            await uow.commit()
    before = await links.counts()

    await links.renew(token)  # no error, whatever the reason

    assert await links.counts() == before


async def test_renewals_are_limited_per_tenant_and_a_renewal_that_sends_nothing_costs_none(
    links: LinkRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(link_access, "RENEWALS_PER_WINDOW", 1)
    token = await _expired(links)
    await links.renew("A" * 23)  # an unknown link spends no renewal
    await links.renew("B" * 23)

    await links.renew(token)  # the one renewal
    other = await links.issue(about_id=(await links.token_node(token))["aboutId"])
    with pytest.raises(LinkRateLimited) as limited:
        await links.renew(other)

    assert limited.value.retry_after_seconds == 600


# -- another tenant's link -------------------------------------------------------------------------


async def test_another_tenants_link_is_an_unknown_one_in_every_use_case(
    links: LinkRig,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    other_tenant_id: str,
) -> None:
    token_a = await _prompted(links)
    other = build_link_rig(
        uow_factory_b,
        neo4j_driver,
        other_tenant_id,
        clock=links.clock,
        secrets=links.secrets,
        ids=SequentialIds.scoped(other_tenant_id),
        service_id="ucr-west-b",
        prefix="b-",
        phone=OTHER_PHONE,
    )
    await other.seed(figure=7)
    with bind_tenant(other_tenant_id):
        token_b = await other.prompt()
    links.clock.set(ANSWER_AT)
    before = await links.counts()

    # Tenant A is asked for tenant B's link: not found, the same as a link nobody holds.
    with pytest.raises(LinkGone) as view_b:
        await links.view(token_b)
    with pytest.raises(LinkGone) as view_unknown:
        await links.view("Z" * 23)
    with pytest.raises(LinkGone) as respond_b:
        await links.respond(token_b, "number", 4)
    await links.renew(token_b)

    assert view_b.value.state == view_unknown.value.state == respond_b.value.state == "expired"
    assert await links.counts() == before
    assert (await links.latest()).value == 3
    # Tenant B's link was not touched, and works in tenant B.
    with bind_tenant(other_tenant_id):
        assert "usedAt" not in await other.token_node(token_b)
        page = await other.view(token_b)
        assert page.body["recordedValue"] == 7
        assert page.body["serviceName"] == "UCR West"
    # ... and tenant B is asked for tenant A's link.
    with bind_tenant(other_tenant_id):
        with pytest.raises(LinkGone) as view_a:
            await other.view(token_a)
        assert view_a.value.state == "expired"


async def test_the_link_node_carries_the_tenant_it_was_issued_in(
    links: LinkRig, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    token = await _prompted(links)

    assert (await links.token_node(token))["tenantId"] == tenant_id


async def test_the_same_hash_in_one_tenant_is_not_readable_from_another_by_the_view(
    links: LinkRig,
) -> None:
    """The hash of a token is the same in every tenant (one secret), so a token alone must not be
    enough: the tenant that holds it is part of the lookup. Checked from the node's own point of
    view, with the hash computed here."""
    token = await _prompted(links)

    node = await links.token_node(token)

    assert node["tokenHash"] == token_hash_of(token)
    assert node["purpose"] == CAPACITY_PURPOSE


# -- no secret in what the code writes or says -----------------------------------------------------


async def _nodes_holding(links: LinkRig, text: str, *, not_labels: tuple[str, ...] = ()) -> int:
    """How many properties of nodes other than the link-token node itself (and `not_labels`)
    contain `text`."""

    async def everything(tx: Any) -> int:
        result = await tx.run(
            "MATCH (n) WHERE NOT n:LinkToken AND NONE(l IN labels(n) WHERE l IN $skip) "
            "RETURN properties(n) AS props",
            skip=list(not_labels),
        )
        return sum(
            text in str(value) for row in await result.data() for value in row["props"].values()
        )

    return await read_tx(links.driver, everything)


async def test_no_token_hash_or_csrf_token_is_stored_in_a_record_or_an_audit_entry(
    links: LinkRig,
) -> None:
    token = await _prompted(links)
    await links.respond(token, "number", 5)

    assert await _nodes_holding(links, token) == 0
    assert await _nodes_holding(links, links.csrf(token)) == 0
    # The hash is the link's identifier: it is in the replay key that makes the link single-use,
    # and in no other record.
    assert await _nodes_holding(links, token_hash_of(token)) == 1
    assert await _nodes_holding(links, token_hash_of(token), not_labels=("IdempotencyRecord",)) == 0


async def test_the_errors_a_link_raises_name_no_token_hash_or_value(links: LinkRig) -> None:
    token = await _prompted(links)
    errors: list[BaseException] = []
    for call in (
        links.view("A" * 23),
        links.respond(token, "number", 40),
        links.respond(token, "confirm", csrf="0" * 64),
    ):
        try:
            await call
        except BaseException as error:
            errors.append(error)

    assert len(errors) == 3
    for error in errors:
        text = repr(error) + str(error) + repr(vars(error))
        assert token not in text and token_hash_of(token) not in text
        assert "A" * 23 not in text
        assert "40" not in text.replace("usual", "")  # the figure sent is never echoed


async def test_two_secrets_are_all_the_link_code_reads(links: LinkRig) -> None:
    token = await _prompted(links)
    secrets: FixedSecretStore = links.secrets

    await links.view(token)

    assert {"link-token", "link-csrf"} <= set(secrets.requested)
    assert SECRET and new_secrets().names == {"link-token", "link-csrf"}


# -- the edges of the gate and the helpers --------------------------------------------------------


def _gate(links: LinkRig) -> Any:
    return link_access._Gate(
        links.factory,
        links.clock,
        links.secrets,
        links.cache,
        lambda repo: LinkTokenService(repo, links.secrets, links.clock),
        links.purposes,
    )


@pytest.mark.no_tenant
async def test_the_gate_refuses_a_unit_of_work_with_no_tenant_bound(links: LinkRig) -> None:
    with pytest.raises(TenantNotBound):
        await _gate(links).find("A" * 23, "slot")


@pytest.mark.no_tenant
async def test_the_gate_refuses_a_unit_of_work_bound_to_a_network(
    links: LinkRig, network_id: str
) -> None:
    with bind_scope(ScopeId.network(network_id)), pytest.raises(TenantNotBound):
        await _gate(links).find("A" * 23, "slot")


async def test_a_report_that_was_just_stored_but_cannot_be_read_is_an_error(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    clock = FixedClock(ANSWER_AT)

    class _Vanishing:
        async def execute(self, command: object) -> ReportCapacityResult:
            return ReportCapacityResult("no-such-report", Status.ACCEPTING, False, None)

    links = build_link_rig(
        uow_factory_on(neo4j_driver, clock),
        neo4j_driver,
        tenant_id,
        clock=clock,
        reports=_Vanishing(),
    )
    token = await _prompted(links)

    with pytest.raises(RuntimeError, match="cannot be read"):
        await links.respond(token, "number", 5)


async def test_the_idempotency_store_of_the_use_cases_round_trips_a_result(
    links: LinkRig,
) -> None:
    store = UnitOfWorkIdempotency(links.factory)
    result = ReportCapacityResult("report-1", Status.ACCEPTING, False, None)

    assert await store.get("a-key") is None
    await store.put("a-key", result)

    assert await store.get("a-key") == result
