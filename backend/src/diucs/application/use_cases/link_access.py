"""Link access (L01): a stub for the red commit (DEC-010). The real module follows."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Protocol

from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.send_prompts import LINK_PURPOSE, LinkTokenServiceFactory
from diucs.domain.errors import DomainError
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile
from diucs.domain.rules.reply_policy import Decision, PromptState
from diucs.domain.rules.tokens import LinkTokenRecord

LINK_CSRF_SECRET: Final = "link-csrf"
CAPACITY_PURPOSE: Final = LINK_PURPOSE
LINK_PROMPT_MESSAGES: Final = frozenset({"C1", "C2", "C8"})
ACTIONS: Final = frozenset({"confirm", "number", "closed"})
CLOSED_VALUE: Final = 0
MAX_VALUE: Final = 999
STATE_OK: Final = "ok"
STATE_EXPIRED: Final = "expired"
STATE_USED: Final = "used"
MAX_TOKEN_LENGTH: Final = 64
REQUEST_WINDOW: Final = timedelta(0)
REQUESTS_PER_WINDOW: Final = 0
BAD_ATTEMPT_WINDOW: Final = timedelta(0)
BAD_ATTEMPTS_PER_ADDRESS: Final = 0
RENEW_WINDOW: Final = timedelta(0)
RENEWALS_PER_WINDOW: Final = 0

type Body = Mapping[str, object]


class LinkGone(DomainError):
    def __init__(self, state: str) -> None:
        super().__init__(state)
        self.state = state


class CsrfRejected(DomainError):
    pass


class LinkOutOfRange(DomainError):
    def __init__(self, usual_min: int, usual_max: int) -> None:
        super().__init__("out-of-range")
        self.usual_min = usual_min
        self.usual_max = usual_max


class SendTheNumber(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class LinkRateLimited(DomainError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate-limited")
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class LinkAction:
    action: str
    value: int | None = None
    confirm_out_of_range: bool = False


@dataclass(frozen=True, slots=True)
class ViewLinkQuery:
    token: str
    client: str


@dataclass(frozen=True, slots=True)
class RespondViaLinkCommand:
    token: str
    csrf_token: str | None
    action: LinkAction
    client: str


@dataclass(frozen=True, slots=True)
class RenewLinkCommand:
    token: str
    client: str
    link_base_url: str


@dataclass(frozen=True, slots=True)
class LinkView:
    purpose: str
    body: Body


@dataclass(frozen=True, slots=True)
class LinkResponse:
    body: Body


@dataclass(frozen=True, slots=True)
class LinkRequest:
    record: LinkTokenRecord
    token: str
    scope: ScopeId
    now: datetime


class LinkPurposeHandler(Protocol):
    async def view(self, link: LinkRequest) -> Body: ...

    async def respond(self, link: LinkRequest, action: LinkAction) -> Body: ...

    async def renew(self, link: LinkRequest, link_base_url: str) -> bool: ...


type LinkPurposes = Mapping[str, LinkPurposeHandler]


def csrf_token(token_hash: str, secret: bytes) -> str:
    return ""


def iso_utc(moment: datetime | None) -> str | None:
    return None


def command_key(scope: ScopeId, record: LinkTokenRecord) -> str:
    return ""


def check_action(action: LinkAction) -> None:
    return None


def figure_of(action: LinkAction) -> int:
    return -1


def prompt_state(
    link: LinkRequest,
    profile: ServiceProfile,
    latest: CapacityReport | None,
    trailing: int,
    action: LinkAction,
) -> PromptState:
    return PromptState(
        service_id="",
        reply_by=None,
        recorded_value=None,
        consecutive_confirms=0,
        last_accepted_at=None,
        last_accepted_value=None,
        pending_out_of_range=None,
        usual_range=(0, 0),
    )


def judge(
    decision: Decision,
    profile: ServiceProfile,
    latest: CapacityReport | None,
    prompt_sent_at: datetime,
    number_since_prompt: bool,
) -> Any:
    return None


async def number_after_prompt(
    uow: UnitOfWork, service_id: str, latest: CapacityReport, prompt_sent_at: datetime
) -> bool:
    return False


class _Stub:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        secrets: SecretStore,
        cache: Cache,
        link_tokens: LinkTokenServiceFactory,
        purposes: LinkPurposes,
    ) -> None:
        self._purposes = purposes


class ViewLink(_Stub):
    async def execute(self, query: ViewLinkQuery) -> LinkView:
        return LinkView(purpose="", body={})


class RespondViaLink(_Stub):
    async def execute(self, command: RespondViaLinkCommand) -> LinkResponse:
        return LinkResponse(body={})


class RenewLink(_Stub):
    async def execute(self, command: RenewLinkCommand) -> None:
        return None


class CapacityLinkHandler:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        link_tokens: LinkTokenServiceFactory,
        sealer: ContentSealer,
        reports: Any,
        confirms: Any,
    ) -> None:
        self._uow_factory = uow_factory

    async def view(self, link: LinkRequest) -> Body:
        return {}

    async def respond(self, link: LinkRequest, action: LinkAction) -> Body:
        return {}

    async def renew(self, link: LinkRequest, link_base_url: str) -> bool:
        return False


class UnitOfWorkIdempotency:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get(self, key: str) -> object | None:
        return None

    async def put(self, key: str, result: object) -> None:
        return None
