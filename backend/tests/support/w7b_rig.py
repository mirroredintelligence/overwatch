"""A route-test rig for the W7B routes: the container the routes read (stubs, no Neo4j) and a world
of one invited registration, built the way `InviteReporter` writes it (U24). Test doubles for unit
tests of routes and use cases, not stores of record (DEC-004). Sample values only."""

import random
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_geo import FixedGeocoder
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.fixed_terminology import FixedTerminology
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_code_store import InMemoryCodeStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.pin import PIN_HMAC_SECRET
from diucs.application.use_cases.registration_draft import (
    ApiStep,
    LocationStep,
    OrganisationStep,
    ReportingStep,
    ServiceStep,
    encode_step,
)
from diucs.application.use_cases.registration_submit import Lookups, encode_lookups
from diucs.application.use_cases.text_code import CODE_HMAC_SECRET, INVITATION_PURPOSE
from diucs.application.work import ScheduledWork, WorkKind
from diucs.domain.codes import (
    PractitionerRoleCode,
    RegistrationStatus,
    Role,
    ScopeFlag,
    ServiceCategory,
)
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import Invitation, Registration, ScopeEntry
from diucs.domain.model.tenant import ConfigStatus, TenantConfig, TenantContact, TenantStatus
from diucs.domain.rules.tokens import LinkTokenRecord, hash_token
from tests.support.registration_rig import StubLimiter, StubPeople, StubUnits
from tests.support.session_rig import StubSessions
from tests.support.tenant_samples import make_tenant

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
HOST = "tenant-a.example.test"
SUSPENDED_HOST = "tenant-s.example.test"
UNKNOWN_HOST = "tenant-x.example.test"
TENANT = "example-icb"
SECRETS = {
    BFF_SECRET_NAME: TEST_BFF_SECRET,
    PHONE_HASH_SECRET: b"phone-hash-w7b-test-secret-0123456789abcd",
    CODE_HMAC_SECRET: b"code-hmac-w7b-test-secret-0123456789abcde",
    PIN_HMAC_SECRET: b"pin-hmac-w7b-test-secret-0123456789abcdef",
    LINK_TOKEN_SECRET: b"link-token-w7b-test-secret-0123456789abc",
}
MOBILE = "07700 900123"
INTERNATIONAL = "+447700900123"
CODE = "482913"
DEVICE = "device-aaaaaaaaaaaaaaaaaaaaaa"
INVITE_TOKEN = "AbCdEfGhIjKlMnOpQrStUvW"
INVITEE = "prac-invitee"
LEAD = "prac-lead"
SERVICE = "svc-ucr-west"
SERVICE_NAME = "UCR West"
REGISTRATION = "reg-1"
INVITATION = "inv-1"
APPLICANT_ROLE = "role-applicant"
LEAD_ROLE = "role-lead"
JSON = {"Content-Type": "application/json"}


ORG = OrganisationStep(
    name="Community Response Ltd",
    ods_code="RXX01",
    org_type="nhs-trust",
    contact_name="Sam Patel",
    contact_email="sam.patel@example.org",
    contact_phone="01305 000111",
)
SITE = LocationStep(
    fixed_site=True,
    postcode="DT4 8XX",
    address="1 Sample Road, Weymouth",
    site_name="Sample Ward",
    site_type="ward",
    open_24h=True,
)
SERVICE_STEP = ServiceStep(
    service_name=SERVICE_NAME,
    category="urgent-community-response",
    referral_methods="phone",
    spoa_phone="01305 123400",
    accepting_days="mon,tue",
    accepting_start="08:00",
    accepting_end="20:00",
    needs="frailty",
    age_min=18,
    no_age_limit=True,
    no_exclusions=True,
    owner_role="Clinical lead, UCR",
    owner_email="owner@example.org",
    review_by=date(2027, 1, 1),
    districts="DT4",
)
REPORTING = ReportingStep(
    measure="referrals-acceptable",
    usual_low=0,
    usual_high=8,
    cadence="every-2-hrs",
    channel="text",
    holder_name="Duty coordinator",
)
REPORTING_MOBILE = "07700 900456"
LOOKUPS = Lookups(True, True, "COMMUNITY RESPONSE LTD", "PILOT-SAMPLE", True, "DT4", NOW)


