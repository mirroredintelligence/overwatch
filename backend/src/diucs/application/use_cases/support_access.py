"""Consent-based support access (O06).

A person shares their session by making a support code (CreateSupportCode). Support opens that
session
with the code, or with a ticket and a lead's approval (OpenSessionForSupport). Every open is one
SupportAccess and one audit entry, written in one unit of work, and the person sees each open with
its
role and time, never a name (ListMyAccesses). The person can stop sharing at once (StopSharing).

Tenancy (DEC-130, DEC-132): the use cases read the tenant from the unit of work only. A code is
found,
stopped and listed in the tenant of the unit of work, so another tenant's code reads as not found.
The
edge that opens the unit of work is what chooses the tenant for a code; that resolution is not here
(it needs a decision on a global lookup, see the fragment). The support role is refused before any
unit
of work opens (the guard), and a refused open never says which of the code, the ticket or the
approval
was wrong.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.support import SupportAccessRecord, SupportCodeRecord
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed
from diucs.domain.rules.support import (
    SUPPORT_CODE_SECRET,
    access_window,
    code_window,
    hash_support_code,
    is_lead,
    may_open_support,
    normalise_support_code,
    support_code_usable,
)
from diucs.domain.rules.tokens import new_support_code

USE_CASE_OPEN: Final = "OpenSessionForSupport"
USE_CASE_CREATE: Final = "CreateSupportCode"
USE_CASE_STOP: Final = "StopSharing"
ACTION_CODE_CREATED: Final = "support-code-created"
ACTION_SHARING_STOPPED: Final = "support-sharing-stopped"
ACTION_SESSION_OPENED: Final = "support-session-opened"

SHARE_REFUSED: Final = "Your session cannot be shared right now."
OPEN_REFUSED: Final = "This session cannot be opened with that code or ticket."
ROLE_REFUSED: Final = "Only support can open a session."
LIST_REFUSED: Final = "These sessions are not yours."
_TICKET: Final = re.compile(r"[A-Za-z0-9-]{1,32}")


@dataclass(frozen=True, slots=True)
class CreateSupportCodeCommand:
    actor: Actor
    session_id: str
    device_type: str
    app_mode: str
    release: str


@dataclass(frozen=True, slots=True)
class CreateSupportCodeResult:
    code: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class StopSharingCommand:
    actor: Actor
    session_id: str


@dataclass(frozen=True, slots=True)
class OpenSessionCommand:
    actor: Actor
    code: str | None = None
    session_id: str | None = None
    ticket: str | None = None
    approved_by: str | None = None


@dataclass(frozen=True, slots=True)
class OpenSessionResult:
    access_id: str
    session_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ListMyAccessesCommand:
    actor: Actor
    session_id: str


@dataclass(frozen=True, slots=True)
class AccessView:
    """One open as the person sees it: when, until when, and by which role. Never a name."""

    opened_at: datetime
    expires_at: datetime
    by: str


class CreateSupportCode:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        secrets: SecretStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._secrets = secrets

    async def execute(self, command: CreateSupportCodeCommand) -> CreateSupportCodeResult:
        """Make a code for the person's session. The code is returned once; only its hash is stored,
        with the session and the practitioner who shares it."""
        actor = command.actor
        if actor.practitioner_id is None or actor.role is Role.SUPPORT:
            raise NotAllowed(SHARE_REFUSED)
        code = new_support_code()
        now = self._clock.now()
        code_hash = hash_support_code(code, self._secrets.get(SUPPORT_CODE_SECRET))
        expires_at = code_window(now)
        async with self._uow_factory() as uow:
            await uow.support.ensure_session(
                command.session_id, command.device_type, command.app_mode, command.release, now
            )
            added = await uow.support.add_code(
                SupportCodeRecord(
                    code_hash=code_hash,
                    session_id=command.session_id,
                    practitioner_id=actor.practitioner_id,
                    created_at=now,
                    expires_at=expires_at,
                )
            )
            if not added:
                raise NotAllowed(SHARE_REFUSED)
            await uow.audit.append(
                AuditEntry(
                    action=ACTION_CODE_CREATED,
                    use_case=USE_CASE_CREATE,
                    actor=actor,
                    entity_ids=(command.session_id,),
                    snapshot={"expires_at": expires_at},
                    at=now,
                )
            )
            await uow.commit()
        return CreateSupportCodeResult(code=code, expires_at=expires_at)


class StopSharing:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: StopSharingCommand) -> int:
        """Expire the person's codes for the session at once, and end the opens in progress. Returns
        the number of codes stopped. With none to stop, nothing is written."""
        actor = command.actor
        if actor.practitioner_id is None:
            raise NotAllowed(SHARE_REFUSED)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            stopped = await uow.support.stop_codes(command.session_id, actor.practitioner_id, now)
            if stopped == 0:
                return 0
            ended = await uow.support.end_accesses(command.session_id, now)
            await uow.audit.append(
                AuditEntry(
                    action=ACTION_SHARING_STOPPED,
                    use_case=USE_CASE_STOP,
                    actor=actor,
                    entity_ids=(command.session_id,),
                    snapshot={"codes_stopped": stopped, "accesses_ended": ended},
                    at=now,
                )
            )
            await uow.commit()
        return stopped


class OpenSessionForSupport:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        secrets: SecretStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._secrets = secrets

    async def execute(self, command: OpenSessionCommand) -> OpenSessionResult:
        """Open a session for support: with a valid code, or with a ticket and a lead's approval.
        The
        role is checked first, before any unit of work opens. Every refusal of the code, the ticket
        or
        the approval is the same error, so an answer does not say which part was wrong."""
        actor = command.actor
        if not may_open_support(actor.role):
            raise NotAllowed(ROLE_REFUSED)
        if actor.practitioner_id is None:
            raise NotAllowed(OPEN_REFUSED)
        now = self._clock.now()
        secret = self._secrets.get(SUPPORT_CODE_SECRET)
        async with self._uow_factory() as uow:
            if command.code is not None:
                canonical = normalise_support_code(command.code)
                if canonical is None:
                    raise NotAllowed(OPEN_REFUSED)
                record = await uow.support.code_by_hash(hash_support_code(canonical, secret))
                if record is None or not support_code_usable(
                    record.expires_at, record.stopped_at, now
                ):
                    raise NotAllowed(OPEN_REFUSED)
                session_id, reason, path = record.session_id, "code", "code"
            else:
                if (
                    command.session_id is None
                    or command.ticket is None
                    or command.approved_by is None
                    or _TICKET.fullmatch(command.ticket) is None
                ):
                    raise NotAllowed(OPEN_REFUSED)
                approver = await uow.people.get_practitioner(command.approved_by)
                roles = (
                    await uow.people.roles_for_practitioner(command.approved_by)
                    if approver is not None
                    else []
                )
                if approver is None or not is_lead(roles, approver.active):
                    raise NotAllowed(OPEN_REFUSED)
                if not await uow.support.session_exists(command.session_id):
                    raise NotAllowed(OPEN_REFUSED)
                session_id = command.session_id
                reason = f"ticket {command.ticket}"
                path = "ticket"
            access = SupportAccessRecord(
                id=self._ids.new_id(),
                session_id=session_id,
                practitioner_id=actor.practitioner_id,
                reason=reason,
                opened_at=now,
                expires_at=access_window(now),
            )
            if not await uow.support.add_access(access):
                raise NotAllowed(OPEN_REFUSED)
            await uow.audit.append(
                AuditEntry(
                    action=ACTION_SESSION_OPENED,
                    use_case=USE_CASE_OPEN,
                    actor=actor,
                    entity_ids=(access.id, session_id),
                    snapshot={"path": path, "expires_at": access.expires_at},
                    at=now,
                )
            )
            await uow.commit()
        return OpenSessionResult(
            access_id=access.id, session_id=session_id, expires_at=access.expires_at
        )


class ListMyAccesses:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: ListMyAccessesCommand) -> list[AccessView]:
        """Each open of a session the person shared: the time it opened and ends, and the role that
        opened it. Only the person who shared the session may list it."""
        actor = command.actor
        if actor.practitioner_id is None:
            raise NotAllowed(LIST_REFUSED)
        async with self._uow_factory() as uow:
            if not await uow.support.session_shared_by(command.session_id, actor.practitioner_id):
                raise NotAllowed(LIST_REFUSED)
            accesses = await uow.support.accesses_of(command.session_id)
        return [
            AccessView(
                opened_at=access.opened_at, expires_at=access.expires_at, by=Role.SUPPORT.value
            )
            for access in accesses
        ]
