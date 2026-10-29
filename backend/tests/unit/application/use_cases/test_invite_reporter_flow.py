"""InviteReporter and ResendInvitation against recording stand-ins for their ports (U24).

The order of the calls, what is written and what is not, and that the mobile number goes only to the
protected contact store. What is really stored, read back from Neo4j, is in
tests/integration/application/test_invite_reporter.py. Sample values only; no patient data.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, LinkTokenService
from diucs.application.use_cases.invite_reporter import (
    InviteReporter,
    InviteReporterCommand,
    ResendInvitation,
    ResendInvitationCommand,
)
from diucs.domain.codes import (
    Channel,
    PractitionerRoleCode,
    RegistrationStatus,
    Role,
    ScopeFlag,
    ServiceCategory,
)
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.events import ReporterInvited
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import ScopeEntry
from tests.support.registration_rig import StubUnits

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
SERVICE = "svc-ucr-west"
MOBILE = "07700 900123"
SECRETS = FixedSecretStore(
    {
        PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab",
        LINK_TOKEN_SECRET: b"link-token-test-secret-0123456789ab",
    }
)
HASHER = HmacPhoneHasher(SECRETS)
LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)
ADVISOR = replace(LEAD, role=Role.ADVISOR)


class World:
    def __init__(self, flag: ScopeFlag = ScopeFlag.IN_PILOT) -> None:
        self.units = StubUnits()
        self.clock = FixedClock(NOW)
        self.ids = SequentialIds("id")
        self.units.scope.entries_by_service[SERVICE] = ScopeEntry(
            service_id=SERVICE,
            name="UCR West",
            category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
            flag=flag,
            date=NOW.date(),
            reason="" if flag is ScopeFlag.IN_PILOT else "Not yet",
        )
        self.units.people.roles["role-lead"] = PractitionerRole(
            id="role-lead",
            practitioner_id="prac-lead",
            service_id=None,
            code=PractitionerRoleCode.SHIFT_LEAD,
            active=True,
            channel=None,
            period_start=NOW,
        )
        self.invite = InviteReporter(
            self.units,
            lambda repo: LinkTokenService(repo, SECRETS, self.clock),
            HASHER,
            self.clock,
            self.ids,
            link_base_url_for=lambda scope: "https://diucs.example",
        )
        self.resend = ResendInvitation(
            self.units,
            lambda repo: LinkTokenService(repo, SECRETS, self.clock),
            self.clock,
            self.ids,
            link_base_url_for=lambda scope: "https://diucs.example",
        )

    def command(self, **changes: Any) -> InviteReporterCommand:
        values: dict[str, Any] = {
            "idempotency_key": "k-1",
            "actor": LEAD,
            "service_id": SERVICE,
            "role_label": "Duty manager",
            "mobile": MOBILE,
            "suggested_channel": Channel.TEXT,
        }
        values.update(changes)
        return InviteReporterCommand(**values)


async def test_an_invitation_stores_the_registration_the_invitation_and_the_reporters_post() -> (
    None
):
    world = World()

    result = await world.invite.execute(world.command())

    assert result.expires_at == NOW + timedelta(hours=48)
    registration = world.units.registrations.held[result.registration_id]
    assert registration.status is RegistrationStatus.INVITED
    assert registration.service_id == SERVICE
    assert registration.created_at == NOW
    invitation = world.units.registrations.invitations[result.invitation_id]
    assert invitation.registration_id == registration.id
    assert invitation.requester_role_id == "role-lead"
    assert invitation.expires_at == NOW + timedelta(hours=48)
    assert invitation.role_label == "Duty manager"
    role = world.units.people.roles[registration.requester_role_id or ""]
    assert role.service_id == SERVICE
    assert role.code is PractitionerRoleCode.DUTY_MANAGER
    assert role.channel is Channel.TEXT
    assert role.practitioner_id == invitation.invitee_id
    assert world.units.commits == 1


async def test_the_mobile_goes_only_to_the_protected_contact_store() -> None:
    world = World()

    result = await world.invite.execute(world.command())

    registration = world.units.registrations.held[result.registration_id]
    assert world.units.contacts.phones == {registration.requester_role_id: "+447700900123"}
    everything = repr(
        (
            world.units.registrations.held,
            world.units.registrations.invitations,
            world.units.people.practitioners,
            world.units.people.roles,
            world.units.audit.entries,
            world.units.communications.sent,
            [message.payload for message in world.units.outbox.messages],
        )
    )
    for form in ("07700900123", "07700 900123", "+447700900123"):
        assert form not in everything
    invitee = world.units.people.practitioners[
        world.units.registrations.invitations[result.invitation_id].invitee_id
    ]
    assert invitee.phone_hash == HASHER.hash(MOBILE)


async def test_the_text_i1_carries_a_link_that_resolves_to_the_invitation_and_the_phone() -> None:
    world = World()

    result = await world.invite.execute(world.command())

    sent = [m for m in world.units.outbox.messages if m.event_type == "SendMessage"]
    assert len(sent) == 1
    payload = sent[0].payload
    assert payload["message_id"] == "I1"
    assert payload["channel"] == "text"
    text = payload["text"]
    assert text.startswith("DIUCS: You are invited to report capacity for UCR West. ")
    assert text.endswith(" Valid for 48 hrs.")
    link = text.split("Set up takes about 3 minutes: ")[1].split(" Valid")[0]
    assert link.startswith("https://diucs.example/i/")
    token = link.removeprefix("https://diucs.example/i/")
    record = await LinkTokenService(world.units.link_tokens, SECRETS, world.clock).resolve(token)
    assert record is not None
    assert record.purpose == "invite"
    assert record.about_id == result.invitation_id
    assert record.phone_hash == HASHER.hash(MOBILE)
    assert record.expires_at == NOW + timedelta(hours=48)


async def test_the_stored_copy_of_the_text_holds_no_token() -> None:
    world = World()

    await world.invite.execute(world.command())

    communication = world.units.communications.sent[0]
    assert communication.message_id == "I1"
    assert "https://diucs.example/i/[link]" in communication.payload_text
    token = world.units.outbox.messages[0].payload["text"].split("/i/")[1].split(" ")[0]
    assert token not in communication.payload_text
    assert communication.recipient_role_id in world.units.people.roles


async def test_the_event_the_audit_entry_and_the_replay_record_are_written_with_the_change() -> (
    None
):
    world = World()

    result = await world.invite.execute(world.command())

    events = [m for m in world.units.outbox.messages if m.event_type == "ReporterInvited"]
    assert len(events) == 1
    assert events[0].topic == "registration.events"
    assert events[0].payload == ReporterInvited(result.invitation_id, SERVICE, NOW).to_payload()
    assert len(world.units.audit.entries) == 1
    entry = world.units.audit.entries[0]
    assert entry.use_case == "InviteReporter"
    assert result.invitation_id in entry.entity_ids
    assert entry.snapshot is not None
    assert entry.snapshot["service_id"] == SERVICE
    assert len(world.units.idempotency.stored) == 1
    assert next(iter(world.units.idempotency.stored)).startswith("invite-reporter:invite:tenant-a:")


@pytest.mark.parametrize("flag", [ScopeFlag.LATER, ScopeFlag.OUT_OF_SCOPE])
async def test_a_service_that_is_not_in_the_pilot_is_refused_and_nothing_is_written(
    flag: ScopeFlag,
) -> None:
    world = World(flag)

    with pytest.raises(NotAllowed, match="Only services in the pilot can be invited"):
        await world.invite.execute(world.command())

    assert world.units.writes.names == []
    assert world.units.commits == 0


async def test_a_service_that_is_not_on_the_list_is_not_found() -> None:
    world = World()

    with pytest.raises(NotFound):
        await world.invite.execute(world.command(service_id="svc-unknown"))

    assert world.units.writes.names == []


async def test_a_mobile_that_is_not_a_uk_mobile_is_refused_before_anything_is_written() -> None:
    world = World()

    with pytest.raises(ValidationFailed) as raised:
        await world.invite.execute(world.command(mobile="0123"))

    assert raised.value.field == "mobile"
    assert world.units.writes.names == []


async def test_an_advisor_cannot_invite() -> None:
    world = World()

    with pytest.raises(NotAllowed):
        await world.invite.execute(world.command(actor=ADVISOR))

    assert world.units.writes.names == []


async def test_a_lead_who_holds_no_shift_lead_post_is_refused() -> None:
    world = World()
    world.units.people.roles.clear()

    with pytest.raises(NotAllowed):
        await world.invite.execute(world.command())

    assert world.units.writes.names == []


async def test_a_service_that_already_has_a_registration_is_a_conflict() -> None:
    world = World()
    await world.invite.execute(world.command())
    writes_before = list(world.units.writes.names)

    with pytest.raises(Conflict):
        await world.invite.execute(world.command(idempotency_key="k-2"))

    assert world.units.writes.names == writes_before


async def test_the_same_key_twice_is_one_invitation_and_one_text() -> None:
    world = World()

    first = await world.invite.execute(world.command())
    second = await world.invite.execute(world.command())

    assert second == first
    assert len(world.units.registrations.invitations) == 1
    assert len([m for m in world.units.outbox.messages if m.event_type == "SendMessage"]) == 1


async def test_the_same_key_for_another_number_is_a_conflict() -> None:
    world = World()
    await world.invite.execute(world.command())

    with pytest.raises(Conflict):
        await world.invite.execute(world.command(mobile="07700 900456"))


async def test_a_person_who_already_holds_the_number_is_reused_not_made_twice() -> None:
    world = World()
    world.units.people.practitioners["prac-known"] = Practitioner(
        id="prac-known", active=True, display_name="Known person", phone_hash=HASHER.hash(MOBILE)
    )

    result = await world.invite.execute(world.command())

    assert world.units.registrations.invitations[result.invitation_id].invitee_id == "prac-known"
    assert list(world.units.people.practitioners) == ["prac-known"]


# Resend


async def test_a_resend_burns_the_old_link_issues_a_new_one_and_texts_again() -> None:
    world = World()
    first = await world.invite.execute(world.command())
    old_text = world.units.outbox.messages[0].payload["text"]
    old_token = old_text.split("/i/")[1].split(" ")[0]
    world.clock.advance(timedelta(hours=30))
    later = world.clock.now()

    result = await world.resend.execute(
        ResendInvitationCommand("k-resend", LEAD, first.invitation_id)
    )

    service = LinkTokenService(world.units.link_tokens, SECRETS, world.clock)
    old = await service.resolve(old_token)
    assert old is not None
    assert old.used_at == later
    sent = [m for m in world.units.outbox.messages if m.event_type == "SendMessage"]
    assert len(sent) == 2
    new_token = sent[1].payload["text"].split("/i/")[1].split(" ")[0]
    new = await service.resolve(new_token)
    assert new is not None
    assert new.used_at is None
    assert new.about_id == first.invitation_id
    assert new.expires_at == later + timedelta(hours=48)
    assert result.invitation_id == first.invitation_id
    assert result.registration_id == first.registration_id
    assert result.expires_at == later + timedelta(hours=48)


async def test_a_resend_restarts_the_forty_eight_hours_the_applicants_saves_are_counted_from() -> (
    None
):
    world = World()
    first = await world.invite.execute(world.command())
    world.clock.advance(timedelta(hours=47))

    await world.resend.execute(ResendInvitationCommand("k-resend", LEAD, first.invitation_id))

    registration = world.units.registrations.held[first.registration_id]
    assert registration.created_at == world.clock.now()
    invitation = world.units.registrations.invitations[first.invitation_id]
    assert invitation.sent_at == world.clock.now()
    assert invitation.created_at == NOW
    assert invitation.expires_at == world.clock.now() + timedelta(hours=48)


async def test_a_resend_after_the_old_link_has_lapsed_just_issues_a_new_one() -> None:
    world = World()
    first = await world.invite.execute(world.command())
    world.clock.advance(timedelta(hours=60))
    marks_before = world.units.writes.names.count("link_tokens.mark_used")

    await world.resend.execute(ResendInvitationCommand("k-resend", LEAD, first.invitation_id))

    assert world.units.writes.names.count("link_tokens.mark_used") == marks_before


async def test_a_resend_after_the_registration_moved_on_is_a_conflict_and_writes_nothing() -> None:
    world = World()
    first = await world.invite.execute(world.command())
    registration = world.units.registrations.held[first.registration_id]
    world.units.registrations.held[registration.id] = replace(
        registration, status=RegistrationStatus.DRAFT
    )
    writes_before = list(world.units.writes.names)

    with pytest.raises(Conflict):
        await world.resend.execute(ResendInvitationCommand("k-resend", LEAD, first.invitation_id))

    assert world.units.writes.names == writes_before


async def test_a_resend_of_an_unknown_invitation_is_not_found() -> None:
    world = World()

    with pytest.raises(NotFound):
        await world.resend.execute(ResendInvitationCommand("k-resend", LEAD, "inv-unknown"))


async def test_an_advisor_cannot_resend() -> None:
    world = World()
    first = await world.invite.execute(world.command())

    with pytest.raises(NotAllowed):
        await world.resend.execute(
            ResendInvitationCommand("k-resend", ADVISOR, first.invitation_id)
        )


async def test_the_same_resend_key_twice_sends_one_text() -> None:
    world = World()
    first = await world.invite.execute(world.command())
    command = ResendInvitationCommand("k-resend", LEAD, first.invitation_id)

    one = await world.resend.execute(command)
    two = await world.resend.execute(command)

    assert two == one
    assert len([m for m in world.units.outbox.messages if m.event_type == "SendMessage"]) == 2
