"""SetupServiceByLead: a shift lead sets up one service for the pilot (U15).

Red stub: the names and signatures the unit tests use. Behaviour arrives in the implement commit.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import PhoneHasher
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Cadence, Channel, Measure, NeedCategory, ServiceCategory
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.service import AvailableTime, ServiceProfile


@dataclass(frozen=True, slots=True)
class SetupServiceCommand:
    idempotency_key: str
    actor: Actor
    name: str
    category: ServiceCategory
    measure: Measure
    unit_label: str
    established_capacity: int
    usual_range: tuple[int, int]
    cadence: Cadence
    available_times: tuple[AvailableTime, ...]
    channel: Channel
    reporter_role_name: str
    age_min: int
    districts: frozenset[str]
    accepts: frozenset[NeedCategory]
    review_by: date
    owner_role_name: str
    phone: str | None = None
    email: str | None = None
    age_max: int | None = None
    excludes: frozenset[NeedCategory] = frozenset()


@dataclass(frozen=True, slots=True)
class SetupServiceResult:
    service_id: str
    practitioner_id: str
    role_id: str
    criteria_id: str
    first_prompt_at: datetime


@dataclass(frozen=True, slots=True)
class ReporterContact:
    channel: Channel
    phone: str | None
    email: str | None


def check_may_set_up(actor: Actor) -> None:
    raise NotImplementedError


def check_role_name(field: str, value: str) -> None:
    raise NotImplementedError


def reporter_contact(channel: Channel, phone: str | None, email: str | None) -> ReporterContact:
    raise NotImplementedError


def international(national: str) -> str:
    raise NotImplementedError


def build_profile(command: SetupServiceCommand, service_id: str) -> ServiceProfile:
    raise NotImplementedError


def build_criteria(
    command: SetupServiceCommand, criteria_id: str, service_id: str, owner_role_id: str
) -> ServiceCriteria:
    raise NotImplementedError


def first_prompt_at(profile: ServiceProfile, now: datetime) -> datetime:
    raise NotImplementedError


def command_fingerprint(command: SetupServiceCommand, contact_key: str) -> str:
    raise NotImplementedError


def setup_snapshot(
    command: SetupServiceCommand,
    *,
    service_id: str,
    practitioner_id: str,
    role_id: str,
    owner_role_id: str,
    criteria_id: str,
    first_prompt: datetime,
) -> dict[str, Any]:
    raise NotImplementedError


class SetupServiceByLead:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
        phone_hasher: PhoneHasher,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency
        self._phone_hasher = phone_hasher

    async def execute(self, command: SetupServiceCommand) -> SetupServiceResult:
        raise NotImplementedError
