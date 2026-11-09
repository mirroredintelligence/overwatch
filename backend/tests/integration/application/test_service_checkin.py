"""Check in by the QR code printed for a service (DEC-1346): the real graph, an in-memory cache.

The printed code names the service; a six-digit code texted to a rostered number proves who is
checking in. The tests cover the code the lead makes (and that a new one ends the old), what the
page can ask, the code texted only to a number on this service's roster, the right and wrong
codes, and the limits. Sample values only."""

import re
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

import pytest
from neo4j import AsyncDriver

from overwatch.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_ids import SequentialIds
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.adapters.testing.memory_cache import InMemoryCache
from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.identity import (
    PHONE_HASH_SECRET,
    HmacPhoneHasher,
    normalise_uk_mobile,
)
from overwatch.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.duty_roster import (
    AddRosterManager,
    AddRosterManagerCommand,
    CheckIn,
    ListRoster,
    SignOff,
)
from overwatch.application.use_cases.link_access import LINK_CSRF_SECRET, CsrfRejected
from overwatch.application.use_cases.service_checkin import (
    OFF,
    ON,
    CheckInCodeWrong,
    CheckInGone,
    CheckInRateLimited,
    ConfirmServiceCheckIn,
    IssueServiceCheckIn,
    SendCheckInCode,
    ViewServiceCheckIn,
)
from overwatch.domain.codes import Cadence, Channel, Measure, Role, ServiceCategory
from overwatch.domain.errors import NotAllowed, ValidationFailed
from overwatch.domain.model.people import Practitioner, RosterState
from overwatch.domain.model.service import AvailableTime, ServiceProfile
from tests.integration.application.conftest import Seed
from tests.support.actors import ACTOR_TENANT
from tests.support.sealing import TEST_SEALER, text_of

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
SECRETS = FixedSecretStore(
    {
        PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab",
        LINK_TOKEN_SECRET: b"link-token-test-secret-0123456789abcdef",
        LINK_CSRF_SECRET: b"link-csrf-test-secret-0123456789abcdefg",
    }
)
HASHER = HmacPhoneHasher(SECRETS)
ANA = "07700 900111"
BEN = "07700 900222"
STRANGER = "07700 900333"
CLIENT = "198.51.100.7"
LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
WEST = ServiceProfile(
    id="ucr-west",
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals in the next 2 hrs",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)
EAST = replace(WEST, id="ucr-east", name="UCR East")


def _hash(mobile: str) -> str:
    return HASHER.hash(normalise_uk_mobile(mobile))


class Rig:
    def __init__(self, factory: UnitOfWorkFactory) -> None:
        self.factory = factory
        self.clock = FixedClock(NOW)
        self.cache = InMemoryCache(self.clock)
        ids = SequentialIds("sc")
        self.add = AddRosterManager(factory, self.clock, ids, HASHER)
        self.list = ListRoster(factory, self.clock)
        check_in = CheckIn(factory, self.clock, ids)
        sign_off = SignOff(factory, self.clock)
        self.issue = IssueServiceCheckIn(factory, self.clock, SECRETS)
        self.view = ViewServiceCheckIn(factory, self.clock, SECRETS, self.cache, HASHER)
        self.send = SendCheckInCode(
            factory, self.clock, SECRETS, self.cache, HASHER, SequentialIds("cd"), TEST_SEALER
        )
        self.confirm = ConfirmServiceCheckIn(
            factory, self.clock, SECRETS, self.cache, HASHER, check_in, sign_off
        )

    def csrf(self, token: str) -> str:
        from overwatch.application.use_cases.link_access import csrf_token
        from overwatch.domain.rules.tokens import hash_token

        return csrf_token(
            hash_token(token[-23:], SECRETS.get(LINK_TOKEN_SECRET)),
            SECRETS.get(LINK_CSRF_SECRET),
        )

    async def person(self, name: str, mobile: str, service: str = "ucr-west") -> None:
        await self.add.execute(AddRosterManagerCommand(LEAD, service, name, mobile))

    async def states(self, service: str = "ucr-west") -> dict[str, RosterState]:
        return {entry.name: entry.state for entry in await self.list.execute(LEAD, service)}

    async def texts(self) -> list[str]:
        async with self.factory() as uow:
            pending = await uow.outbox.pending(1000)
        return [
            text_of(message, ACTOR_TENANT)
            for message in pending
            if message.event_type == "SendMessage"
        ]

    async def code_for(self, mobile: str, token: str) -> str:
        """Ask for a code and read it from the text that was queued."""
        before = len(await self.texts())
        await self.send.execute(token, mobile, CLIENT, self.csrf(token))
        texts = await self.texts()
        assert len(texts) == before + 1, "no code was texted"
        match = re.search(r"code: (\d{6})\.", texts[-1])
        assert match is not None
        return match.group(1)


@pytest.fixture
async def rig(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    clean_graph: None,
    seed_service: Seed,
) -> Rig:
    await ensure_audit_head(neo4j_driver)
    await seed_service(WEST, EAST)
    async with uow_factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-lead", active=True, display_name="Shift lead", phone_hash=None)
        )
        await uow.commit()
    return Rig(uow_factory)


