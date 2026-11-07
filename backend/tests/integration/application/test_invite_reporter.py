"""Integration tests for inviting a service reporter (U24), against the real Neo4j the harness
starts. Each assertion reads back through a fresh unit of work or the harness helpers. The numbers
are sample values: there is no patient data and no real phone number.

NOT RUN in the build wave (no Neo4j in the builder's environment, build-wave rules): the batch
verification run proves them.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver

from overwatch.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_ids import SequentialIds
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.identity import (
    PHONE_HASH_SECRET,
    HmacPhoneHasher,
    normalise_uk_mobile,
)
from overwatch.application.ports.outbound.tokens import LINK_TOKEN_SECRET, LinkTokenService
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.invite_reporter import (
    InviteReporter,
    InviteReporterCommand,
    ResendInvitation,
    ResendInvitationCommand,
)
from overwatch.domain.codes import (
    Channel,
    PractitionerRoleCode,
    RegistrationStatus,
    Role,
    ScopeFlag,
    ServiceCategory,
)
from overwatch.domain.errors import Conflict, NotAllowed, ValidationFailed
from overwatch.domain.model.people import Practitioner, PractitionerRole
from overwatch.domain.model.registration import ScopeEntry
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import count_nodes, read_tx, run_nodes
from tests.support.sealing import TEST_SEALER, text_of

pytestmark = pytest.mark.asyncio(loop_scope="session")

# 09:00 London on 2026-10-29: London is on GMT, so local time equals UTC.
NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
MOBILE = "07700 900123"
SECRETS = FixedSecretStore(
    {
        PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab",
        LINK_TOKEN_SECRET: b"link-token-test-secret-0123456789abcdef",
    }
)
HASHER = HmacPhoneHasher(SECRETS)
LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
ADVISOR = replace(LEAD, role=Role.ADVISOR)
IN_PILOT = "svc-ucr-west"
LATER = "svc-ucr-later"


class Rig:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self.uow_factory = uow_factory
        self.clock = FixedClock(NOW)
        self.invite = InviteReporter(
            uow_factory,
            lambda repo: LinkTokenService(repo, SECRETS, self.clock),
            HASHER,
            self.clock,
            SequentialIds("inv"),
            link_base_url_for=lambda scope: "https://overwatch.example",
            sealer=TEST_SEALER,
        )
        self.resend = ResendInvitation(
            uow_factory,
            lambda repo: LinkTokenService(repo, SECRETS, self.clock),
            self.clock,
            SequentialIds("rsd"),
            link_base_url_for=lambda scope: "https://overwatch.example",
            sealer=TEST_SEALER,
        )

    def command(self, **changes: Any) -> InviteReporterCommand:
        values: dict[str, Any] = {
            "idempotency_key": "invite-1",
            "actor": LEAD,
            "service_id": IN_PILOT,
            "role_label": "Duty manager",
            "mobile": MOBILE,
            "suggested_channel": Channel.TEXT,
        }
        values.update(changes)
        return InviteReporterCommand(**values)

    async def outbox(self) -> list[Any]:
        async with self.uow_factory() as uow:
            return list(await uow.outbox.pending(100))

    def tokens(self, repo: Any) -> LinkTokenService:
        return LinkTokenService(repo, SECRETS, self.clock)


@pytest.fixture
async def rig(uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None) -> Rig:
    await ensure_audit_head(neo4j_driver)
    async with uow_factory() as uow:
        for service_id, name, flag, reason in (
            (IN_PILOT, "UCR West", ScopeFlag.IN_PILOT, ""),
            (LATER, "UCR Later", ScopeFlag.LATER, "Not ready"),
        ):
            await uow.scope.save_entry(
                ScopeEntry(
                    service_id=service_id,
                    name=name,
                    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                    flag=flag,
                    date=date(2026, 10, 29),
                    reason=reason,
                )
            )
        await uow.people.save_practitioner(
            Practitioner(id="prac-lead", active=True, display_name="Shift lead", phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id="role-lead",
                practitioner_id="prac-lead",
                service_id=None,
                code=PractitionerRoleCode.SHIFT_LEAD,
                active=True,
                channel=None,
                period_start=NOW,
            )
        )
        await uow.commit()
    return Rig(uow_factory)


async def _every_property_value(driver: AsyncDriver) -> list[tuple[list[str], str, Any]]:
    async def work(tx: Any) -> list[dict[str, Any]]:
        return await (await run_nodes(tx, "labels(n) AS labels, properties(n) AS p")).data()

    rows = await read_tx(driver, work)
    return [(row["labels"], name, value) for row in rows for name, value in row["p"].items()]


def _contains(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, list | tuple):
        return any(_contains(item, needle) for item in value)
    return False


async def test_an_invitation_stores_the_task_the_invited_registration_the_text_and_the_event(
    rig: Rig,
) -> None:
    result = await rig.invite.execute(rig.command())

    assert result.expires_at == datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
    async with rig.uow_factory() as uow:
        invitation = await uow.registrations.get_invitation(result.invitation_id)
        registration = await uow.registrations.get(result.registration_id)
    assert invitation is not None
    assert invitation.service_id == IN_PILOT
    assert invitation.requester_role_id == "role-lead"
    assert invitation.expires_at == result.expires_at
    assert registration is not None
    assert registration.status is RegistrationStatus.INVITED
    assert registration.requester_role_id is not None
    messages = await rig.outbox()
    sent = [m for m in messages if m.event_type == "SendMessage"]
    assert len(sent) == 1
    assert sent[0].payload["message_id"] == "I1"
    assert "https://overwatch.example/i/" in text_of(sent[0], ACTOR_TENANT)
    assert [m.event_type for m in messages if m.event_type == "ReporterInvited"] == [
        "ReporterInvited"
    ]


async def test_the_invitation_of_a_service_lead_is_the_set_up_text_and_keeps_their_name(
    rig: Rig,
) -> None:
    await rig.invite.execute(rig.command(role_label="Service lead", person_name=" Dee  Lead "))

    sent = [m for m in await rig.outbox() if m.event_type == "SendMessage"]
    assert [m.payload["message_id"] for m in sent] == ["I4"]
    text = text_of(sent[0], ACTOR_TENANT)
    assert "set up UCR West" in text
    assert "https://overwatch.example/i/" in text
    async with rig.uow_factory() as uow:
        person = await uow.people.find_by_phone_hash(HASHER.hash(normalise_uk_mobile(MOBILE)))
    assert person is not None
    assert person.display_name == "Dee Lead"


async def test_an_invitation_with_no_name_keeps_the_role_label_as_before(rig: Rig) -> None:
    await rig.invite.execute(rig.command())

    async with rig.uow_factory() as uow:
        person = await uow.people.find_by_phone_hash(HASHER.hash(normalise_uk_mobile(MOBILE)))
    assert person is not None
    assert person.display_name == "Duty manager"


async def test_the_mobile_number_is_found_only_on_the_protected_contact_node(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    await rig.invite.execute(rig.command())

    found: set[tuple[str, ...]] = set()
    for labels, _name, value in await _every_property_value(neo4j_driver):
        if _contains(value, "07700900123") or _contains(value, "+447700900123"):
            found.add(tuple(labels))
    assert found == {("ProtectedContact",)}
    assert not any(
        _contains(value, "07700 900123")
        for _labels, _name, value in await _every_property_value(neo4j_driver)
    )


async def test_a_service_flagged_later_is_refused_and_no_task_is_made(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    with pytest.raises(NotAllowed, match="Only services in the pilot can be invited"):
        await rig.invite.execute(rig.command(service_id=LATER))

    assert await count_nodes(neo4j_driver, "Task") == 0


async def test_a_mobile_that_is_not_a_uk_mobile_is_refused_on_the_mobile_field(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    with pytest.raises(ValidationFailed) as raised:
        await rig.invite.execute(rig.command(mobile="0123"))

    assert raised.value.field == "mobile"
    assert await count_nodes(neo4j_driver, "Task") == 0


async def test_a_resend_burns_the_old_link_and_issues_a_new_one_with_a_second_text(
    rig: Rig,
) -> None:
    first = await rig.invite.execute(rig.command())
    old_text = text_of((await rig.outbox())[0], ACTOR_TENANT)
    old_token = old_text.split("/i/")[1].split(" ")[0]
    rig.clock.advance(timedelta(hours=5))

    result = await rig.resend.execute(
        ResendInvitationCommand("resend-1", LEAD, first.invitation_id)
    )

    texts = [text_of(m, ACTOR_TENANT) for m in await rig.outbox() if m.event_type == "SendMessage"]
    assert len(texts) == 2
    new_token = texts[1].split("/i/")[1].split(" ")[0]
    async with rig.uow_factory() as uow:
        service = rig.tokens(uow.link_tokens)
        old = await service.resolve(old_token)
        new = await service.resolve(new_token)
        invitation = await uow.registrations.get_invitation(first.invitation_id)
    assert old is not None
    assert old.used_at is not None
    assert new is not None
    assert new.used_at is None
    assert new.expires_at == result.expires_at == rig.clock.now() + timedelta(hours=48)
    assert invitation is not None
    assert invitation.expires_at == result.expires_at


async def test_a_resend_after_the_registration_moved_to_draft_is_a_conflict(rig: Rig) -> None:
    first = await rig.invite.execute(rig.command())
    async with rig.uow_factory() as uow:
        registration = await uow.registrations.get(first.registration_id)
        assert registration is not None
        await uow.registrations.save(replace(registration, status=RegistrationStatus.DRAFT))
        await uow.commit()

    with pytest.raises(Conflict):
        await rig.resend.execute(ResendInvitationCommand("resend-1", LEAD, first.invitation_id))


async def test_an_advisor_cannot_invite_and_the_same_key_twice_is_one_invitation_and_one_text(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    with pytest.raises(NotAllowed):
        await rig.invite.execute(rig.command(actor=ADVISOR))

    first = await rig.invite.execute(rig.command())
    second = await rig.invite.execute(rig.command())

    assert second == first
    sent = [m for m in await rig.outbox() if m.event_type == "SendMessage"]
    assert len(sent) == 1
    assert await count_nodes(neo4j_driver, "Task") == 2  # the invitation and the registration


# --- a staff-sign-in lead has no shift-lead post: the 404 after a set-up


STAFF_LEAD = replace(LEAD, practitioner_id="prac-staff")


async def _staff_practitioner_without_a_post(uow_factory: UnitOfWorkFactory) -> None:
    """What the first staff sign-in leaves: a practitioner record and no role (DEC-1330)."""
    async with uow_factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-staff", active=True, display_name="Staff member", phone_hash=None)
        )
        await uow.commit()


async def test_a_lead_from_a_staff_sign_in_can_invite_and_is_given_the_shift_lead_post(
    rig: Rig, uow_factory: UnitOfWorkFactory
) -> None:
    await _staff_practitioner_without_a_post(uow_factory)

    result = await rig.invite.execute(rig.command(actor=STAFF_LEAD))

    assert result.invitation_id
    async with uow_factory() as uow:
        posts = [
            role
            for role in await uow.people.roles_for_practitioner("prac-staff")
            if role.code is PractitionerRoleCode.SHIFT_LEAD
        ]
    assert len(posts) == 1
    assert posts[0].active and posts[0].service_id is None


async def test_a_second_invitation_by_the_same_lead_does_not_make_a_second_post(
    rig: Rig, uow_factory: UnitOfWorkFactory
) -> None:
    await _staff_practitioner_without_a_post(uow_factory)
    async with uow_factory() as uow:
        await uow.scope.save_entry(
            ScopeEntry(
                service_id="svc-second",
                name="Second",
                category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                flag=ScopeFlag.IN_PILOT,
                date=date(2026, 10, 29),
                reason="",
            )
        )
        await uow.commit()
    await rig.invite.execute(rig.command(actor=STAFF_LEAD))

    await rig.invite.execute(
        rig.command(
            actor=STAFF_LEAD,
            idempotency_key="invite-2",
            service_id="svc-second",
            mobile="07700 900456",
        )
    )

    async with uow_factory() as uow:
        posts = [
            role
            for role in await uow.people.roles_for_practitioner("prac-staff")
            if role.code is PractitionerRoleCode.SHIFT_LEAD
        ]
    assert len(posts) == 1


async def test_an_actor_with_no_practitioner_record_is_still_refused(rig: Rig) -> None:
    with pytest.raises(NotAllowed):
        await rig.invite.execute(rig.command(actor=replace(LEAD, practitioner_id="prac-nobody")))
