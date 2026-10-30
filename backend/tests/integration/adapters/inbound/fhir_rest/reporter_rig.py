"""The rig of the reporter app route tests (W7C): the set-up routes behind a link or a device and
the routes behind a reporter's bearer token, on the harness Neo4j and the compose Redis, with the
real use cases and the real session, code and rate stores.

The clock is Thursday 29 October 2026, 14:00Z (14:00 London, GMT). The run tenant is the one the
host `HOST_A` names. Two services (UCR West and UCR East, open 08:00 to 20:00,
usual range 0 to 8) and one reporter who holds both. UCR West last reported 4 at 12:10, so it is
due now (every two hours); UCR East, once a day from 08:00, reported 2 at 13:58, so it is
confirmed. A device that a text code verified three
days ago is registered for the reporter. Numbers are samples (07700 900xxx): no real number and no
patient data. Each test starts from a graph the harness wiped and Redis keys of the run flushed.
"""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, LinkTokenService
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.pin import PIN_HMAC_SECRET
from diucs.application.use_cases.text_code import CODE_HMAC_SECRET, INVITATION_PURPOSE, code_hash
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    RegistrationStatus,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
)
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import Invitation, Registration
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.identity_policy import CodeState
from tests.integration.adapters.inbound.link_pages.conftest import seed_tenant_host
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.redis import flush_prefix

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
MOBILE = "07700 900123"
INVITEE_MOBILE = "07700 900321"
COVER_MOBILE = "07700 900456"
UNKNOWN_MOBILE = "07700 900789"
CODE = "482913"
PIN = "135790"
PERSON = "prac-1"
DEVICE = "device-aaaaaaaaaaaaaaaaaaaaaa"
OTHER_DEVICE = "device-bbbbbbbbbbbbbbbbbbbbbb"
WEST = "ucr-west"
EAST = "ucr-east"
VAPID_PUBLIC_KEY = "BNsamplepublickey0123456789abcdefghijklmnopqrstuvwxyz"
SECRETS: dict[str, bytes] = {
    BFF_SECRET_NAME: TEST_BFF_SECRET,
    PHONE_HASH_SECRET: b"phone-hash-route-test-secret-0123456789ab",
    CODE_HMAC_SECRET: b"code-hmac-route-test-secret-0123456789abc",
    PIN_HMAC_SECRET: b"pin-hmac-route-test-secret-0123456789abcd",
    LINK_TOKEN_SECRET: b"link-token-route-test-secret-0123456789a",
    "webpush-vapid-public-key": VAPID_PUBLIC_KEY.encode(),
}


def profile(service_id: str, name: str, cadence: Cadence = Cadence.EVERY_2_HRS) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=name,
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals in the next 2 hrs",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=cadence,
        available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


def report(report_id: str, service_id: str, value: int, at: datetime) -> CapacityReport:
    return CapacityReport(
        id=report_id,
        service_id=service_id,
        value=value,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=at,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )


def bearer(
    person: str = PERSON,
    *,
    role: Role = Role.REPORTER,
    services: tuple[str, ...] = (WEST, EAST),
    device: str | None = DEVICE,
    tenant: str | None = None,
    key: str | None = None,
) -> dict[str, str]:
    """A reporter's bearer header. The token's `services` claim is deliberately wide: the routes
    must ask the graph what the person holds, not read the claim."""
    token = issue_test_token(
        role, services, person, device=device, tenant=tenant, expires_at=NOW + timedelta(hours=8)
    )
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


async def open_container(
    server: ThrowawayNeo4j, clock: FixedClock, *tenants: str
) -> AsyncIterator[Container]:
    connection = Neo4jConnection(server.uri, server.user, server.password)
    await connection.open()
    container = build_for_tests(
        clock=clock, ids=SequentialIds(), neo4j=connection, secrets=FixedSecretStore(SECRETS)
    )
    for tenant in tenants:
        await flush_prefix(container.redis, f"diucs:{tenant}:")
    try:
        yield container
    finally:
        for tenant in tenants:
            await flush_prefix(container.redis, f"diucs:{tenant}:")
        await container.redis.aclose()
        await connection.close()