async def test_the_lead_makes_a_code_and_the_page_can_ask_which_service_it_is_for(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")

    assert (await rig.view.execute(token, CLIENT)).service_name == "UCR West"


async def test_a_new_code_ends_the_old_one(rig: Rig) -> None:
    old = await rig.issue.execute(LEAD, "ucr-west")
    new = await rig.issue.execute(LEAD, "ucr-west")

    assert (await rig.view.execute(new, CLIENT)).service_name == "UCR West"
    with pytest.raises(CheckInGone):
        await rig.view.execute(old, CLIENT)


async def test_a_code_for_one_service_is_not_a_code_for_another(rig: Rig) -> None:
    west = await rig.issue.execute(LEAD, "ucr-west")
    east = await rig.issue.execute(LEAD, "ucr-east")

    assert (await rig.view.execute(west, CLIENT)).service_name == "UCR West"
    assert (await rig.view.execute(east, CLIENT)).service_name == "UCR East"


async def test_only_a_shift_lead_makes_a_code_and_only_for_a_service_that_exists(rig: Rig) -> None:
    with pytest.raises(NotAllowed):
        await rig.issue.execute(replace(LEAD, role=Role.ADVISOR), "ucr-west")
    with pytest.raises(Exception, match="no service"):
        await rig.issue.execute(LEAD, "nowhere")


async def test_an_unknown_or_malformed_code_is_gone(rig: Rig) -> None:
    for token in ("A" * 23, "short", "not a token!"):
        with pytest.raises(CheckInGone):
            await rig.view.execute(token, CLIENT)


async def test_a_code_is_texted_only_to_a_number_on_this_services_roster(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)
    await rig.person("Ben Duty", BEN, service="ucr-east")

    await rig.send.execute(token, ANA, CLIENT, rig.csrf(token))
    await rig.send.execute(
        token, BEN, CLIENT, rig.csrf(token)
    )  # on the roster of the other service only
    await rig.send.execute(token, STRANGER, CLIENT, rig.csrf(token))  # on no roster

    texts = await rig.texts()
    assert len(texts) == 1
    assert re.fullmatch(
        r"Overwatch code: \d{6}\. It works for 10 minutes\. Do not share it\.", texts[0]
    )


async def test_the_answer_is_the_same_for_a_number_on_the_roster_and_one_that_is_not(
    rig: Rig,
) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)

    assert await rig.send.execute(token, ANA, CLIENT, rig.csrf(token)) is None
    assert await rig.send.execute(token, STRANGER, CLIENT, rig.csrf(token)) is None


