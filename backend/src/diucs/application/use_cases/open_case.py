"""OpenCase and UpdateCase: an advisor's case for a patient need (U11, P21, D18, D19).

An advisor opens an empty case at the start of a call, then fills in the age band, the postcode
district, the needs, the urgency and the referrer's scores. Only the district of the postcode is
stored (DEC-067 item 1). The reference is four digits, unique in the tenant among every case
(DEC-067 item 7). The case, its audit entry and its replay record are written in one unit of work.
No outbox message is written: a case sends nothing.

Red stub: the public names and signatures are the contract (see docs/delivery/fragments/U11.md).
The behaviour is not written yet.
"""

import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId
from diucs.domain.codes import AgeBand, NeedCategory, ReferrerType, Urgency
from diucs.domain.model.case import Case
from diucs.domain.model.scores import Score


@dataclass(frozen=True, slots=True)
class OpenCaseCommand:
    idempotency_key: str
    actor: Actor
    referrer_type: ReferrerType


@dataclass(frozen=True, slots=True)
class OpenCaseResult:
    case_id: str
    reference: str


@dataclass(frozen=True, slots=True)
class UpdateCaseCommand:
    idempotency_key: str
    actor: Actor
    case_id: str
    age_band: AgeBand | None = None
    postcode: str | None = None
    needs: tuple[NeedCategory, ...] | None = None
    urgency: Urgency | None = None
    scores: tuple[Score, ...] | None = None


@dataclass(frozen=True, slots=True)
class UpdateCaseResult:
    case_id: str
    complete: bool
    missing: tuple[str, ...]


def check_role(actor: Actor) -> None:
    raise NotImplementedError


def tenant_scope(scope: ScopeId | None) -> ScopeId:
    raise NotImplementedError


def district_for(text: object) -> str:
    raise NotImplementedError


def new_open_case(
    case_id: str, reference: str, referrer_type: ReferrerType, opened_at: datetime
) -> Case:
    raise NotImplementedError


def missing_fields(case: Case) -> tuple[str, ...]:
    raise NotImplementedError


def apply_update(case: Case, command: UpdateCaseCommand) -> Case:
    raise NotImplementedError


def snapshot_of(case: Case) -> dict[str, Any]:
    raise NotImplementedError


async def free_reference(rng: random.Random, is_held: Callable[[str], Awaitable[bool]]) -> str:
    raise NotImplementedError


def replay_key(use_case: str, scope: ScopeId, key: str) -> str:
    raise NotImplementedError


def open_fingerprint(command: OpenCaseCommand) -> str:
    raise NotImplementedError


def update_fingerprint(command: UpdateCaseCommand) -> str:
    raise NotImplementedError


class OpenCase:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
        rng: random.Random,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency
        self._rng = rng

    async def execute(self, command: OpenCaseCommand) -> OpenCaseResult:
        raise NotImplementedError


class UpdateCase:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        idempotency: IdempotencyStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._idempotency = idempotency

    async def execute(self, command: UpdateCaseCommand) -> UpdateCaseResult:
        raise NotImplementedError
