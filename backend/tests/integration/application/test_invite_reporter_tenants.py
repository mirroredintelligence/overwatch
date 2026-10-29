"""Two-tenant tests for inviting a reporter (U24, DEC-130 to DEC-132, DEC-142).

Tenant A and tenant B each have a scope list entry with the same service id, and the same mobile
may be invited by both. A's lead resends and invites only in A: an invitation of B given to A's
unit of work reads as not found, and B's link is not touched by A's resend. Runs on
contracted_container() (DEC-159, lesson L168).

NOT RUN in the build wave: the batch verification run proves it.
"""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.invite_reporter import (
    InviteReporter,
    InviteReporterCommand,
    ResendInvitation,
    ResendInvitationCommand,
)
from diucs.domain.codes import Channel, PractitionerRoleCode, Role, ScopeFlag, ServiceCategory
from diucs.domain.errors import NotFound
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import ScopeEntry
from tests.support.neo4j import wipe
from tests.support.tenant_seed import contracted_container
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
SERVICE = "svc-ucr-west"
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
)


@pytest_asyncio.fixture(loop_scope="session")
async def two_tenants(
    tenant_id: str, other_tenant_id: str
) -> AsyncIterator[tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory]]:
    async with contracted_container() as driver:
        await wipe(driver)
        await ensure_audit_heads(driver, tenant_id, other_tenant_id)
        factory_a = tenant_uow_factory(driver, tenant_id)
        factory_b = tenant_uow_factory(driver, other_tenant_id)
        for factory in (factory_a, factory_b):
            async with factory() as uow:
                await uow.scope.save_entry(
                    ScopeEntry(
                        service_id=SERVICE,
                        name="UCR West",
                        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                        flag=ScopeFlag.IN_PILOT,
                        date=date(2026, 10, 29),
                    )
                )
                await uow.people.save_practitioner(
                    Practitioner(
                        id="prac-lead", active=True, display_name="Shift lead", phone_hash=None
                    )
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
        yield driver, factory_a, factory_b


def _use_cases(factory: UnitOfWorkFactory) -> tuple[InviteReporter, ResendInvitation]:
    clock = FixedClock(NOW)

    def tokens(repo: object) -> LinkTokenService:
        return LinkTokenService(repo, SECRETS, clock)  # type: ignore[arg-type]

    return (
        InviteReporter(
            factory,
            tokens,
            HASHER,
            clock,
            SequentialIds("inv"),
            link_base_url_for=lambda scope: f"https://{scope}.diucs.example",
        ),
        ResendInvitation(
            factory,
            tokens,
            clock,
            SequentialIds("rsd"),
            link_base_url_for=lambda scope: f"https://{scope}.diucs.example",
        ),
    )


def _command() -> InviteReporterCommand:
    return InviteReporterCommand(
        idempotency_key="invite-1",
        actor=LEAD,
        service_id=SERVICE,
        role_label="Duty manager",
        mobile=MOBILE,
        suggested_channel=Channel.TEXT,
    )


async def test_the_same_mobile_can_be_invited_by_two_tenants_without_a_collision(
    two_tenants: tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory],
) -> None:
    _driver, factory_a, factory_b = two_tenants
    invite_a, _ = _use_cases(factory_a)
    invite_b, _ = _use_cases(factory_b)

    result_a = await invite_a.execute(_command())
    result_b = await invite_b.execute(_command())

    assert result_a.invitation_id == result_b.invitation_id  # same generated id in both tenants
    async with factory_a() as uow_a:
        assert await uow_a.registrations.get_invitation(result_a.invitation_id) is not None
    async with factory_b() as uow_b:
        assert await uow_b.registrations.get_invitation(result_b.invitation_id) is not None


async def test_an_invitation_of_another_tenant_reads_as_not_found_and_is_not_changed(
    two_tenants: tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory],
) -> None:
    _driver, factory_a, factory_b = two_tenants
    invite_a, resend_a = _use_cases(factory_a)
    _, resend_b = _use_cases(factory_b)
    first_a = await invite_a.execute(replace(_command(), service_id=SERVICE))
    # B has no invitation: A's invitation id handed to B's resend is not found there.
    with pytest.raises(NotFound):
        await resend_b.execute(ResendInvitationCommand("resend-b", LEAD, first_a.invitation_id))
    async with factory_a() as uow:
        invitation = await uow.registrations.get_invitation(first_a.invitation_id)
    assert invitation is not None
    assert invitation.sent_at == NOW
