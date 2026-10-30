"""Recording stand-ins for the ports the registration and sign-in use cases touch (W2E).

They are test doubles for a unit test that checks the order and the content of a use case's calls,
not stores of record: nothing here survives a test, and no use-case flow is proved against them
(that is the integration tests' job against the real graph, DEC-004). Every write is also logged in
`unit.writes`, so a test can show that a refused command wrote nothing. Sample values only.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from types import TracebackType
from typing import Any, Self

from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.messaging import Communication, PushSubscription
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.tenancy import ScopeId
from diucs.domain.codes import PractitionerRoleCode, Role
from diucs.domain.model.flags import ServiceFlag
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import Invitation, Registration, ScopeEntry
from diucs.domain.rules.identity_policy import PinState
from diucs.domain.rules.tokens import LinkTokenRecord


@dataclass
class Writes:
    """Every write, in order, as `port.method`. A refused command leaves this empty."""

    names: list[str] = field(default_factory=list)


class _Part:
    def __init__(self, writes: Writes, name: str) -> None:
        self._writes = writes
        self._name = name

    def wrote(self, method: str) -> None:
        self._writes.names.append(f"{self._name}.{method}")


class StubPeople(_Part):
    def __init__(self, writes: Writes, calls: list[str] | None = None) -> None:
        super().__init__(writes, "people")
        self.practitioners: dict[str, Practitioner] = {}
        self.roles: dict[str, PractitionerRole] = {}
        self.reads: list[str] = calls if calls is not None else []

    async def get_practitioner(self, practitioner_id: str) -> Practitioner | None:
        self.reads.append("people.get_practitioner")
        return self.practitioners.get(practitioner_id)

    async def find_by_phone_hash(self, phone_hash: str) -> Practitioner | None:
        found = [
            person
            for person in self.practitioners.values()
            if person.active and person.phone_hash == phone_hash
        ]
        return found[0] if found else None

    async def roles_for_practitioner(self, practitioner_id: str) -> list[PractitionerRole]:
        return [
            role
            for role in self.roles.values()
            if role.practitioner_id == practitioner_id and role.active
        ]

    async def reporter_roles_for_service(
        self, service_id: str, now: datetime
    ) -> list[PractitionerRole]:
        return [
            role
            for role in self.roles.values()
            if role.service_id == service_id
            and role.active
            and role.code in (PractitionerRoleCode.DUTY_MANAGER, PractitionerRoleCode.COORDINATOR)
            and role.period_start <= now
            and (role.period_end is None or now < role.period_end)
        ]

    async def services_for_phone_hash(
        self, phone_hash: str, now: datetime
    ) -> list[tuple[PractitionerRole, str]]:
        """The active reporter roles the phone holds or covers at `now` (names are the ids)."""
        holders = {
            person.id for person in self.practitioners.values() if person.phone_hash == phone_hash
        }
        found: list[tuple[PractitionerRole, str]] = []
        for role in self.roles.values():
            if not role.active or role.code not in (
                PractitionerRoleCode.DUTY_MANAGER,
                PractitionerRoleCode.COORDINATOR,
            ):
                continue
            covering = (
                role.covered_by_practitioner_id in holders
                and role.covered_until is not None
                and now < role.covered_until
            )
            covered_out = (
                role.practitioner_id in holders
                and role.covered_until is not None
                and now < role.covered_until
            )
            if covering or (role.practitioner_id in holders and not covered_out):
                found.append((role, role.service_id or ""))
        return found

    async def save_practitioner(self, practitioner: Practitioner) -> None:
        self.wrote("save_practitioner")
        self.practitioners[practitioner.id] = practitioner

    async def save_role(self, role: PractitionerRole) -> None:
        self.wrote("save_role")
        self.roles[role.id] = role


class StubRegistrations(_Part):
    def __init__(self, writes: Writes) -> None:
        super().__init__(writes, "registrations")
        self.held: dict[str, Registration] = {}
        self.invitations: dict[str, Invitation] = {}
        self.bundles: list[dict[str, Any]] = []
        self.districts: dict[str, str] = {}
        self.fail_write: Exception | None = None

    async def add(self, registration: Registration) -> None:
        self.wrote("add")
        self.held[registration.id] = registration

    async def get(self, registration_id: str) -> Registration | None:
        return self.held.get(registration_id)

    async def save(self, registration: Registration) -> None:
        self.wrote("save")
        self.held[registration.id] = registration

    async def for_service(self, service_id: str) -> list[Registration]:
        found = [item for item in self.held.values() if item.service_id == service_id]
        return sorted(found, key=lambda item: item.created_at, reverse=True)

    async def list_by_status(self, status: Any) -> list[Registration]:
        return [item for item in self.held.values() if item.status is status]

    async def write_bundle(self, bundle: dict[str, Any]) -> dict[str, str]:
        self.wrote("write_bundle")
        if self.fail_write is not None:
            raise self.fail_write
        self.bundles.append(bundle)
        return {}

    async def district_locations(self, districts: Sequence[str]) -> dict[str, str]:
        return {name: self.districts[name] for name in districts if name in self.districts}

    async def add_invitation(self, invitation: Invitation) -> None:
        self.wrote("add_invitation")
        self.invitations[invitation.id] = invitation

    async def get_invitation(self, invitation_id: str) -> Invitation | None:
        return self.invitations.get(invitation_id)

    async def save_invitation(self, invitation: Invitation) -> None:
        self.wrote("save_invitation")
        self.invitations[invitation.id] = invitation


class StubCriteria(_Part):
    def __init__(self, writes: Writes) -> None:
        super().__init__(writes, "criteria")
        self.current: dict[str, Any] = {}

    async def current_for_service(self, service_id: str) -> Any:
        return self.current.get(service_id)


class StubScope(_Part):
    def __init__(self, writes: Writes) -> None:
        super().__init__(writes, "scope")
        self.entries_by_service: dict[str, ScopeEntry] = {}

    async def get_entry(self, service_id: str) -> ScopeEntry | None:
        return self.entries_by_service.get(service_id)

    async def entries(self) -> list[ScopeEntry]:
        return list(self.entries_by_service.values())


class StubContacts(_Part):
    def __init__(self, writes: Writes) -> None:
        super().__init__(writes, "contacts")
        self.phones: dict[str, str] = {}
        self.emails: dict[str, str] = {}

    async def put_phone(self, role_id: str, number: str) -> None:
        self.wrote("put_phone")
        self.phones[role_id] = number

    async def get_phone(self, role_id: str) -> str | None:
        return self.phones.get(role_id)

    async def put_email(self, role_id: str, email: str) -> None:
        self.wrote("put_email")
        self.emails[role_id] = email

    async def get_email(self, role_id: str) -> str | None:
        return self.emails.get(role_id)


class StubLinkTokens(_Part):
    def __init__(self, writes: Writes) -> None:
        super().__init__(writes, "link_tokens")
        self.records: dict[str, LinkTokenRecord] = {}

    async def add(self, record: LinkTokenRecord) -> None:
        self.wrote("add")
        self.records[record.token_hash] = record

    async def get_by_hash(self, token_hash: str) -> LinkTokenRecord | None:
        return self.records.get(token_hash)

    async def mark_used(self, token_hash: str, at: datetime, key: str) -> bool:
        self.wrote("mark_used")
        record = self.records.get(token_hash)
        if record is None or record.used_at is not None:
            return False
        self.records[token_hash] = replace(record, used_at=at)
        return True

    async def burn_key(self, token_hash: str) -> str | None:
        return None

    async def open_for_phone(
        self, purpose: str, phone_hash: str, now: datetime
    ) -> LinkTokenRecord | None:
        found = [
            record
            for record in self.records.values()
            if record.purpose == purpose
            and record.phone_hash == phone_hash
            and record.used_at is None
            and record.expires_at > now
        ]
        return max(found, key=lambda record: record.expires_at) if found else None

    async def open_for_about(
        self, purpose: str, about_id: str, now: datetime
    ) -> LinkTokenRecord | None:
        found = [
            record
            for record in self.records.values()
            if record.purpose == purpose
            and record.about_id == about_id
            and record.used_at is None
            and record.expires_at > now
        ]
        return max(found, key=lambda record: record.expires_at) if found else None


class StubAudit(_Part):
    def __init__(self, writes: Writes) -> None:
        super().__init__(writes, "audit")
        self.entries: list[AuditEntry] = []
        self.provenance: list[dict[str, Any]] = []

    async def append(self, entry: AuditEntry) -> None:
        self.wrote("append")
        self.entries.append(entry)

    async def append_provenance(
        self,
        target_type: str,
        target_id: str,
        activity: str,
        agent_id: str,
        agent_role: Role,
        source_communication_id: str | None = None,
        extra: dict[str, Any] | None = None,
        agent_type: str = "Practitioner",
    ) -> str:
        self.wrote("append_provenance")
        self.provenance.append(
            {
                "target_type": target_type,
                "target_id": target_id,
                "activity": activity,
                "agent_id": agent_id,
                "agent_role": agent_role,
                "extra": dict(extra or {}),
            }
        )
        return f"prov-{len(self.provenance)}"


class StubOutbox(_Part):
    def __init__(self, writes: Writes) -> None:
        super().__init__(writes, "outbox")
        self.messages: list[OutboxMessage] = []

    async def add(self, message: OutboxMessage) -> None:
        self.wrote("add")
        self.messages.append(message)


class StubCommunications(_Part):
    def __init__(self, writes: Writes) -> None:
        super().__init__(writes, "communications")
        self.sent: list[Communication] = []

    async def add(self, communication: Communication) -> None:
        self.wrote("add")
        self.sent.append(communication)


class StubIdempotency(_Part):
    def __init__(self, writes: Writes) -> None:
        super().__init__(writes, "idempotency")
        self.stored: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self.stored.get(key)

    async def put(self, key: str, result: Any) -> None:
        self.wrote("put")
        self.stored[key] = result


class StubPins(_Part):
    """PIN credentials by (practitioner, device): the stored hash and the lock state."""

    def __init__(self, writes: Writes, calls: list[str]) -> None:
        super().__init__(writes, "pins")
        self.held: dict[tuple[str, str], tuple[str, PinState]] = {}
        self._calls = calls

    async def get(self, practitioner_id: str, device_id: str) -> tuple[str, PinState] | None:
        self._calls.append("pins.get")
        return self.held.get((practitioner_id, device_id))

    async def set_pin(self, practitioner_id: str, device_id: str, pin_hash: str) -> None:
        self.wrote("set_pin")
        self.held[(practitioner_id, device_id)] = (pin_hash, PinState())

    async def save_state(self, practitioner_id: str, device_id: str, state: PinState) -> None:
        self.wrote("save_state")
        pin_hash, _ = self.held[(practitioner_id, device_id)]
        self.held[(practitioner_id, device_id)] = (pin_hash, state)

    async def clear_all(self, practitioner_id: str) -> None:
        self.wrote("clear_all")
        for held in [key for key in self.held if key[0] == practitioner_id]:
            del self.held[held]


class StubDevices(_Part):
    """Devices by (practitioner, device): revoked flag, pending call-back and the last text-code
    verification."""

    def __init__(self, writes: Writes, calls: list[str]) -> None:
        super().__init__(writes, "devices")
        self.held: dict[tuple[str, str], dict[str, Any]] = {}
        self._calls = calls

    async def register(self, practitioner_id: str, device_id: str, at: datetime) -> None:
        self.wrote("register")
        self.held.setdefault(
            (practitioner_id, device_id),
            {"revoked": False, "pending": False, "verified_at": None, "at": at},
        )

    async def register_pending(self, practitioner_id: str, device_id: str, at: datetime) -> None:
        self.wrote("register_pending")
        self.held.setdefault(
            (practitioner_id, device_id),
            {"revoked": False, "pending": True, "verified_at": None, "at": at},
        )

    async def confirm_pending(self, practitioner_id: str, at: datetime) -> int:
        self.wrote("confirm_pending")
        count = 0
        for (person, _device), device in self.held.items():
            if person == practitioner_id and device["pending"] and not device["revoked"]:
                device["pending"] = False
                count += 1
        return count

    async def awaiting_callback(self, practitioner_id: str) -> list[str]:
        self._calls.append("devices.awaiting_callback")
        return sorted(
            device_id
            for (person, device_id), device in self.held.items()
            if person == practitioner_id and device["pending"] and not device["revoked"]
        )

    async def owner_of(self, device_id: str) -> str | None:
        self._calls.append("devices.owner_of")
        owners = [person for (person, held_id) in self.held if held_id == device_id]
        return owners[0] if owners else None

    async def known(self, practitioner_id: str, device_id: str) -> bool:
        self._calls.append("devices.known")
        device = self.held.get((practitioner_id, device_id))
        return device is not None and not device["revoked"] and not device.get("pending", False)

    async def verified_at(self, practitioner_id: str, device_id: str) -> datetime | None:
        self._calls.append("devices.verified_at")
        device = self.held.get((practitioner_id, device_id))
        if device is None or device["revoked"]:
            return None
        verified: datetime | None = device["verified_at"]
        return verified

    async def mark_verified(self, practitioner_id: str, device_id: str, at: datetime) -> None:
        self.wrote("mark_verified")
        self.held[(practitioner_id, device_id)]["verified_at"] = at

    async def revoke_all(self, practitioner_id: str) -> int:
        self.wrote("revoke_all")
        count = 0
        for (person, _device), device in self.held.items():
            if person == practitioner_id and not device["revoked"]:
                device["revoked"] = True
                count += 1
        return count


class StubFlags(_Part):
    """Service flags by (service, code)."""

    def __init__(self, writes: Writes) -> None:
        super().__init__(writes, "flags")
        self.held: dict[tuple[str, str], ServiceFlag] = {}

    async def service_flags(self, service_id: str) -> list[ServiceFlag]:
        return [
            flag
            for (service, _), flag in self.held.items()
            if service == service_id and flag.active
        ]

    async def set_service_flag(self, flag: ServiceFlag) -> None:
        self.wrote("set_service_flag")
        self.held[(flag.service_id, flag.code)] = flag


class StubPush(_Part):
    """Push subscriptions by device id."""

    def __init__(self, writes: Writes) -> None:
        super().__init__(writes, "push_subscriptions")
        self.held: dict[str, PushSubscription] = {}

    async def for_practitioner(self, practitioner_id: str) -> list[PushSubscription]:
        return [sub for sub in self.held.values() if sub.practitioner_id == practitioner_id]

    async def delete(self, device_id: str) -> None:
        self.wrote("delete")
        self.held.pop(device_id, None)


class StubConsents(_Part):
    """Notification consents: the devices whose consent was withdrawn."""

    def __init__(self, writes: Writes) -> None:
        super().__init__(writes, "notification_consents")
        self.withdrawn: list[tuple[str, str]] = []

    async def withdraw(self, practitioner_id: str, device_id: str, at: datetime) -> None:
        self.wrote("withdraw")
        self.withdrawn.append((practitioner_id, device_id))


class StubLimiter:
    """A fixed-window throttle without a window: it counts attempts per key and refuses the ones
    past the limit. It keeps every key it was asked about, so a test can read the keys."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.limits: dict[str, int] = {}

    async def allow(self, key: str, limit: int, window: timedelta) -> bool:
        self.counts[key] = self.counts.get(key, 0) + 1
        self.limits[key] = limit
        return self.counts[key] <= limit