class W7BPeople(StubPeople):
    """The people stub with the one read the views add: a role by id."""

    async def get_role(self, role_id: str) -> PractitionerRole | None:
        return self.roles.get(role_id)


class StubScheduledWork:
    """Scheduled work by about id."""

    def __init__(self) -> None:
        self.held: list[ScheduledWork] = []

    async def for_about(self, about_id: str, kind: WorkKind | None = None) -> list[ScheduledWork]:
        return [
            work
            for work in self.held
            if work.about_id == about_id and (kind is None or work.kind is kind)
        ]


class StubTenantConfig:
    """The tenant configuration: only the current version, with its wording."""

    def __init__(self) -> None:
        self.config: TenantConfig | None = None
        self.contact_list: tuple[TenantContact, ...] = ()

    async def current_version(self) -> TenantConfig | None:
        return self.config

    async def contacts(self) -> tuple[TenantContact, ...]:
        return self.contact_list

    def give_wording(self) -> None:
        self.config = TenantConfig(
            version=1,
            status=ConfigStatus.CURRENT,
            values={
                "systemName": "Sample urgent care",
                "referralSystemName": "Sample directory",
                "coordinationTeamName": "The sample SPOA team",
            },
            created_at=NOW,
            created_by_ref="person-a",
            effective_from=NOW,
            approved_by_refs=("person-b", "person-c"),
        )


class _Directory:
    def __init__(self) -> None:
        self._by_host = {
            HOST: make_tenant(id=TENANT),
            SUSPENDED_HOST: make_tenant(TenantStatus.SUSPENDED),
        }

    async def get(self, tenant_id: str) -> Any:
        return make_tenant(id=tenant_id)

    async def by_host(self, host: str) -> Any:
        return self._by_host.get(host)


class _Sealer:
    def seal(self, content: str, *, message_id: str, tenant_id: str, recipient_role_id: str) -> str:
        return f"sealed:{message_id}"

    def unseal(
        self, sealed: str, *, message_id: str, tenant_id: str, recipient_role_id: str
    ) -> str:
        raise AssertionError("a route never opens a sealed message")


@dataclass
class _LinkBase:
    def __call__(self, scope: ScopeId) -> str:
        return f"https://{HOST}"


