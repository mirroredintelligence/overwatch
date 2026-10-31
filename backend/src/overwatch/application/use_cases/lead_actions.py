"""What the shift lead can do from the overview and the set-up tracker (W7B C, DEC-807 to DEC-809):
send the reminder now, send a service's reporter a test message, and switch a reporter to text.
(Sending an invitation again is `ResendInvitation`, U24.)

- `RemindService`: runs the reminder step of the missed-report ladder that is waiting for the
  service, now (C8 with a fresh link, and the status moves to not updated, as the step does by
  itself). Only a reminder that is scheduled and not yet sent can be run: with none, the answer is
  a conflict, so the lead is not told a reminder went when it did not.
- `SendLeadTestPrompt`: the test message (T1) to the service's reporter post, by the post's channel
  or by the one the lead names. It carries no link and asks for nothing, so it can never be
  answered with a number (a report). One a minute for a service, so a double press, and a flood, are
  refused. It goes to the post's own number: a cover's number is not used (known issue).
- `SwitchReporterToText`: the invited person's post is set to text, when a mobile number is held for
  it. The channel is the post's, so the next prompt goes by text.

Each is for the shift lead, keyed, replayed and audited; no number, link or token is in an audit
entry or a reply.
"""

import hashlib
from dataclasses import dataclass, replace
from typing import Final, Protocol

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.sealed_send import queue_message
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from diucs.application.use_cases.lead_views import check_lead, ending
from diucs.application.use_cases.missed_report_ladder import (
    REMINDED,
    LadderStepCommand,
    LadderStepResult,
)
from diucs.application.work import SCHEDULED, WorkKind
from diucs.domain.codes import Channel
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.people import cover_in_force, phone_contact_key

AUDIT_ACTION: Final = "U"
USE_CASE_TEST: Final = "SendLeadTestPrompt"
USE_CASE_SWITCH: Final = "SwitchReporterToText"
TEST_CONSUMER: Final = "lead-test-prompt"
ONE_MINUTE: Final = 60
NO_REMINDER: Final = "no reminder is waiting for this service"


class _LadderStep(Protocol):
    async def execute(self, command: LadderStepCommand) -> LadderStepResult: ...


@dataclass(frozen=True, slots=True)
class _Stored:
    fingerprint: str
    result: object


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()


def _replayed(stored: object, fingerprint: str) -> object | None:
    if stored is None:
        return None
    if not isinstance(stored, _Stored) or stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different command")
    return stored.result


def _scope_of(uow: UnitOfWork) -> ScopeId:
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


def _lead_with_name(actor: Actor) -> str:
    check_lead(actor)
    if actor.practitioner_id is None:
        raise NotAllowed("the lead must act as a named practitioner")
    return actor.practitioner_id


# ----------------------------------------------------------------------------------- reminder


class RemindService:
    def __init__(self, uow_factory: UnitOfWorkFactory, ladder: _LadderStep) -> None:
        self._uow_factory = uow_factory
        self._ladder = ladder

    async def execute(self, actor: Actor, service_id: str, idempotency_key: str) -> None:
        _lead_with_name(actor)
        async with self._uow_factory() as uow:
            if await uow.services.get(service_id) is None:
                raise NotFound("no service with this id")
            waiting = [
                work
                for work in await uow.scheduled_work.for_about(service_id, WorkKind.REMINDER)
                if work.status == SCHEDULED
            ]
        if not waiting:
            raise Conflict(NO_REMINDER)
        work = min(waiting, key=lambda item: (item.due_at, item.id))
        result = await self._ladder.execute(
            LadderStepCommand(
                idempotency_key=f"remind:{idempotency_key}", actor=actor, work_id=work.id
            )
        )
        if result.action != REMINDED:
            raise Conflict(NO_REMINDER)


# --------------------------------------------------------------------------------- test prompt


@dataclass(frozen=True, slots=True)
class PromptSent:
    channel: Channel
    number_ending: str | None


class SendLeadTestPrompt:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, ids: IdGenerator, clock: Clock, sealer: ContentSealer
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock
        self._sealer = sealer

    async def execute(
        self, actor: Actor, service_id: str, channel: Channel | None, idempotency_key: str
    ) -> PromptSent:
        _lead_with_name(actor)
        fingerprint = _fingerprint("test-prompt", service_id, channel)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _scope_of(uow)
            key = f"lead-test-prompt:{scope}:{idempotency_key}"
            replay = _replayed(await uow.idempotency.get(key), fingerprint)
            if isinstance(replay, PromptSent):
                return replay
            profile = await uow.services.get(service_id)
            if profile is None:
                raise NotFound("no service with this id")
            roles = await uow.people.reporter_roles_for_service(service_id, now)
            if not roles:
                raise Conflict("this service has no reporter to send to")
            role = min(roles, key=lambda item: item.id)
            chosen = channel or role.channel or Channel.TEXT
            # The message goes to whoever holds the post now (F6B): the cover's number while a
            # cover runs, and a cover has no email address, so the original's is not used.
            phone = await uow.contacts.get_phone(phone_contact_key(role, now))
            if chosen is Channel.TEXT and not phone:
                raise ValidationFailed("contact", "no mobile number is held for this channel")
            if chosen is Channel.EMAIL and (
                cover_in_force(role, now) or not await uow.contacts.get_email(role.id)
            ):
                raise ValidationFailed("contact", "no email address is held for this channel")
            bucket = f"lead-test:{service_id}:{int(now.timestamp()) // ONE_MINUTE}"
            if not await uow.processed.mark_if_new(bucket, TEST_CONSUMER):
                raise Conflict("a test message was sent to this service a moment ago")
            await queue_message(
                uow,
                self._ids,
                self._sealer,
                scope=scope,
                rendered=render(MessageId.T1, chosen, service=profile.name),
                recipient_role_id=role.id,
                about_id=service_id,
                now=now,
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE_TEST,
                    actor=actor,
                    entity_ids=(service_id, role.id),
                    snapshot={"channel": chosen.value},
                    at=now,
                )
            )
            result = PromptSent(chosen, ending(phone, 4))
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


# --------------------------------------------------------------------------------- switch to text


class SwitchReporterToText:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor, invitation_id: str, idempotency_key: str) -> Channel:
        _lead_with_name(actor)
        fingerprint = _fingerprint("switch", invitation_id)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _scope_of(uow)
            key = f"lead-switch-text:{scope}:{idempotency_key}"
            replay = _replayed(await uow.idempotency.get(key), fingerprint)
            if isinstance(replay, Channel):
                return replay
            invitation = await uow.registrations.get_invitation(invitation_id)
            if invitation is None:
                raise NotFound("no invitation with this id")
            registration = await uow.registrations.get(invitation.registration_id)
            role_id = None if registration is None else registration.requester_role_id
            role = None if role_id is None else await uow.people.get_role(role_id)
            if registration is None or role is None:
                raise NotFound("the reporter of this invitation")
            if not await uow.contacts.get_phone(role.id):
                raise Conflict("no mobile number is held for this reporter")
            if role.channel is not Channel.TEXT:
                await uow.people.save_role(replace(role, channel=Channel.TEXT))
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE_SWITCH,
                    actor=actor,
                    entity_ids=(invitation.id, role.id, invitation.service_id),
                    snapshot={"channel": Channel.TEXT.value},
                    at=now,
                )
            )
            await uow.idempotency.put(key, _Stored(fingerprint, Channel.TEXT))
            await uow.commit()
        return Channel.TEXT
