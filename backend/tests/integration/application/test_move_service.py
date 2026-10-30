"""Integration tests for U38 (moving and adding services between phones), on the real Neo4j.

WRITTEN, NOT RUN in the build wave (no Neo4j per build-wave rules); verification runs them.
The code check is a recording fake (CodeVerifier): the text-code flow of U25 has its own tests. The
phone numbers are the sample values of the prompts; nothing here is a patient.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.move_service import (
    AddServiceToPhone,
    AddServiceToPhoneCommand,
    AnswerServiceAddition,
    AnswerServiceAdditionCommand,
    CompleteServiceMove,
    CompleteServiceMoveCommand,
    RecordMoveCallBack,
    RecordMoveCallBackCommand,
    StartServiceMove,
    StartServiceMoveCommand,
    VerifyServiceMoveCode,
    VerifyServiceMoveCodeCommand,
)
from diucs.domain.codes import Channel, Role
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.people import PractitionerRole, PractitionerRoleCode
from tests.support.actors import ACTOR_TENANT
from tests.support.ladder_rig import reporter, seed_people, virtual_ward
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

LONDON = ZoneInfo("Europe/London")
SECRET = b"phone-hash-test-secret-0123456789ab"
HASHER = HmacPhoneHasher(FixedSecretStore({PHONE_HASH_SECRET: SECRET}))
OLD_MOBILE = "07700 900123"
NEW_MOBILE = "07700 900456"
OLD_HASH = HASHER.hash(OLD_MOBILE)
NEW_HASH = HASHER.hash(NEW_MOBILE)
NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
FRIDAY_20 = datetime(2026, 10, 30, 20, 0, tzinfo=LONDON).astimezone(UTC)
LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="lead-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
REPORTER = Actor(
    role=Role.REPORTER,
    practitioner_id="prac-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)


@dataclass
class RecordingVerifier:
    """Stands in for the text-code check: accepts the one code the tests use."""

    accept: bool = True
    calls: list[tuple[str, str, str]] | None = None

    async def verify(self, phone: str, purpose: str, code: str) -> bool:
        self.calls = (self.calls or []) + [(phone, purpose, code)]
        return self.accept


def _clock(at: datetime = NOW) -> FixedClock:
    return FixedClock(at)


def _start(uow_factory: UnitOfWorkFactory) -> StartServiceMove:
    return StartServiceMove(uow_factory, SequentialIds("move"), _clock(), HASHER)


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(
    clean_graph: None,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    """One phone (prac-1, OLD_MOBILE) holding UCR West and UCR East; a second phone (prac-2,
    NEW_MOBILE) that is a registered reporter for UCR South; UCR North and UCR Park exist."""
    await ensure_audit_heads(neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        for service in ("ucr-west", "ucr-east", "ucr-north", "ucr-park", "ucr-south"):
            await uow.services.save(virtual_ward(service, name=service.replace("-", " ").title()))
        await uow.commit()
    await seed_people(
        uow_factory,
        reporter(1, OLD_HASH, service_id="ucr-west"),
        reporter(2, NEW_HASH, service_id="ucr-south"),
    )
    async with uow_factory() as uow:
        await uow.people.save_role(
            PractitionerRole(
                id="role-east",
                practitioner_id="prac-1",
                service_id="ucr-east",
                code=PractitionerRoleCode.DUTY_MANAGER,
                active=True,
                channel=Channel.TEXT,
                period_start=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await uow.commit()


async def _move_to_completion(
    uow_factory: UnitOfWorkFactory,
    service: str,
    *,
    until: datetime | None = None,
    verifier: RecordingVerifier | None = None,
) -> str:
    started = await _start(uow_factory).execute(
        StartServiceMoveCommand(actor=LEAD, service_id=service, to_mobile=NEW_MOBILE, until=until)
    )
    await VerifyServiceMoveCode(
        uow_factory, verifier or RecordingVerifier(), _clock(), HASHER
    ).execute(
        VerifyServiceMoveCodeCommand(move_id=started.move_id, mobile=NEW_MOBILE, code="123456")
    )
    await RecordMoveCallBack(uow_factory, _clock()).execute(
        RecordMoveCallBackCommand(actor=LEAD, move_id=started.move_id)
    )
    await CompleteServiceMove(uow_factory, SequentialIds("done"), _clock(), HASHER).execute(
        CompleteServiceMoveCommand(actor=LEAD, move_id=started.move_id)
    )
    return started.move_id


async def test_a_permanent_move_ends_the_old_role_and_links_the_service_to_the_new_phone(
    uow_factory: UnitOfWorkFactory, seeded: None
) -> None:
    move_id = await _move_to_completion(uow_factory, "ucr-east")

    async with uow_factory() as uow:
        east = await uow.people.get_role("role-east")
        west = await uow.people.get_role("role-1")
        move = await uow.service_moves.get(move_id)
        new_roles = await uow.people.roles_for_practitioner("prac-2")
    assert east is not None and east.active is False and east.period_end is not None
    assert west is not None and west.active is True
    assert any(role.service_id == "ucr-east" and role.active for role in new_roles)
    assert move is not None
    assert None not in (move.code_verified_at, move.callback_at, move.completed_at)


async def test_completing_before_the_call_back_is_not_allowed_and_changes_nothing(
    uow_factory: UnitOfWorkFactory, seeded: None
) -> None:
    started = await _start(uow_factory).execute(
        StartServiceMoveCommand(actor=LEAD, service_id="ucr-east", to_mobile=NEW_MOBILE, until=None)
    )
    await VerifyServiceMoveCode(uow_factory, RecordingVerifier(), _clock(), HASHER).execute(
        VerifyServiceMoveCodeCommand(move_id=started.move_id, mobile=NEW_MOBILE, code="123456")
    )
    with pytest.raises(NotAllowed, match="call"):
        await CompleteServiceMove(uow_factory, SequentialIds("done"), _clock(), HASHER).execute(
            CompleteServiceMoveCommand(actor=LEAD, move_id=started.move_id)
        )
    async with uow_factory() as uow:
        east = await uow.people.get_role("role-east")
    assert east is not None and east.active is True


async def test_a_cover_keeps_the_old_role_and_the_service_returns_when_the_cover_ends(
    uow_factory: UnitOfWorkFactory, seeded: None
) -> None:
    await _move_to_completion(uow_factory, "ucr-east", until=FRIDAY_20)

    async with uow_factory() as uow:
        east = await uow.people.get_role("role-east")
        during = await uow.people.services_for_phone_hash(OLD_HASH, NOW)
        after = await uow.people.services_for_phone_hash(OLD_HASH, FRIDAY_20.replace(hour=21))
    assert east is not None and east.active is True
    assert east.covered_by_practitioner_id == "prac-2" and east.covered_until == FRIDAY_20
    assert "ucr-east" not in {role.service_id for role, _ in during}
    assert "ucr-east" in {role.service_id for role, _ in after}


async def test_an_added_service_is_inactive_until_the_person_accepts_and_a_rejection_ends_it(
    uow_factory: UnitOfWorkFactory, seeded: None
) -> None:
    added = await AddServiceToPhone(uow_factory, SequentialIds("add"), _clock(), HASHER).execute(
        AddServiceToPhoneCommand(actor=LEAD, service_id="ucr-north", mobile=OLD_MOBILE)
    )
    async with uow_factory() as uow:
        before = await uow.people.get_role(added.role_id)
    assert before is not None and before.active is False

    await AnswerServiceAddition(uow_factory, _clock()).execute(
        AnswerServiceAdditionCommand(actor=REPORTER, role_id=added.role_id, accept=False)
    )
    async with uow_factory() as uow:
        rejected = await uow.people.get_role(added.role_id)
    assert rejected is not None and rejected.active is False and rejected.period_end is not None


async def test_a_fourth_service_on_one_phone_sets_the_holds_many_flag(
    uow_factory: UnitOfWorkFactory, seeded: None
) -> None:
    for service in ("ucr-north", "ucr-park"):
        added = await AddServiceToPhone(
            uow_factory, SequentialIds(service), _clock(), HASHER
        ).execute(AddServiceToPhoneCommand(actor=LEAD, service_id=service, mobile=OLD_MOBILE))
        await AnswerServiceAddition(uow_factory, _clock()).execute(
            AnswerServiceAdditionCommand(actor=REPORTER, role_id=added.role_id, accept=True)
        )
    async with uow_factory() as uow:
        flagged = await uow.flags.services_with_flag("holds-many-services")
    assert {"ucr-west", "ucr-east", "ucr-north", "ucr-park"} <= flagged


async def test_a_reporter_cannot_start_a_move(uow_factory: UnitOfWorkFactory, seeded: None) -> None:
    with pytest.raises(NotAllowed):
        await _start(uow_factory).execute(
            StartServiceMoveCommand(
                actor=REPORTER, service_id="ucr-east", to_mobile=NEW_MOBILE, until=None
            )
        )


async def test_a_move_for_another_tenants_service_reads_as_not_found(
    uow_factory_b: UnitOfWorkFactory, uow_factory_a: UnitOfWorkFactory, seeded: None
) -> None:
    with pytest.raises(NotFound):
        await _start(uow_factory_b).execute(
            StartServiceMoveCommand(
                actor=LEAD, service_id="ucr-east", to_mobile=NEW_MOBILE, until=None
            )
        )
    async with uow_factory_a() as uow:
        assert await uow.service_moves.open_for_service("ucr-east") == []