async def test_a_number_that_is_not_a_uk_mobile_is_refused(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    with pytest.raises(ValidationFailed):
        await rig.send.execute(token, "12345", CLIENT, rig.csrf(token))


async def test_the_right_code_puts_the_person_on_shift_for_this_service_only(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)
    await rig.person("Ana Duty", ANA, service="ucr-east")
    code = await rig.code_for(ANA, token)

    outcome = await rig.confirm.execute(token, ANA, code, ON, 6, CLIENT, rig.csrf(token))

    assert outcome.state == "on-shift"
    assert [change.service_name for change in outcome.changes] == ["UCR West"]
    assert await rig.states("ucr-west") == {"Ana Duty": RosterState.ON_SHIFT}
    assert await rig.states("ucr-east") == {"Ana Duty": RosterState.OFF_SHIFT}


async def test_a_code_works_once(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)
    code = await rig.code_for(ANA, token)
    await rig.confirm.execute(token, ANA, code, ON, 4, CLIENT, rig.csrf(token))

    with pytest.raises(CheckInCodeWrong):
        await rig.confirm.execute(token, ANA, code, ON, 4, CLIENT, rig.csrf(token))


async def test_a_wrong_code_does_nothing(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)
    code = await rig.code_for(ANA, token)
    wrong = "000000" if code != "000000" else "111111"

    with pytest.raises(CheckInCodeWrong):
        await rig.confirm.execute(token, ANA, wrong, ON, 4, CLIENT, rig.csrf(token))

    assert await rig.states() == {"Ana Duty": RosterState.OFF_SHIFT}


async def test_a_code_that_is_not_six_digits_is_wrong(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)
    await rig.code_for(ANA, token)

    for typed in ("", "12345", "abcdef", "1234567"):
        with pytest.raises(CheckInCodeWrong):
            await rig.confirm.execute(token, ANA, typed, ON, 4, CLIENT, rig.csrf(token))


async def test_a_code_typed_with_spaces_or_a_hyphen_is_read(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)
    code = await rig.code_for(ANA, token)

    outcome = await rig.confirm.execute(
        token, ANA, f"{code[:3]} {code[3:]}", ON, 4, CLIENT, rig.csrf(token)
    )

    assert outcome.state == "on-shift"


async def test_a_code_stops_working_after_ten_minutes(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)
    code = await rig.code_for(ANA, token)

    rig.clock.set(NOW + timedelta(minutes=11))

    with pytest.raises(CheckInCodeWrong):
        await rig.confirm.execute(token, ANA, code, ON, 4, CLIENT, rig.csrf(token))


async def test_a_code_texted_to_one_person_does_not_work_for_another(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)
    await rig.person("Ben Duty", BEN)
    code = await rig.code_for(ANA, token)

    with pytest.raises(CheckInCodeWrong):
        await rig.confirm.execute(token, BEN, code, ON, 4, CLIENT, rig.csrf(token))


async def test_a_code_made_for_one_service_cannot_check_in_to_another(rig: Rig) -> None:
    west = await rig.issue.execute(LEAD, "ucr-west")
    east = await rig.issue.execute(LEAD, "ucr-east")
    await rig.person("Ana Duty", ANA)
    await rig.person("Ana Duty", ANA, service="ucr-east")
    code = await rig.code_for(ANA, west)

    with pytest.raises(CheckInCodeWrong):
        await rig.confirm.execute(east, ANA, code, ON, 4, CLIENT, rig.csrf(east))


async def test_the_right_code_signs_the_person_off(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)
    on = await rig.code_for(ANA, token)
    await rig.confirm.execute(token, ANA, on, ON, 8, CLIENT, rig.csrf(token))
    off = await rig.code_for(ANA, token)

    outcome = await rig.confirm.execute(token, ANA, off, OFF, None, CLIENT, rig.csrf(token))

    assert outcome.state == "off-shift"
    assert await rig.states() == {"Ana Duty": RosterState.OFF_SHIFT}


async def test_a_shift_longer_than_the_longest_is_refused(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)
    code = await rig.code_for(ANA, token)

    with pytest.raises(ValidationFailed):
        await rig.confirm.execute(token, ANA, code, ON, 20, CLIENT, rig.csrf(token))


async def test_an_action_that_is_not_on_or_off_is_refused(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    with pytest.raises(ValidationFailed):
        await rig.confirm.execute(token, ANA, "123456", "later", 4, CLIENT, rig.csrf(token))


async def test_a_replaced_code_cannot_check_anyone_in(rig: Rig) -> None:
    old = await rig.issue.execute(LEAD, "ucr-west")
    await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)

    with pytest.raises(CheckInGone):
        await rig.send.execute(old, ANA, CLIENT, rig.csrf(old))
    with pytest.raises(CheckInGone):
        await rig.confirm.execute(old, ANA, "123456", ON, 4, CLIENT, rig.csrf(old))


async def test_a_fourth_code_for_one_number_in_ten_minutes_is_refused_whoever_it_is(
    rig: Rig,
) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    for _ in range(3):
        await rig.send.execute(token, STRANGER, CLIENT, rig.csrf(token))

    with pytest.raises(CheckInRateLimited):
        await rig.send.execute(token, STRANGER, CLIENT, rig.csrf(token))


async def test_a_sixth_wrong_code_for_one_number_is_refused_and_a_right_code_gives_its_attempt_back(
    rig: Rig,
) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)
    code = await rig.code_for(ANA, token)
    for _ in range(4):
        with pytest.raises(CheckInCodeWrong):
            await rig.confirm.execute(
                token,
                ANA,
                "000000" if code != "000000" else "111111",
                ON,
                4,
                CLIENT,
                rig.csrf(token),
            )

    outcome = await rig.confirm.execute(
        token, ANA, code, ON, 4, CLIENT, rig.csrf(token)
    )  # the fifth is right
    assert outcome.state == "on-shift"

    # Four wrong codes are still held, so one more is allowed and the next is refused.
    wrong = "000000" if code != "000000" else "111111"
    with pytest.raises(CheckInCodeWrong):
        await rig.confirm.execute(token, ANA, wrong, ON, 4, CLIENT, rig.csrf(token))
    with pytest.raises(CheckInRateLimited):
        await rig.confirm.execute(token, ANA, wrong, ON, 4, CLIENT, rig.csrf(token))


