"""STUB (U24 red): declarations only."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import PhoneHasher
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.send_prompts import LinkTokenServiceFactory
from diucs.domain.codes import Channel, ScopeFlag
from diucs.domain.model.people import PractitionerRole

LinkBaseUrlFor = Callable[[ScopeId], str]
INVITE_LINK_PATH: Final = "/i/"
MOBILE_MESSAGE: Final = "Enter a UK mobile number, like 07700 900123"
NOT_IN_PILOT_MESSAGE: Final = "Only services in the pilot can be invited"


@dataclass(frozen=True, slots=True)
class InviteReporterCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    role_label: str
    mobile: str
    suggested_channel: Channel


@dataclass(frozen=True, slots=True)
class InviteReporterResult:
    invitation_id: str
    registration_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ResendInvitationCommand:
    idempotency_key: str
    actor: Actor
    invitation_id: str


def check_invite_mobile(text: str) -> str:
    raise NotImplementedError


def check_may_invite(actor: Actor) -> str:
    raise NotImplementedError


def check_in_pilot(flag: ScopeFlag) -> None:
    raise NotImplementedError


def invitation_expiry(sent_at: datetime) -> datetime:
    raise NotImplementedError


def invitation_link(base_url: str, token: str) -> str:
    raise NotImplementedError


def redacted_invitation_link(base_url: str) -> str:
    raise NotImplementedError


def lead_post(roles: list[PractitionerRole]) -> PractitionerRole | None:
    raise NotImplementedError


def command_key(operation: str, scope: ScopeId, key: str) -> str:
    raise NotImplementedError


class InviteReporter:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        link_tokens: LinkTokenServiceFactory,
        phone_hasher: PhoneHasher,
        clock: Clock,
        ids: IdGenerator,
        *,
        link_base_url_for: LinkBaseUrlFor,
    ) -> None:
        raise NotImplementedError

    async def execute(self, command: InviteReporterCommand) -> InviteReporterResult:
        raise NotImplementedError


class ResendInvitation:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        link_tokens: LinkTokenServiceFactory,
        clock: Clock,
        ids: IdGenerator,
        *,
        link_base_url_for: LinkBaseUrlFor,
    ) -> None:
        raise NotImplementedError

    async def execute(self, command: ResendInvitationCommand) -> InviteReporterResult:
        raise NotImplementedError