async def seed_world(
    container: Container,
    tenant: str,
    *,
    mobile: str = MOBILE,
    west_value: int = 4,
    east_value: int = 2,
) -> None:
    """The two services, the reporter, their posts, number and phone, and the reports, in `tenant`.
    The reports are written at the times they carry (the clock is moved for each, then put back),
    so that the record order of a report is its own: a number written at 14:00 is 'since' a prompt
    sent at 14:00, and the reply policy then refuses a Y (H-32)."""
    hasher = HmacPhoneHasher(container.secrets)
    clock = container.clock
    assert isinstance(clock, FixedClock)
    with bind_tenant(tenant):
        clock.set(NOW - timedelta(days=3))
        async with container.uow_factory() as uow:
            await uow.services.save(profile(WEST, "UCR West"))
            await uow.services.save(profile(EAST, "UCR East", Cadence.ONCE_A_DAY))
            await uow.people.save_practitioner(
                Practitioner(
                    id=PERSON,
                    active=True,
                    display_name="Sample Reporter",
                    phone_hash=hasher.hash(mobile),
                )
            )
            for role_id, service in (("role-west", WEST), ("role-east", EAST)):
                await uow.people.save_role(
                    PractitionerRole(
                        id=role_id,
                        practitioner_id=PERSON,
                        service_id=service,
                        code=PractitionerRoleCode.DUTY_MANAGER,
                        active=True,
                        channel=Channel.TEXT,
                        period_start=NOW - timedelta(days=30),
                    )
                )
            international = "+44" + mobile.replace(" ", "")[1:]
            await uow.contacts.put_phone("role-west", international)
            await uow.contacts.put_phone("role-east", international)
            await uow.devices.register(PERSON, DEVICE, NOW - timedelta(days=3))
            await uow.devices.mark_verified(PERSON, DEVICE, NOW - timedelta(days=3))
            await uow.commit()
        for report_id, service, value, at in (
            ("rep-west-1", WEST, west_value, datetime(2026, 10, 29, 12, 10, tzinfo=UTC)),
            ("rep-east-1", EAST, east_value, datetime(2026, 10, 29, 13, 58, tzinfo=UTC)),
        ):
            clock.set(at)
            async with container.uow_factory() as uow:
                await uow.capacity.add(report(report_id, service, value, at))
                await uow.commit()
        clock.set(NOW)


async def seed_invitation(
    container: Container,
    tenant: str,
    *,
    mobile: str = INVITEE_MOBILE,
    service_id: str = "ucr-new",
    service_name: str = "UCR New",
    expires_at: datetime | None = None,
    used: bool = False,
) -> str:
    """An open invitation for a new reporter on a service that is not live yet, as InviteReporter
    leaves it: the invitee and their post, the number in the protected contact store, the
    registration, the invitation and its link token. Returns the token text."""
    hasher = HmacPhoneHasher(container.secrets)
    clock = container.clock
    phone_hash = hasher.hash(mobile)
    expiry = expires_at if expires_at is not None else NOW + timedelta(hours=40)
    with bind_tenant(tenant):
        async with container.uow_factory() as uow:
            await uow.services.save(replace(profile(service_id, service_name), active=False))
            await uow.people.save_practitioner(
                Practitioner(
                    id="invitee-1", active=True, display_name="Reporter", phone_hash=phone_hash
                )
            )
            await uow.people.save_role(
                PractitionerRole(
                    id="role-invitee",
                    practitioner_id="invitee-1",
                    service_id=service_id,
                    code=PractitionerRoleCode.DUTY_MANAGER,
                    active=True,
                    channel=Channel.TEXT,
                    period_start=NOW - timedelta(hours=8),
                )
            )
            await uow.contacts.put_phone("role-invitee", "+44" + mobile.replace(" ", "")[1:])
            await uow.registrations.add(
                Registration(
                    id="reg-1",
                    service_id=service_id,
                    status=RegistrationStatus.INVITED,
                    requester_role_id="role-invitee",
                    owner_role_id=None,
                    created_at=NOW - timedelta(hours=8),
                    last_modified=NOW - timedelta(hours=8),
                )
            )
            await uow.registrations.add_invitation(
                Invitation(
                    id="inv-1",
                    service_id=service_id,
                    registration_id="reg-1",
                    requester_role_id="role-lead",
                    invitee_id="invitee-1",
                    role_label="Duty manager",
                    created_at=NOW - timedelta(hours=8),
                    sent_at=NOW - timedelta(hours=8),
                    expires_at=expiry,
                )
            )
            token = await LinkTokenService(uow.link_tokens, container.secrets, clock).issue(
                INVITATION_PURPOSE, "inv-1", phone_hash, expiry
            )
            if used:
                await LinkTokenService(uow.link_tokens, container.secrets, clock).burn(token, "k")
            await uow.commit()
    return token


async def hold_code(
    container: Container, tenant: str, mobile: str = MOBILE, purpose: str = "setup"
) -> None:
    """Put the code a person was texted into the code store, as a request would have."""
    phone_hash = HmacPhoneHasher(container.secrets).hash(mobile)
    stored = code_hash(SECRETS[CODE_HMAC_SECRET], phone_hash, purpose, CODE)
    with bind_tenant(tenant):
        await container.codes.save(purpose, phone_hash, stored, CodeState(NOW))


async def build_app(container: Container) -> FastAPI:
    app = create_app(container)
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    app.state.cache = container.cache
    return app


def client_for(app: FastAPI, host: str, peer: str = "203.0.113.9") -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False, client=(peer, 1)),
        base_url=f"https://{host}",
    )


async def seed_host_and_head(driver: AsyncDriver, tenant: str, host: str) -> None:
    from tests.support.tenancy import as_tenant

    with as_tenant(tenant):
        await ensure_audit_head(driver)
    await seed_tenant_host(driver, tenant, host)
