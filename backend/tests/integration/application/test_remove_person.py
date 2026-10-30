"""Integration tests for RemovePerson, SignOutEverywhere, StartNewPhone and ConfirmNewPhone (U37),
against the real Neo4j the harness starts. Each assertion reads back through a fresh unit of work or
the harness helpers. The PINs are samples: no real PIN, no real number. The session store is the
recording stand-in: the Redis store has its own contract tests (the epoch cases).
"""

from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.messaging import PushSubscription
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.pin import (
    PIN_HMAC_SECRET,
    PinSignIn,
    PinSignInCommand,
    SetPin,
    SetPinCommand,
)
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
from diucs.application.use_cases.send_prompts import _phone_hash
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
)
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_NO_REPORTER
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import count_nodes, node_props
from tests.support.registration_rig import StubLimiter
from tests.support.session_rig import StubSessions
from tests.support.tenant_seed import contracted_container
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
SECRETS = FixedSecretStore({PIN_HMAC_SECRET: b"pin-hmac-test-secret-0123456789abcdef"})
PIN = "482913"
PERSON = "prac-1"
LEAD = "lead-1"
COVER = "prac-cover"
OTHER = "prac-other"
PERSON_HASH = "a" * 64
COVER_HASH = "b" * 64
DEVICES = ("dev-1", "dev-2")
SUBSCRIPTION = {
    "endpoint": "https://push.example/sample-endpoint",
    "keys": {"auth": "sample-auth", "p256dh": "sample-p256dh"},
}


