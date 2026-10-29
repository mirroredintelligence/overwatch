"""STUB (U28 red): declarations only."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import PhoneHasher
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.registration_submit import Lookups
from diucs.domain.codes import RegistrationStatus, ScopeFlag
from diucs.domain.model.registration import Answer, CallBackResult, Registration

AreaDistrictsFor = Callable[[ScopeId], frozenset[str]]
CHECK_ODS: Final = "ods-code"
CHECK_NAME: Final = "organisation-name"
CHECK_ADDRESS: Final = "address-area"
CHECK_PHONE: Final = "reporting-phone"
CHECK_EMAIL: Final = "owner-email"
NOTES_STEP: Final = "check_notes"
FREE_MAIL_DOMAINS: Final = frozenset[str]()
NHS_MAIL_DOMAIN: Final = "nhs.net"
NHS_ORGANISATION_TYPES: Final = frozenset[str]()


@dataclass(frozen=True, slots=True)
class AutomaticCheck:
    name: str
    passed: bool
    message: str
    explained_note: str | None = None

    @property
    def ok(self) -> bool:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ScopeAnswers:
    on_dorset_pathway: Answer
    takes_spoa_referrals: Answer
    can_report: Answer
    category_on_pilot_list: Answer


@dataclass(frozen=True, slots=True)
class ReviewStatus:
    registration_id: str
    status: RegistrationStatus
    checks: tuple[AutomaticCheck, ...]
    automatic_ok: bool
    callback_confirmed: bool
    scope: ScopeFlag | None
    criteria_approved: bool
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StartReviewCommand:
    idempotency_key: str
    actor: Actor
    registration_id: str


@dataclass(frozen=True, slots=True)
class StartReviewResult:
    registration_id: str
    status: RegistrationStatus
    reviewer_role_id: str


@dataclass(frozen=True, slots=True)
class ExplainCheckCommand:
    idempotency_key: str
    actor: Actor
    registration_id: str
    check_name: str
    note: str


@dataclass(frozen=True, slots=True)
class ExplainCheckResult:
    registration_id: str
    check_name: str
    automatic_ok: bool


@dataclass(frozen=True, slots=True)
class RecordCallBackCommand:
    idempotency_key: str
    actor: Actor
    registration_id: str
    number_called: str
    role_spoken_to: str
    result: CallBackResult


@dataclass(frozen=True, slots=True)
class RecordCallBackResult:
    registration_id: str
    result: CallBackResult
    callback_confirmed: bool
    provenance_id: str


@dataclass(frozen=True, slots=True)
class RecordScopeDecisionCommand:
    idempotency_key: str
    actor: Actor
    registration_id: str
    answers: ScopeAnswers
    decision: ScopeFlag
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RecordScopeDecisionResult:
    registration_id: str
    decision: ScopeFlag
    provenance_id: str


@dataclass(frozen=True, slots=True)
class GetReviewStatusQuery:
    actor: Actor
    registration_id: str


def check_may_review(actor: Actor) -> str:
    raise NotImplementedError


def name_key(text: str) -> str:
    raise NotImplementedError


def organisation_email_ok(owner_email: str, organisation_email: str) -> bool:
    raise NotImplementedError


def number_digits(number: str) -> str:
    raise NotImplementedError


def callback_number_hash(secret: bytes, number: str) -> str:
    raise NotImplementedError


def districts_in_ranges(*ranges: tuple[str, int, int]) -> frozenset[str]:
    return frozenset()


def run_automatic_checks(
    registration: Registration,
    *,
    lookups: Lookups | None,
    invited_phone_hash: str | None,
    reporting_phone_hash: str | None,
    area_districts: frozenset[str],
    notes: Mapping[str, str] | None = None,
) -> tuple[AutomaticCheck, ...]:
    raise NotImplementedError


def automatic_ok(checks: tuple[AutomaticCheck, ...]) -> bool:
    raise NotImplementedError


class StartReview:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        phone_hasher: PhoneHasher,
        clock: Clock,
        *,
        area_districts_for: AreaDistrictsFor,
    ) -> None:
        raise NotImplementedError

    async def execute(self, command: StartReviewCommand) -> StartReviewResult:
        raise NotImplementedError


class ExplainCheck:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        phone_hasher: PhoneHasher,
        clock: Clock,
        *,
        area_districts_for: AreaDistrictsFor,
    ) -> None:
        raise NotImplementedError

    async def execute(self, command: ExplainCheckCommand) -> ExplainCheckResult:
        raise NotImplementedError


class RecordCallBack:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        phone_hasher: PhoneHasher,
        secret_store: SecretStore,
        ids: IdGenerator,
        clock: Clock,
        *,
        area_districts_for: AreaDistrictsFor,
    ) -> None:
        raise NotImplementedError

    async def execute(self, command: RecordCallBackCommand) -> RecordCallBackResult:
        raise NotImplementedError


class RecordScopeDecision:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        phone_hasher: PhoneHasher,
        clock: Clock,
        *,
        area_districts_for: AreaDistrictsFor,
    ) -> None:
        raise NotImplementedError

    async def execute(self, command: RecordScopeDecisionCommand) -> RecordScopeDecisionResult:
        raise NotImplementedError


class GetReviewStatus:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        phone_hasher: PhoneHasher,
        clock: Clock,
        *,
        area_districts_for: AreaDistrictsFor,
    ) -> None:
        raise NotImplementedError

    async def execute(self, query: GetReviewStatusQuery) -> ReviewStatus:
        raise NotImplementedError