class Rig:
    """The container the W7B routes read, over `StubUnits`."""

    def __init__(self) -> None:
        self.clock = FixedClock(NOW)
        self.ids = SequentialIds()
        self.rng = random.Random(7)
        self.units = StubUnits(ScopeId.tenant(TENANT))
        self.units.people = W7BPeople(self.units.writes, self.units.calls)
        self.units.scheduled_work = StubScheduledWork()
        self.units.tenant_config = StubTenantConfig()
        self.uow_factory = self.units
        self.tenants = _Directory()
        self.secrets = FixedSecretStore(SECRETS)
        self.codes = InMemoryCodeStore(self.clock)
        self.sessions = StubSessions(self.units.events)
        self.rate_limiter = StubLimiter()
        self.sealer = _Sealer()
        self.cache = InMemoryCache(self.clock)
        self.hasher = HmacPhoneHasher(self.secrets)
        self.geocoder = FixedGeocoder({})
        self.terminology = FixedTerminology({}, {})
        self.link_base_url_for = _LinkBase()

    def invite(self, status: RegistrationStatus = RegistrationStatus.INVITED) -> str:
        """One invited registration for the service, with the applicant's post and number, the
        lead's post, the scope entry and an open invitation link. Returns the link token."""
        units = self.units
        phone_hash = self.hasher.hash(MOBILE)
        units.people.practitioners[INVITEE] = Practitioner(
            id=INVITEE, active=True, display_name="Duty manager", phone_hash=phone_hash
        )
        units.people.practitioners[LEAD] = Practitioner(
            id=LEAD, active=True, display_name="Shift lead", phone_hash=None
        )
        units.people.roles[APPLICANT_ROLE] = PractitionerRole(
            id=APPLICANT_ROLE,
            practitioner_id=INVITEE,
            service_id=SERVICE,
            code=PractitionerRoleCode.DUTY_MANAGER,
            active=True,
            channel=None,
            period_start=NOW - timedelta(hours=1),
        )
        units.people.roles[LEAD_ROLE] = PractitionerRole(
            id=LEAD_ROLE,
            practitioner_id=LEAD,
            service_id=None,
            code=PractitionerRoleCode.SHIFT_LEAD,
            active=True,
            channel=None,
            period_start=NOW - timedelta(days=30),
        )
        units.contacts.phones[APPLICANT_ROLE] = INTERNATIONAL
        units.scope.entries_by_service[SERVICE] = ScopeEntry(
            SERVICE,
            SERVICE_NAME,
            ServiceCategory.URGENT_COMMUNITY_RESPONSE,
            ScopeFlag.IN_PILOT,
            date(2026, 10, 1),
        )
        created = NOW - timedelta(hours=1)
        units.registrations.held[REGISTRATION] = Registration(
            id=REGISTRATION,
            service_id=SERVICE,
            status=status,
            requester_role_id=APPLICANT_ROLE,
            owner_role_id=None,
            created_at=created,
            last_modified=created,
        )
        units.registrations.invitations[INVITATION] = Invitation(
            id=INVITATION,
            service_id=SERVICE,
            registration_id=REGISTRATION,
            requester_role_id=LEAD_ROLE,
            invitee_id=INVITEE,
            role_label="Duty manager",
            created_at=created,
            sent_at=created,
            expires_at=created + timedelta(hours=48),
        )
        self.link(INVITE_TOKEN, phone_hash)
        return INVITE_TOKEN

    def fill(
        self,
        status: RegistrationStatus = RegistrationStatus.SUBMITTED,
        *,
        steps: tuple[str, ...] = ("organisation", "location", "service", "reporting", "api"),
        **changes: Any,
    ) -> None:
        """Fill the registration's draft with a complete, sample application and move it to
        `status`. The reporting contact is the applicant's own number (held by the contact store,
        not the draft), which is not the number the invitation holds."""
        registration = self.units.registrations.held[REGISTRATION]
        every = {
            "organisation": ORG,
            "location": SITE,
            "service": SERVICE_STEP,
            "reporting": REPORTING,
            "api": ApiStep(wanted=False),
        }
        draft = {name: encode_step(every[name]) for name in steps}
        draft["lookups"] = encode_lookups(LOOKUPS)
        self.units.contacts.phones[APPLICANT_ROLE] = REPORTING_MOBILE
        self.units.registrations.held[REGISTRATION] = replace(
            registration,
            status=status,
            draft=draft,
            submitted_at=NOW - timedelta(minutes=30),
            **changes,
        )

    def link(
        self,
        token: str,
        phone_hash: str | None,
        *,
        expires_in: timedelta = timedelta(hours=47),
        used: bool = False,
        about: str = INVITATION,
    ) -> None:
        record = LinkTokenRecord(
            token_hash=hash_token(token, SECRETS[LINK_TOKEN_SECRET]),
            purpose=INVITATION_PURPOSE,
            about_id=about,
            phone_hash=phone_hash,
            expires_at=NOW + expires_in,
            used_at=NOW - timedelta(minutes=1) if used else None,
        )
        self.units.link_tokens.records[record.token_hash] = record

    async def hold_code(
        self, mobile: str = MOBILE, purpose: str = "setup", code: str = CODE
    ) -> None:
        from diucs.application.use_cases.text_code import code_hash
        from diucs.domain.rules.identity_policy import CodeState

        phone_hash = self.hasher.hash(mobile)
        stored = code_hash(SECRETS[CODE_HMAC_SECRET], phone_hash, purpose, code)
        await self.codes.save(purpose, phone_hash, stored, CodeState(NOW - timedelta(seconds=30)))


def client(rig: Rig, host: str = HOST, address: str = "203.0.113.9") -> httpx.AsyncClient:
    app = create_app(rig)  # type: ignore[arg-type]
    app.state.secrets = rig.secrets
    app.state.cache = rig.cache
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False, client=(address, 1234)),
        base_url=f"http://{host}",
    )


def bearer(
    role: Role,
    sub: str,
    services: tuple[str, ...] = (),
    *,
    device: str | None = None,
    tenant: str = TENANT,
) -> dict[str, str]:
    token = issue_test_token(
        role,
        list(services),
        sub,
        tenant=tenant,
        device=device,
        expires_at=NOW + timedelta(hours=8),
    )
    return {"Authorization": f"Bearer {token}"}