def _actor(role: Role, practitioner_id: str, tenant: str = ACTOR_TENANT) -> Actor:
    return Actor(
        role=role,
        practitioner_id=practitioner_id,
        device_id=None,
        channel="api",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def _service(service_id: str, name: str) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=name,
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


def _role(role_id: str, person: str, service: str, **changes: Any) -> PractitionerRole:
    base = PractitionerRole(
        id=role_id,
        practitioner_id=person,
        service_id=service,
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=Channel.TEXT,
        period_start=NOW - timedelta(days=30),
    )
    from dataclasses import replace

    return replace(base, **changes)


async def seed(factory: UnitOfWorkFactory) -> None:
    """A reporter holding UCR West and UCR East (East covered until tomorrow by COVER), with two
    devices, two credentials, two push subscriptions with consent, and one past report. Another
    reporter with a device and a credential must be left alone."""
    clock = FixedClock(NOW)
    async with factory() as uow:
        await uow.services.save(_service("ucr-west", "UCR West"))
        await uow.services.save(_service("ucr-east", "UCR East"))
        for person, phone in (
            (PERSON, PERSON_HASH),
            (LEAD, None),
            (COVER, COVER_HASH),
            (OTHER, None),
        ):
            await uow.people.save_practitioner(
                Practitioner(
                    id=person, active=True, display_name="Sample Reporter", phone_hash=phone
                )
            )
        await uow.people.save_role(_role("role-west", PERSON, "ucr-west"))
        await uow.people.save_role(
            _role(
                "role-east",
                PERSON,
                "ucr-east",
                covered_by_practitioner_id=COVER,
                covered_until=NOW + timedelta(hours=9),
            )
        )
        for number, device in enumerate((*DEVICES, "dev-other"), start=1):
            owner = OTHER if device == "dev-other" else PERSON
            await uow.devices.register(owner, device, NOW - timedelta(days=40))
            await uow.devices.mark_verified(owner, device, NOW - timedelta(days=2))
            await uow.pins.set_pin(owner, device, f"hash-{number}")
            await uow.push_subscriptions.save(
                PushSubscription(
                    device_id=f"app-{device}",
                    practitioner_id=owner,
                    subscription=SUBSCRIPTION,
                    saved_at=NOW - timedelta(days=1),
                )
            )
            await uow.notification_consents.record(
                owner, f"app-{device}", "wording-v1", NOW - timedelta(days=1)
            )
        await uow.capacity.add(
            CapacityReport(
                id="obs-1",
                service_id="ucr-west",
                value=3,
                measure=Measure.REFERRALS_ACCEPTABLE,
                effective_at=NOW - timedelta(hours=3),
                source=ReportSource.TEXT,
                report_type=ReportType.NUMBER,
            )
        )
        await uow.commit()
    _ = clock


class Rig:
    def __init__(self, factory: UnitOfWorkFactory, tenant: str = ACTOR_TENANT) -> None:
        self.factory = factory
        self.tenant = tenant
        self.clock = FixedClock(NOW)
        self.sessions = StubSessions()
        self.remove = RemovePerson(factory, self.clock, SequentialIds("role"), self.sessions)
        self.sign_out = SignOutEverywhere(factory, self.clock, self.sessions)
        self.start = StartNewPhone(factory, self.clock, self.sessions)
        self.confirm = ConfirmNewPhone(factory, self.clock)
        self.limiter = StubLimiter()
        self.sign_in = PinSignIn(factory, SECRETS, self.clock, self.limiter)
        self.set_pin = SetPin(factory, SECRETS, self.clock, self.limiter)
        self.lead = _actor(Role.LEAD, LEAD, tenant)
        self.reporter = _actor(Role.REPORTER, PERSON, tenant)

    async def removal(self, key: str = "k1", person: str = PERSON) -> Any:
        return await self.remove.execute(
            RemovePersonCommand(key, self.lead, person, RemovalReason.LEFT_SERVICE)
        )

    async def sign(self, device: str, pin: str = PIN) -> Any:
        return await self.sign_in.execute(PinSignInCommand(PERSON, device, pin))

    async def give_a_pin(self, device: str) -> None:
        stamp = NOW - timedelta(minutes=1)
        async with self.factory() as uow:
            await uow.devices.mark_verified(PERSON, device, stamp)
            await uow.commit()
        assert (await self.set_pin.execute(SetPinCommand(PERSON, device, PIN, stamp))).ok

    async def credentials_of(self, person: str) -> int:
        async with self.factory() as uow:
            held = [await uow.pins.get(person, device) for device in (*DEVICES, "dev-other")]
        return len([item for item in held if item is not None])


@pytest_asyncio.fixture(loop_scope="session")
async def rig(
    clean_graph: None,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> Rig:
    await ensure_audit_heads(neo4j_driver, tenant_id)
    await seed(uow_factory)
    return Rig(uow_factory, tenant_id)


# RemovePerson


async def test_remove_ends_both_posts_deletes_credentials_and_push_and_keeps_past_reports(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    credentials_before = await count_nodes(neo4j_driver, "Credential")
    observations_before = await count_nodes(neo4j_driver, "Observation")
    assert credentials_before == 3
    assert observations_before >= 1

    result = await rig.removal()

    assert (result.roles_ended, result.devices_revoked, result.push_removed) == (2, 2, 2)
    assert await count_nodes(neo4j_driver, "Credential") == credentials_before - 2
    assert await count_nodes(neo4j_driver, "Observation") == observations_before
    async with rig.factory() as uow:
        for role_id in ("role-west", "role-east"):
            role = await uow.people.get_role(role_id)
            assert role is not None
            assert role.active is False
            assert role.period_end == NOW
        assert await uow.people.roles_for_practitioner(PERSON) == []
        assert (await uow.people.get_practitioner(PERSON)) is not None
        person = await uow.people.get_practitioner(PERSON)
        assert person is not None and person.active is False
        assert await uow.push_subscriptions.for_practitioner(PERSON) == []
        consent = await uow.notification_consents.get("app-dev-1")
        assert consent is not None and consent.status == "inactive"
        for device in DEVICES:
            assert await uow.devices.known(PERSON, device) is False
    assert await count_nodes(neo4j_driver, "AuditEvent") >= 1
    audit = await node_props(neo4j_driver, "AuditEvent", useCase="RemovePerson")
    assert audit["action"] == "U"


async def test_another_persons_devices_credentials_and_push_are_left_alone(rig: Rig) -> None:
    await rig.removal()
    async with rig.factory() as uow:
        assert await uow.devices.known(OTHER, "dev-other") is True
        assert await uow.pins.get(OTHER, "dev-other") is not None
        assert len(await uow.push_subscriptions.for_practitioner(OTHER)) == 1


async def test_east_has_an_active_cover_so_it_has_no_flag_and_west_has_one(rig: Rig) -> None:
    result = await rig.removal()
    assert result.services_without_reporter == ("ucr-west",)
    assert result.services_covered == ("ucr-east",)
    async with rig.factory() as uow:
        assert [f.code for f in await uow.flags.service_flags("ucr-west")] == [
            SERVICE_FLAG_NO_REPORTER
        ]
        assert await uow.flags.service_flags("ucr-east") == []
        east = await uow.people.reporter_roles_for_service("ucr-east", NOW)
        assert [(r.practitioner_id, r.period_end) for r in east] == [
            (COVER, NOW + timedelta(hours=9))
        ]
        assert await uow.people.reporter_roles_for_service("ucr-west", NOW) == []


async def test_the_removed_persons_pin_sign_in_fails(rig: Rig) -> None:
    await rig.removal()
    for device in DEVICES:
        answer = await rig.sign(device, PIN)
        assert answer.ok is False
        assert answer.needs_text_code is True


async def test_a_reporter_cannot_remove_and_nothing_changes(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    before = await count_nodes(neo4j_driver, "Credential")
    with pytest.raises(NotAllowed):
        await rig.remove.execute(
            RemovePersonCommand("k1", rig.reporter, OTHER, RemovalReason.OTHER)
        )
    assert await count_nodes(neo4j_driver, "Credential") == before


async def test_a_replay_of_the_same_key_returns_the_first_result_and_changes_nothing(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    first = await rig.removal("k-replay")
    audits = await count_nodes(neo4j_driver, "AuditEvent")
    second = await rig.removal("k-replay")
    assert second == first
    assert await count_nodes(neo4j_driver, "AuditEvent") == audits


async def test_a_role_the_person_was_covering_goes_back_to_its_holder(rig: Rig) -> None:
    async with rig.factory() as uow:
        await uow.people.save_role(
            _role(
                "role-other",
                OTHER,
                "ucr-west",
                covered_by_practitioner_id=PERSON,
                covered_until=NOW + timedelta(days=2),
            )
        )
        await uow.commit()
    result = await rig.removal()
    assert result.covers_released == 1
    async with rig.factory() as uow:
        role = await uow.people.get_role("role-other")
        assert role is not None
        assert role.covered_by_practitioner_id is None
        assert role.active is True
        # West now has OTHER, so no flag
        assert await uow.flags.service_flags("ucr-west") == []


# SignOutEverywhere


async def test_sign_out_everywhere_says_two_and_the_next_sign_in_needs_a_text_code(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    await rig.give_a_pin("dev-1")
    assert (await rig.sign("dev-1")).ok is True
    result = await rig.sign_out.execute(SignOutEverywhereCommand("k1", rig.reporter))
    assert result.devices_signed_out == 2
    answer = await rig.sign("dev-1")
    assert answer.ok is False
    assert answer.needs_text_code is True
    async with rig.factory() as uow:
        person = await uow.people.get_practitioner(PERSON)
        assert person is not None and person.active is True
        assert len(await uow.people.roles_for_practitioner(PERSON)) == 2
    assert rig.sessions.epochs[PERSON] == 2


# Lost phone


async def test_a_lost_phone_revokes_the_old_devices_and_the_new_one_waits_for_the_callback(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    stamp = NOW - timedelta(minutes=1)
    result = await rig.start.execute(StartNewPhoneCommand(PERSON, "dev-new", stamp))
    assert result.started is True
    assert result.devices_signed_out == 2
    props = await node_props(neo4j_driver, "Device", id="dev-new")
    assert props["status"] == "pending-callback"
    for device in DEVICES:
        old = await node_props(neo4j_driver, "Device", id=device)
        assert old["status"] == "revoked"
    async with rig.factory() as uow:
        assert await uow.pins.get(PERSON, "dev-1") is None
        assert await uow.push_subscriptions.for_practitioner(PERSON) == []
        assert await uow.devices.awaiting_callback(PERSON) == ["dev-new"]

    # The new phone can set a PIN (the code was just verified) but cannot sign in until confirmed.
    assert (await rig.set_pin.execute(SetPinCommand(PERSON, "dev-new", PIN))).ok is True
    refused = await rig.sign("dev-new")
    assert refused.ok is False
    assert refused.needs_text_code is True
    async with rig.factory() as uow:
        role = await uow.people.get_role("role-west")
        assert role is not None
        assert await _phone_hash(uow, role, NOW) is None

    confirmed = await rig.confirm.execute(ConfirmNewPhoneCommand("c1", rig.lead, PERSON))
    assert confirmed.confirmed == 1
    accepted = await rig.sign("dev-new")
    assert accepted.ok is True
    assert accepted.practitioner_id == PERSON
    async with rig.factory() as uow:
        role = await uow.people.get_role("role-west")
        assert role is not None
        assert await _phone_hash(uow, role, NOW) == PERSON_HASH


async def test_a_reporter_cannot_confirm_a_new_phone(rig: Rig) -> None:
    await rig.start.execute(StartNewPhoneCommand(PERSON, "dev-new", NOW - timedelta(minutes=1)))
    with pytest.raises(NotAllowed):
        await rig.confirm.execute(ConfirmNewPhoneCommand("c1", rig.reporter, PERSON))
    async with rig.factory() as uow:
        assert await uow.devices.known(PERSON, "dev-new") is False


async def test_confirming_when_nothing_waits_is_not_found(rig: Rig) -> None:
    with pytest.raises(NotFound):
        await rig.confirm.execute(ConfirmNewPhoneCommand("c1", rig.lead, PERSON))


async def test_the_same_new_phone_twice_keeps_it(rig: Rig) -> None:
    command = StartNewPhoneCommand(PERSON, "dev-new", NOW - timedelta(minutes=1))
    await rig.start.execute(command)
    again = await rig.start.execute(command)
    assert again.started is True
    assert again.devices_signed_out == 0
    async with rig.factory() as uow:
        assert await uow.devices.awaiting_callback(PERSON) == ["dev-new"]


async def test_a_device_id_another_person_holds_is_not_a_new_phone(rig: Rig) -> None:
    result = await rig.start.execute(
        StartNewPhoneCommand(PERSON, "dev-other", NOW - timedelta(minutes=1))
    )
    assert result.started is False
    async with rig.factory() as uow:
        assert await uow.devices.known(OTHER, "dev-other") is True
        assert await uow.devices.known(PERSON, "dev-1") is True


# Two tenants


@pytest_asyncio.fixture(loop_scope="session")
async def two_tenants(tenant_id: str, other_tenant_id: str):  # type: ignore[no-untyped-def]
    from tests.support.neo4j import wipe

    async with contracted_container() as driver:
        await wipe(driver)
        await ensure_audit_heads(driver, tenant_id, other_tenant_id)
        factory_a = tenant_uow_factory(driver, tenant_id)
        factory_b = tenant_uow_factory(driver, other_tenant_id)
        await seed(factory_a)
        await seed(factory_b)
        yield driver, Rig(factory_a, tenant_id), Rig(factory_b, other_tenant_id)


async def test_removing_in_a_leaves_b_untouched_and_the_same_ids_do_not_collide(
    two_tenants: Any,
) -> None:
    _, a, b = two_tenants
    await a.removal()
    async with b.factory() as uow:
        assert len(await uow.people.roles_for_practitioner(PERSON)) == 2
        assert await uow.devices.known(PERSON, "dev-1") is True
        assert await uow.pins.get(PERSON, "dev-1") is not None
        assert len(await uow.push_subscriptions.for_practitioner(PERSON)) == 2
        person = await uow.people.get_practitioner(PERSON)
        assert person is not None and person.active is True
        assert await uow.flags.service_flags("ucr-west") == []
    # The same command key in B is B's own command: it removes B's person.
    result = await b.removal()
    assert result.roles_ended == 2


async def test_a_person_of_b_given_to_a_is_not_found(two_tenants: Any) -> None:
    _, a, b = two_tenants
    async with b.factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="only-in-b", active=True, display_name="Sample", phone_hash=None)
        )
        await uow.commit()
    with pytest.raises(NotFound):
        await a.removal(person="only-in-b")
    async with b.factory() as uow:
        person = await uow.people.get_practitioner("only-in-b")
        assert person is not None and person.active is True
    with pytest.raises(NotFound):
        await a.confirm.execute(ConfirmNewPhoneCommand("c1", a.lead, "only-in-b"))


async def test_a_new_phone_in_a_does_not_touch_b(two_tenants: Any) -> None:
    _, a, b = two_tenants
    await a.start.execute(StartNewPhoneCommand(PERSON, "dev-new", NOW - timedelta(minutes=1)))
    async with b.factory() as uow:
        assert await uow.devices.known(PERSON, "dev-1") is True
        assert await uow.devices.awaiting_callback(PERSON) == []
        assert await uow.devices.owner_of("dev-new") is None
