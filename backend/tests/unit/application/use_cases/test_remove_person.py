"""RemovePerson, SignOutEverywhere, StartNewPhone and ConfirmNewPhone against recording stand-ins
for their ports (U37).

The order of the calls, what is written and what is not, who may call, that the session store is
told after the commit as well as before (so a failed revoke is an error and never a quiet success),
that a refused command writes nothing, and that no phone number or hash reaches an audit entry. What
is really stored, read back from Neo4j, is in tests/integration/application/test_remove_person.py.
Sample values only.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.messaging import PushSubscription
from diucs.application.use_cases.remove_person import (
    ConfirmNewPhone,
    ConfirmNewPhoneCommand,
    RemovalReason,
    RemovePerson,
    RemovePersonCommand,
    SignOutEverywhere,
    SignOutEverywhereCommand,
    StartNewPhone,
    StartNewPhoneCommand,
)
from diucs.domain.codes import PractitionerRoleCode, Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.flags import SERVICE_FLAG_NO_REPORTER
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.rules.identity_policy import PinState
from tests.support.actors import ACTOR_TENANT
from tests.support.registration_rig import StubUnits
from tests.support.session_rig import StubSessions

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
PERSON = "prac-1"
LEAD = "lead-1"
COVER = "prac-cover"
HASH = "a" * 64


def _actor(role: Role, practitioner_id: str | None) -> Actor:
    return Actor(
        role=role,
        practitioner_id=practitioner_id,
        device_id=None,
        channel="api",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )


LEAD_ACTOR = _actor(Role.LEAD, LEAD)
REPORTER_ACTOR = _actor(Role.REPORTER, PERSON)


def _role(
    role_id: str,
    person: str,
    service: str,
    **changes: Any,
) -> PractitionerRole:
    base = PractitionerRole(
        id=role_id,
        practitioner_id=person,
        service_id=service,
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=None,
        period_start=NOW - timedelta(days=30),
    )
    return replace(base, **changes)


class World:
    """A reporter holding UCR West and UCR East, two devices, two credentials and a subscription."""

    def __init__(self) -> None:
        self.units = StubUnits()
        self.clock = FixedClock(NOW)
        self.sessions = StubSessions(self.units.events)
        for person_id in (PERSON, LEAD, COVER):
            self.units.people.practitioners[person_id] = Practitioner(
                id=person_id,
                active=True,
                display_name="Sample Reporter",
                phone_hash=HASH if person_id == PERSON else None,
            )
        self.units.people.roles["role-west"] = _role("role-west", PERSON, "ucr-west")
        self.units.people.roles["role-east"] = _role("role-east", PERSON, "ucr-east")
        for device in ("dev-1", "dev-2"):
            self.units.devices.held[(PERSON, device)] = {
                "revoked": False,
                "pending": False,
                "verified_at": NOW - timedelta(days=2),
                "at": NOW - timedelta(days=40),
            }
            self.units.pins.held[(PERSON, device)] = ("hash-" + device, PinState())
            self.units.push_subscriptions.held["app-" + device] = PushSubscription(
                device_id="app-" + device,
                practitioner_id=PERSON,
                subscription={"endpoint": "https://push.example/sample", "keys": {}},
                saved_at=NOW - timedelta(days=1),
            )
        self.ids = SequentialIds("role")
        self.remove = RemovePerson(self.units, self.clock, self.ids, self.sessions)
        self.sign_out = SignOutEverywhere(self.units, self.clock, self.sessions)
        self.start = StartNewPhone(self.units, self.clock, self.sessions)
        self.confirm = ConfirmNewPhone(self.units, self.clock)

    def removal(self, key: str = "k1", reason: RemovalReason = RemovalReason.LEFT_SERVICE) -> Any:
        return RemovePersonCommand(key, LEAD_ACTOR, PERSON, reason)

    def cover_east(self, until: timedelta = timedelta(hours=9)) -> None:
        role = self.units.people.roles["role-east"]
        self.units.people.roles["role-east"] = replace(
            role, covered_by_practitioner_id=COVER, covered_until=NOW + until
        )

    def audit(self) -> list[Any]:
        return list(self.units.audit.entries)


# RemovePerson


async def test_remove_ends_every_role_and_signs_the_person_out() -> None:
    world = World()
    result = await world.remove.execute(world.removal())
    roles = world.units.people.roles
    for role_id in ("role-west", "role-east"):
        assert roles[role_id].active is False
        assert roles[role_id].period_end == NOW
    assert result.roles_ended == 2
    assert result.devices_revoked == 2
    assert all(device["revoked"] for device in world.units.devices.held.values())
    assert [key for key in world.units.pins.held if key[0] == PERSON] == []
    assert world.units.push_subscriptions.held == {}
    assert sorted(world.units.notification_consents.withdrawn) == [
        (PERSON, "app-dev-1"),
        (PERSON, "app-dev-2"),
    ]
    assert result.push_removed == 2
    assert world.units.people.practitioners[PERSON].active is False


async def test_the_session_store_is_told_before_and_after_the_commit() -> None:
    world = World()
    await world.remove.execute(world.removal())
    assert world.units.events == ["sessions.revoke", "commit", "sessions.revoke"]


async def test_a_session_store_that_fails_after_the_commit_is_an_error_not_a_success() -> None:
    world = World()
    world.sessions.fail = False

    async def fail_second(practitioner_id: str) -> None:
        world.units.events.append("sessions.revoke")
        if world.units.events.count("sessions.revoke") == 2:
            raise OSError("redis unreachable")

    world.sessions.delete_all_for_person = fail_second  # type: ignore[method-assign]
    with pytest.raises(OSError, match="redis"):
        await world.remove.execute(world.removal())
    # The change itself is committed; the replay of the same key finishes the sign-out.
    assert world.units.commits == 1


async def test_a_session_store_that_fails_before_anything_stops_the_removal() -> None:
    world = World()
    world.sessions.fail = True
    with pytest.raises(OSError):
        await world.remove.execute(world.removal())
    assert world.units.writes.names == []
    assert world.units.commits == 0


async def test_a_replay_changes_nothing_again_but_signs_the_sessions_out_again() -> None:
    world = World()
    first = await world.remove.execute(world.removal())
    writes = list(world.units.writes.names)
    world.units.events.clear()
    second = await world.remove.execute(world.removal())
    assert second == first
    assert world.units.writes.names == writes
    assert world.units.events == ["sessions.revoke"]


async def test_the_same_key_for_another_person_is_a_conflict() -> None:
    world = World()
    await world.remove.execute(world.removal())
    world.units.people.practitioners["prac-2"] = Practitioner(
        id="prac-2", active=True, display_name="Sample Reporter", phone_hash=None
    )
    with pytest.raises(Conflict):
        await world.remove.execute(
            RemovePersonCommand("k1", LEAD_ACTOR, "prac-2", RemovalReason.LEFT_SERVICE)
        )


async def test_a_service_with_no_other_reporter_and_no_cover_gets_the_no_reporter_flag() -> None:
    world = World()
    world.cover_east()
    result = await world.remove.execute(world.removal())
    flag = world.units.flags.held[("ucr-west", SERVICE_FLAG_NO_REPORTER)]
    assert flag.active is True
    assert flag.actor_id == LEAD
    assert ("ucr-east", SERVICE_FLAG_NO_REPORTER) not in world.units.flags.held
    assert result.services_without_reporter == ("ucr-west",)
    assert result.services_covered == ("ucr-east",)


async def test_an_active_cover_carries_on_until_it_ends() -> None:
    world = World()
    world.cover_east(timedelta(hours=9))
    await world.remove.execute(world.removal())
    successors = [
        role
        for role in world.units.people.roles.values()
        if role.practitioner_id == COVER and role.service_id == "ucr-east"
    ]
    assert len(successors) == 1
    successor = successors[0]
    assert successor.active is True
    assert successor.code is PractitionerRoleCode.DUTY_MANAGER
    assert successor.period_start == NOW
    assert successor.period_end == NOW + timedelta(hours=9)
    assert successor.covered_by_practitioner_id is None


async def test_a_cover_that_has_ended_does_not_count() -> None:
    world = World()
    world.cover_east(timedelta(seconds=0))
    result = await world.remove.execute(world.removal())
    assert result.services_without_reporter == ("ucr-east", "ucr-west")
    assert ("ucr-east", SERVICE_FLAG_NO_REPORTER) in world.units.flags.held


async def test_a_cover_who_has_left_does_not_count() -> None:
    world = World()
    world.cover_east()
    world.units.people.practitioners[COVER] = replace(
        world.units.people.practitioners[COVER], active=False
    )
    result = await world.remove.execute(world.removal())
    assert "ucr-east" in result.services_without_reporter


async def test_a_service_with_another_active_reporter_gets_no_flag() -> None:
    world = World()
    world.units.people.roles["role-west-2"] = _role("role-west-2", COVER, "ucr-west")
    result = await world.remove.execute(world.removal())
    assert ("ucr-west", SERVICE_FLAG_NO_REPORTER) not in world.units.flags.held
    assert result.services_without_reporter == ("ucr-east",)


async def test_another_reporter_who_has_left_is_not_a_reporter() -> None:
    world = World()
    world.units.people.roles["role-west-2"] = _role("role-west-2", COVER, "ucr-west")
    world.units.people.practitioners[COVER] = replace(
        world.units.people.practitioners[COVER], active=False
    )
    result = await world.remove.execute(world.removal())
    assert "ucr-west" in result.services_without_reporter


async def test_a_role_the_person_was_covering_goes_back_to_its_own_holder() -> None:
    world = World()
    world.units.people.roles["role-other"] = _role(
        "role-other",
        COVER,
        "ucr-north",
        covered_by_practitioner_id=PERSON,
        covered_until=NOW + timedelta(days=2),
    )
    result = await world.remove.execute(world.removal())
    released = world.units.people.roles["role-other"]
    assert released.covered_by_practitioner_id is None
    assert released.covered_until is None
    assert released.active is True
    assert result.covers_released == 1


async def test_only_the_lead_may_remove_and_a_refusal_writes_nothing() -> None:
    world = World()
    for actor in (REPORTER_ACTOR, _actor(Role.ADVISOR, "adv-1"), _actor(Role.WALL, None)):
        with pytest.raises(NotAllowed):
            await world.remove.execute(
                RemovePersonCommand("k1", actor, PERSON, RemovalReason.OTHER)
            )
    assert world.units.writes.names == []
    assert world.units.events == []


async def test_a_lead_cannot_remove_themself() -> None:
    world = World()
    with pytest.raises(NotAllowed):
        await world.remove.execute(RemovePersonCommand("k1", LEAD_ACTOR, LEAD, RemovalReason.OTHER))
    assert world.units.writes.names == []


async def test_a_lead_with_no_practitioner_cannot_remove() -> None:
    world = World()
    with pytest.raises(NotAllowed):
        await world.remove.execute(
            RemovePersonCommand("k1", _actor(Role.LEAD, None), PERSON, RemovalReason.OTHER)
        )


async def test_an_unknown_person_is_not_found_and_nothing_is_written() -> None:
    world = World()
    with pytest.raises(NotFound):
        await world.remove.execute(
            RemovePersonCommand("k1", LEAD_ACTOR, "nobody", RemovalReason.OTHER)
        )
    assert world.units.writes.names == []


async def test_a_reason_that_is_not_one_of_the_four_is_refused() -> None:
    world = World()
    with pytest.raises(ValidationFailed):
        await world.remove.execute(
            RemovePersonCommand("k1", LEAD_ACTOR, PERSON, "boredom")  # type: ignore[arg-type]
        )
    assert world.units.writes.names == []


async def test_a_blank_key_is_refused() -> None:
    world = World()
    with pytest.raises(ValidationFailed):
        await world.remove.execute(
            RemovePersonCommand("  ", LEAD_ACTOR, PERSON, RemovalReason.OTHER)
        )


@pytest.mark.parametrize("reason", list(RemovalReason))
async def test_the_audit_entry_holds_the_reason_and_counts_and_no_number(
    reason: RemovalReason,
) -> None:
    world = World()
    await world.remove.execute(world.removal(reason=reason))
    entries = world.audit()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.use_case == "RemovePerson"
    assert entry.snapshot["reason"] == reason.value
    assert entry.snapshot["roles_ended"] == 2
    text = json.dumps(entry.snapshot, default=str)
    assert HASH not in text
    assert "push.example" not in text


async def test_a_person_with_no_devices_and_no_roles_is_still_removed() -> None:
    world = World()
    world.units.devices.held.clear()
    world.units.people.roles.clear()
    world.units.push_subscriptions.held.clear()
    result = await world.remove.execute(world.removal())
    assert (result.roles_ended, result.devices_revoked, result.push_removed) == (0, 0, 0)
    assert world.units.people.practitioners[PERSON].active is False


# SignOutEverywhere


async def test_sign_out_everywhere_revokes_every_device_and_says_how_many() -> None:
    world = World()
    result = await world.sign_out.execute(SignOutEverywhereCommand("k1", REPORTER_ACTOR))
    assert result.devices_signed_out == 2
    assert all(device["revoked"] for device in world.units.devices.held.values())
    assert [key for key in world.units.pins.held if key[0] == PERSON] == []
    assert world.units.push_subscriptions.held == {}
    assert world.units.people.practitioners[PERSON].active is True
    assert world.units.people.roles["role-west"].active is True
    assert world.units.events == ["sessions.revoke", "commit", "sessions.revoke"]


async def test_sign_out_everywhere_kills_the_sessions_of_the_person_only() -> None:
    world = World()
    other = await world.sessions.create(Role.REPORTER, "someone-else", "dev-9", (), NOW, epoch=0)
    mine = await world.sessions.create(Role.REPORTER, PERSON, "dev-1", (), NOW, epoch=0)
    await world.sign_out.execute(SignOutEverywhereCommand("k1", REPORTER_ACTOR))
    assert await world.sessions.get(mine) is None
    assert await world.sessions.get(other) is not None


async def test_sign_out_everywhere_is_replayed_by_key_with_the_first_count() -> None:
    world = World()
    first = await world.sign_out.execute(SignOutEverywhereCommand("k1", REPORTER_ACTOR))
    second = await world.sign_out.execute(SignOutEverywhereCommand("k1", REPORTER_ACTOR))
    assert (first.devices_signed_out, second.devices_signed_out) == (2, 2)
    third = await world.sign_out.execute(SignOutEverywhereCommand("k2", REPORTER_ACTOR))
    assert third.devices_signed_out == 0


async def test_sign_out_everywhere_needs_a_person() -> None:
    world = World()
    for actor in (_actor(Role.WALL, None), _actor(Role.ANONYMOUS_LINK, None)):
        with pytest.raises(NotAllowed):
            await world.sign_out.execute(SignOutEverywhereCommand("k1", actor))
    assert world.units.writes.names == []
    assert world.units.events == []


async def test_a_lead_may_sign_themself_out_everywhere() -> None:
    world = World()
    result = await world.sign_out.execute(SignOutEverywhereCommand("k1", LEAD_ACTOR))
    assert result.devices_signed_out == 0


async def test_sign_out_everywhere_audit_holds_a_count_only() -> None:
    world = World()
    await world.sign_out.execute(SignOutEverywhereCommand("k1", REPORTER_ACTOR))
    entry = world.audit()[0]
    assert entry.use_case == "SignOutEverywhere"
    assert entry.snapshot == {"devices_signed_out": 2}


# StartNewPhone


def _start(world: World, device: str = "dev-new", ago: timedelta = timedelta(minutes=1)) -> Any:
    return world.start.execute(StartNewPhoneCommand(PERSON, device, NOW - ago))


async def test_a_new_phone_signs_the_old_ones_out_and_waits_for_a_callback() -> None:
    world = World()
    result = await _start(world)
    assert result.started is True
    assert result.devices_signed_out == 2
    assert world.units.devices.held[(PERSON, "dev-1")]["revoked"] is True
    assert world.units.devices.held[(PERSON, "dev-2")]["revoked"] is True
    new = world.units.devices.held[(PERSON, "dev-new")]
    assert new["pending"] is True
    assert new["revoked"] is False
    assert new["verified_at"] == NOW - timedelta(minutes=1)
    assert [key for key in world.units.pins.held if key[0] == PERSON] == []
    assert world.units.push_subscriptions.held == {}
    assert world.units.events == ["sessions.revoke", "commit", "sessions.revoke"]


async def test_the_new_phone_cannot_sign_in_until_the_lead_confirms() -> None:
    world = World()
    await _start(world)
    assert await world.units.devices.known(PERSON, "dev-new") is False
    assert await world.units.devices.awaiting_callback(PERSON) == ["dev-new"]


async def test_a_repeat_of_the_same_new_phone_changes_nothing_and_keeps_the_device() -> None:
    world = World()
    await _start(world)
    writes = list(world.units.writes.names)
    again = await _start(world)
    assert again.started is True
    assert again.devices_signed_out == 0
    assert world.units.writes.names == writes
    assert world.units.devices.held[(PERSON, "dev-new")]["revoked"] is False


async def test_a_device_id_that_was_revoked_cannot_be_the_new_phone() -> None:
    world = World()
    world.units.devices.held[(PERSON, "dev-1")]["revoked"] = True
    result = await _start(world, device="dev-1")
    assert result.started is False
    assert world.units.commits == 0
    assert world.units.devices.held[(PERSON, "dev-2")]["revoked"] is False


async def test_a_device_id_another_person_holds_is_not_a_new_phone() -> None:
    world = World()
    world.units.devices.held[(COVER, "dev-cover")] = {
        "revoked": False,
        "pending": False,
        "verified_at": None,
        "at": NOW,
    }
    result = await _start(world, device="dev-cover")
    assert result.started is False
    assert world.units.writes.names == []


async def test_a_device_id_that_is_already_active_is_not_a_new_phone() -> None:
    world = World()
    result = await _start(world, device="dev-2")
    assert result.started is False
    assert world.units.commits == 0


@pytest.mark.parametrize("ago", [timedelta(minutes=11), timedelta(days=1), timedelta(minutes=-5)])
async def test_a_verification_that_is_not_recent_starts_nothing(ago: timedelta) -> None:
    world = World()
    result = await _start(world, ago=ago)
    assert result.started is False
    assert world.units.writes.names == []
    assert world.units.events == []


async def test_an_unknown_or_removed_person_starts_nothing_with_the_same_answer() -> None:
    world = World()
    unknown = await world.start.execute(StartNewPhoneCommand("nobody", "dev-new", NOW))
    world.units.people.practitioners[PERSON] = replace(
        world.units.people.practitioners[PERSON], active=False
    )
    gone = await _start(world)
    assert unknown == gone
    assert unknown.started is False
    assert unknown.devices_signed_out == 0
    assert (world.units.devices.held[(PERSON, "dev-1")]["revoked"]) is False


async def test_the_new_phone_audit_names_no_device_secret() -> None:
    world = World()
    await _start(world)
    entry = world.audit()[0]
    assert entry.use_case == "StartNewPhone"
    assert entry.snapshot == {"devices_signed_out": 2}


# ConfirmNewPhone


async def test_the_lead_confirms_the_new_phone() -> None:
    world = World()
    await _start(world)
    result = await world.confirm.execute(ConfirmNewPhoneCommand("k1", LEAD_ACTOR, PERSON))
    assert result.confirmed == 1
    assert await world.units.devices.known(PERSON, "dev-new") is True
    assert await world.units.devices.awaiting_callback(PERSON) == []
    assert world.audit()[-1].use_case == "ConfirmNewPhone"


async def test_a_reporter_cannot_confirm_a_new_phone() -> None:
    world = World()
    await _start(world)
    writes = list(world.units.writes.names)
    with pytest.raises(NotAllowed):
        await world.confirm.execute(ConfirmNewPhoneCommand("k1", REPORTER_ACTOR, PERSON))
    assert world.units.writes.names == writes
    assert await world.units.devices.known(PERSON, "dev-new") is False


async def test_confirming_when_no_phone_waits_is_not_found() -> None:
    world = World()
    with pytest.raises(NotFound):
        await world.confirm.execute(ConfirmNewPhoneCommand("k1", LEAD_ACTOR, PERSON))


async def test_confirming_a_person_who_has_left_is_not_found() -> None:
    world = World()
    await _start(world)
    world.units.people.practitioners[PERSON] = replace(
        world.units.people.practitioners[PERSON], active=False
    )
    with pytest.raises(NotFound):
        await world.confirm.execute(ConfirmNewPhoneCommand("k1", LEAD_ACTOR, PERSON))
    assert await world.units.devices.known(PERSON, "dev-new") is False


async def test_a_confirm_is_replayed_by_key() -> None:
    world = World()
    await _start(world)
    first = await world.confirm.execute(ConfirmNewPhoneCommand("k1", LEAD_ACTOR, PERSON))
    second = await world.confirm.execute(ConfirmNewPhoneCommand("k1", LEAD_ACTOR, PERSON))
    assert first == second
    assert len(world.audit()) == 2  # the start and the one confirm


async def test_a_lead_cannot_confirm_their_own_new_phone() -> None:
    world = World()
    world.units.devices.held[(LEAD, "dev-lead")] = {
        "revoked": False,
        "pending": True,
        "verified_at": NOW,
        "at": NOW,
    }
    with pytest.raises(NotAllowed):
        await world.confirm.execute(ConfirmNewPhoneCommand("k1", LEAD_ACTOR, LEAD))
