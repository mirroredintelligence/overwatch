"""Outbound ports: service profiles and capacity reports (P01).

Adapters: Neo4jServiceRepository and Neo4jCapacityRepository in adapters/outbound/graph_store/.
Reports are never updated or deleted: a correction is a new report.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from diucs.domain.codes import AlertKind, RegistrationStatus
from diucs.domain.model.alerts import AlertRecord, AlertSubscription
from diucs.domain.model.booking import Booking
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.case import Case
from diucs.domain.model.clinical import ClinicalRequestRecord
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.flags import ReportFlag, ServiceFlag
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import Registration, ScopeEntry
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.service_move import ServiceMove


class ServiceRepository(Protocol):
    async def get(self, service_id: str) -> ServiceProfile | None:
        """The stored profile, or None if there is no such service."""
        ...

    async def get_versioned(self, service_id: str) -> tuple[ServiceProfile, int] | None:
        """The stored profile and the version of the stored resource it was read from, in one
        read, or None if there is no such service. Raises ValidationFailed for a service that has
        no profile yet (a scope-list entry that has not registered, lesson L104). R04 builds the
        ETag of a service from the version."""
        ...

    async def list_active(self) -> list[ServiceProfile]:
        """Every active service, sorted by name."""
        ...

    async def save(self, profile: ServiceProfile) -> None:
        """Insert the profile, or replace the stored one."""
        ...


class CapacityRepository(Protocol):
    async def add(self, report: CapacityReport) -> None:
        """Store a new report. A report id that already exists raises Conflict."""
        ...

    async def get(self, report_id: str) -> CapacityReport | None:
        """The report with this id, or None. The id is the report's own id, not the service's."""
        ...

    async def latest(self, service_id: str) -> CapacityReport | None:
        """The report with the greatest effective time, or None."""
        ...

    async def latest_for_services(self, service_ids: Sequence[str]) -> dict[str, CapacityReport]:
        """The latest report per service. Services with no report are left out."""
        ...

    async def reports_since(self, service_id: str, since: datetime) -> list[CapacityReport]:
        """Reports effective at or after `since`, oldest first."""
        ...

    async def reports_between(self, start: datetime, end: datetime) -> list[CapacityReport]:
        """Reports of every service effective at or after `start` and before `end` (U35), oldest
        first."""
        ...

    async def last_report_times(self) -> dict[str, datetime | None]:
        """For every active service, the effective time of its latest report, or None."""
        ...

    async def lock_service(self, service_id: str) -> None:
        """Take the service's write lock for the rest of the unit of work. Two writers that decide
        a per-service count (confirmations in a row) must lock first, then read (DEC-112 item 8).
        Writes nothing; an unknown service is left for the caller to refuse."""
        ...

    async def trailing_confirmations(self, service_id: str) -> int:
        """How many confirmed reports come after the last number report, newest first by
        effective time. All of them when the service has no number report."""
        ...

    async def latest_confirmation_at(self, service_id: str) -> datetime | None:
        """The effective time of the newest confirmed report of the service, or None when it has
        none (DEC-140). Numbers do not count."""
        ...


class BookingRepository(Protocol):
    async def add(self, booking: Booking) -> None:
        """Store a new booking. A booking id that already exists raises Conflict."""
        ...

    async def get(self, booking_id: str) -> Booking | None:
        """The stored booking, or None."""
        ...

    async def get_by_reference(self, reference: str) -> Booking | None:
        """The most recently requested booking with this reference, or None."""
        ...

    async def save(self, booking: Booking) -> None:
        """Replace the stored booking. An unknown id raises NotFound."""
        ...

    async def open_for_service(self, service_id: str) -> list[Booking]:
        """The bookings for this service that are still requested."""
        ...

    async def open_for_services(self, service_ids: Sequence[str]) -> dict[str, list[Booking]]:
        """The open bookings per service. Every requested service id is a key, with [] if none."""
        ...

    async def confirmed_since(self, service_id: str, since: datetime) -> list[datetime]:
        """confirmed_at of bookings whose status is exactly confirmed, at or after `since`."""
        ...

    async def confirmed_since_for_services(
        self, service_ids: Sequence[str], since: datetime
    ) -> dict[str, list[datetime]]:
        """For each service, the confirmed_at of its bookings whose status is exactly confirmed,
        at or after `since`. Every requested id is a key, with [] if none. One query for all the
        services (Q-BOOK-CONFIRMED-FOR, DEC-088)."""
        ...

    async def confirmed_between(self, start: datetime, end: datetime) -> list[Booking]:
        """Bookings whose confirmation is at or after `start` and before `end` (U35), with their
        requested and confirmed times."""
        ...

    async def pending_count(self, service_id: str) -> int:
        """How many bookings for this service are requested (Q-BOOK-PENDING)."""
        ...


class PersonRepository(Protocol):
    """Practitioners and their posts (P03). Adapter: Neo4jPersonRepository (graph_store/).

    A role's period and cover are read at the `now` the caller passes. Services are returned with
    the service's name, sorted by service name, then service id, then role id (DEC-065 item 2).
    Saves refuse an unknown practitioner, service or cover practitioner with NotFound, checked
    before anything is written.
    """

    async def get_practitioner(self, practitioner_id: str) -> Practitioner | None:
        """The stored practitioner, or None."""
        ...

    async def find_by_phone_hash(self, phone_hash: str) -> Practitioner | None:
        """The active practitioner holding this phone hash, or None. Inactive people are never
        returned. Two active practitioners on one hash raise Conflict and return nothing
        (DEC-065 item 1). A malformed hash raises ValidationFailed."""
        ...

    async def roles_for_practitioner(self, practitioner_id: str) -> list[PractitionerRole]:
        """The active roles this practitioner owns, whatever their code."""
        ...

    async def services_for_phone_hash(
        self, phone_hash: str, now: datetime
    ) -> list[tuple[PractitionerRole, str]]:
        """Every active reporter role this phone holds and is not covered out of at `now`, plus
        every active reporter role it covers until after `now`. Each comes with its service name,
        sorted by service name, then service id, then role id (DEC-065 item 2). A malformed phone
        hash raises ValidationFailed."""
        ...

    async def reporter_roles_for_service(
        self, service_id: str, now: datetime
    ) -> list[PractitionerRole]:
        """The active reporter roles of this service in effect at `now`. A covered role is included
        as stored; the caller resolves the holder with role_holder."""
        ...

    async def save_practitioner(self, practitioner: Practitioner) -> None:
        """Insert the practitioner, or replace the stored one."""
        ...

    async def save_role(self, role: PractitionerRole) -> None:
        """Insert the role, or replace the stored one, with its channel and cover links. Replacing
        without a cover removes the cover link."""
        ...


class CaseRepository(Protocol):
    """Advisor cases: a Patient stub, a ServiceRequest and the referrer's score Observations (P21).
    Adapter: Neo4jCaseRepository (graph_store/case_repository.py).

    The postcode and needs are cleared when the case closes, and no copy of them survives (the
    stub and the request keep no history). Scores and the reference never change once recorded,
    and a closed case cannot be reopened.
    """

    async def add(self, case: Case) -> None:
        """Store a new case with its scores. A case id that already exists raises Conflict."""
        ...

    async def get(self, case_id: str) -> Case | None:
        """The stored case, open or closed, or None."""
        ...

    async def get_by_reference(self, reference: str) -> Case | None:
        """The case with this reference, or None."""
        ...

    async def opened_between(self, start: datetime, end: datetime) -> list[Case]:
        """Cases opened at or after `start` and before `end` (U35), oldest first."""
        ...

    async def save(self, case: Case) -> None:
        """Replace the stored case. An unknown id raises NotFound. A change to the scores or the
        reference raises ValidationFailed, and reopening a closed case raises InvalidTransition.
        All of these are checked before anything is written."""
        ...


class CriteriaRepository(Protocol):
    """Service criteria versions (P04).
    Adapter: Neo4jCriteriaRepository (graph_store/criteria_repository.py).

    Each version is stored with its own id and is never deleted. At most one version per service
    is current. Saving a current version moves the service's CURRENT_CRITERIA link in the same
    transaction. Writes check everything before the first change.
    """

    async def current_for_service(self, service_id: str) -> ServiceCriteria | None:
        """The current version for this service, or None. Two current versions raise Conflict."""
        ...

    async def current_for_services(self, service_ids: Sequence[str]) -> dict[str, ServiceCriteria]:
        """The current version per service. Services without a current version are left out."""
        ...

    async def get(self, criteria_id: str) -> ServiceCriteria | None:
        """The stored version with this id, or None. A service flag is not a criteria version."""
        ...

    async def add(self, criteria: ServiceCriteria) -> None:
        """Store a new version. An id that exists raises Conflict, an unknown service or superseded
        version raises NotFound, a version number already used for the service raises Conflict, and
        a second current version raises Conflict. Nothing is written when any of these holds."""
        ...

    async def save(self, criteria: ServiceCriteria) -> None:
        """Replace a stored version. An unknown id raises NotFound. A change of service or version
        number raises ValidationFailed. A second current version raises Conflict."""
        ...

    async def history(self, service_id: str) -> list[ServiceCriteria]:
        """Every version for this service, newest version number first. Old versions are kept."""
        ...


class RegistrationRepository(Protocol):
    """Service registrations, stored as Task code register-service (P13).
    Adapter: Neo4jRegistrationRepository (graph_store/registration_repository.py).

    The repository stores what it is given. It does not decide which status may follow which:
    the use cases do that with transition_registration (D22). Adding for an unknown service is
    NotFound and writes nothing.
    """

    async def add(self, registration: Registration) -> None:
        """Store a new registration. An id that exists raises Conflict."""
        ...

    async def get(self, registration_id: str) -> Registration | None:
        """The stored registration, or None."""
        ...

    async def save(self, registration: Registration) -> None:
        """Replace the stored registration, including its draft. An unknown id raises NotFound.
        A draft is replaced as a whole: fields left out of the new draft are gone."""
        ...

    async def list_by_status(self, status: RegistrationStatus) -> list[Registration]:
        """Registrations with this status, oldest submission first. Drafts have no submission time
        and so are only listed under draft, ordered by id."""
        ...

    async def for_service(self, service_id: str) -> list[Registration]:
        """Registrations for this service, newest first."""
        ...


class ScopeListRepository(Protocol):
    """The scope list: one list whose entries point at services, which may not have registered yet
    (P13). Adapter: Neo4jScopeListRepository (graph_store/scope_list_repository.py).

    save_entry for an unknown service creates a minimal inactive HealthcareService. It never
    changes an existing service's name, category or active flag.
    """

    async def entries(self) -> list[ScopeEntry]:
        """Every entry, sorted by service name, then service id."""
        ...

    async def get_entry(self, service_id: str) -> ScopeEntry | None:
        """The entry for this service, or None."""
        ...

    async def save_entry(self, entry: ScopeEntry) -> None:
        """Insert the entry, or replace its flag, date and reason. Services that do not exist yet
        are created as minimal inactive HealthcareServices."""
        ...


class FlagRepository(Protocol):
    """Report flags (platform nodes on an Observation) and service flags (Basic, ServiceFlag)
    (P14). Adapter: Neo4jFlagRepository (graph_store/flag_repository.py).

    A report flag is never edited except for its resolution: a resolved flag is not changed again.
    A service flag is one per service and code; setting it again replaces it, and an inactive flag
    stays stored but is not returned.
    """

    async def add_report_flag(self, flag: ReportFlag) -> None:
        """Store a new report flag on its report. An unknown report raises NotFound, a report of
        another service raises ValidationFailed, and an id that exists raises Conflict."""
        ...

    async def report_flag(self, flag_id: str) -> ReportFlag | None:
        """The report flag with this id, open or resolved, or None (U39)."""
        ...

    async def open_report_flags(self, service_id: str | None = None) -> list[ReportFlag]:
        """Open report flags, oldest first, for one service or for all services."""
        ...

    async def save_report_flag(self, flag: ReportFlag) -> None:
        """Record the resolution of a flag. An unknown id raises NotFound. A change to its report,
        service, reason or creation time raises ValidationFailed. A flag already resolved raises
        InvalidTransition."""
        ...

    async def service_flags(self, service_id: str) -> list[ServiceFlag]:
        """The active service flags of this service."""
        ...

    async def set_service_flag(self, flag: ServiceFlag) -> None:
        """Set the flag for this service and code, replacing any earlier one. An unknown service
        raises NotFound and writes nothing."""
        ...

    async def services_with_flag(self, code: str) -> set[str]:
        """The ids of services with an active service flag with this code."""
        ...


class AlertSubscriptionRepository(Protocol):
    """Alert preferences, one per practitioner (P17). Adapter: Neo4jAlertSubscriptionRepository
    (graph_store/alert_repository.py). Saving again replaces the practitioner's subscription."""

    async def get_for_practitioner(self, practitioner_id: str) -> AlertSubscription | None:
        """The stored subscription of this practitioner, or None."""
        ...

    async def save(self, subscription: AlertSubscription) -> None:
        """Insert the subscription, or replace the practitioner's stored one. An unknown
        practitioner raises NotFound and writes nothing."""
        ...

    async def subscribers_for_kind(self, kind: AlertKind) -> list[AlertSubscription]:
        """The subscriptions of the bound tenant that have this alert kind switched on."""
        ...