async def test_one_address_cannot_make_more_than_thirty_requests_in_ten_minutes(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    for _ in range(30):
        await rig.view.execute(token, CLIENT)

    with pytest.raises(CheckInRateLimited):
        await rig.view.execute(token, CLIENT)
    assert (await rig.view.execute(token, "198.51.100.8")).service_name == "UCR West"


async def test_a_write_without_the_pages_csrf_token_is_refused_before_anything_is_read(
    rig: Rig,
) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")
    await rig.person("Ana Duty", ANA)

    with pytest.raises(CsrfRejected):
        await rig.send.execute(token, ANA, CLIENT, None)
    with pytest.raises(CsrfRejected):
        await rig.send.execute(token, ANA, CLIENT, "0" * 64)
    with pytest.raises(CsrfRejected):
        await rig.confirm.execute(token, ANA, "123456", ON, 4, CLIENT, None)
    assert await rig.texts() == []


async def test_the_csrf_token_of_one_code_is_not_the_csrf_token_of_another(rig: Rig) -> None:
    west = await rig.issue.execute(LEAD, "ucr-west")
    east = await rig.issue.execute(LEAD, "ucr-east")

    with pytest.raises(CsrfRejected):
        await rig.send.execute(west, ANA, CLIENT, rig.csrf(east))


async def test_the_page_gives_the_csrf_token_that_its_writes_must_send_back(rig: Rig) -> None:
    token = await rig.issue.execute(LEAD, "ucr-west")

    page = await rig.view.execute(token, CLIENT)

    assert page.csrf_token == rig.csrf(token)