class StubUnit:
    """One unit of work over the stubs. Several `StubUnit`s made by one `StubUnits` share state, so
    a second command sees what the first committed."""

    def __init__(self, shared: StubUnits) -> None:
        self._shared = shared
        self.committed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._shared, name)

    @property
    def unit_scope(self) -> ScopeId:
        return self._shared.scope_id

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True
        self._shared.commits += 1
        self._shared.events.append("commit")

    async def rollback(self) -> None:
        return None


class StubUnits:
    """The shared state of a test's units, and the factory that opens them."""

    def __init__(self, scope: ScopeId | None = None) -> None:
        self.scope_id = scope or ScopeId.tenant("tenant-a")
        self.writes = Writes()
        self.commits = 0
        self.events: list[str] = []
        """Cross-port order of what matters to a test: `commit` and, from a stub session store that
        was given this list, `sessions.revoke`."""
        self.calls: list[str] = []
        self.people = StubPeople(self.writes, self.calls)
        self.registrations = StubRegistrations(self.writes)
        self.scope = StubScope(self.writes)
        self.criteria = StubCriteria(self.writes)
        self.contacts = StubContacts(self.writes)
        self.link_tokens = StubLinkTokens(self.writes)
        self.audit = StubAudit(self.writes)
        self.outbox = StubOutbox(self.writes)
        self.communications = StubCommunications(self.writes)
        self.idempotency = StubIdempotency(self.writes)
        self.pins = StubPins(self.writes, self.calls)
        self.devices = StubDevices(self.writes, self.calls)
        self.flags = StubFlags(self.writes)
        self.push_subscriptions = StubPush(self.writes)
        self.notification_consents = StubConsents(self.writes)

    def __call__(self) -> StubUnit:
        return StubUnit(self)