class AlertRepository(Protocol):
    """Alerts, stored as Task code acknowledge-alert (P17). Adapter: Neo4jAlertRepository."""

    async def add(self, alert: AlertRecord) -> None:
        """Store a new alert. An id that exists raises Conflict."""
        ...

    async def get(self, alert_id: str) -> AlertRecord | None:
        """The stored alert, or None."""
        ...

    async def save(self, alert: AlertRecord) -> None:
        """Replace the stored alert. An unknown id raises NotFound."""
        ...

    async def open_for_owner(self, practitioner_id: str) -> list[AlertRecord]:
        """The alerts owned by this practitioner that are still new."""
        ...

    async def chain(self, alert_id: str) -> list[AlertRecord]:
        """The alert and every alert it escalates from, from the root through each partOf link,
        oldest first. An unknown id raises NotFound."""
        ...


class ClinicalRequestRepository(Protocol):
    """Clinical advice requests, stored as Task code clinical-advice-request (P18). Adapter:
    Neo4jClinicalRequestRepository (graph_store/clinical_request_repository.py). The queue order is
    the one of queue_order (D23): now before within-15-min, then oldest first. Presence is not
    stored here."""

    async def add(self, record: ClinicalRequestRecord) -> None:
        """Store a new request. An id that exists raises Conflict."""
        ...

    async def get(self, request_id: str) -> ClinicalRequestRecord | None:
        """The stored request, or None."""
        ...

    async def save(self, record: ClinicalRequestRecord) -> None:
        """Replace the stored request. An unknown id raises NotFound; a stale version raises
        Conflict."""
        ...

    async def waiting(self) -> list[ClinicalRequestRecord]:
        """The requests nobody has taken, in queue order."""
        ...

    async def taken_by(self, clinician_id: str) -> list[ClinicalRequestRecord]:
        """The requests this clinician has taken and not yet advised on."""
        ...


class ServiceMoveRepository(Protocol):
    """Service moves (P20, U38). Adapter: Neo4jServiceMoveRepository
    (graph_store/service_move_repository.py). Only the phone hash is stored, never the number."""

    async def add(self, move: ServiceMove) -> None:
        """Store a new move. A second open move for the service raises Conflict, an id that exists
        raises Conflict, and a service or practitioner that is not there raises NotFound."""
        ...

    async def get(self, move_id: str) -> ServiceMove | None:
        """The stored move, or None."""
        ...

    async def save(self, move: ServiceMove) -> None:
        """Record the times of a move (verified, callback, completed, cancelled, until). A change
        to its service, practitioner or phone hash raises ValidationFailed; an unknown id raises
        NotFound."""
        ...

    async def open_for_service(self, service_id: str) -> list[ServiceMove]:
        """The moves of this service that are not completed and not cancelled."""
        ...
