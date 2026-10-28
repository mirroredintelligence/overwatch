"""SendPrompts: send the capacity question for one service that is due (U03, DEC-115).

When a prompt is due the reporter gets a text with a one-time link. The communication records, the
link tokens, the missed-report ladder, the next prompt, the audit entry and the outbox messages are
all written in one unit of work. Rules: domain-rules 1.4 (schedule), 1.5 (ladder), 2.1 and 9 (the
messages C1 and C2), 7 (link tokens).
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Final

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.work import WorkKind
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import RenderedMessage, render
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED
from diucs.domain.model.people import PractitionerRole, role_holder
from diucs.domain.model.service import ServiceProfile
from diucs.domain.rules.london_time import format_hhmm
from diucs.domain.rules.opening_hours import is_in_hours
from diucs.domain.rules.schedule import LadderStep, ladder_times, next_due, reply_by

MESSAGES_TOPIC: Final = "messages.outbound"
SEND_MESSAGE: Final = "SendMessage"
USE_CASE: Final = "SendPrompts"
AUDIT_ACTION: Final = "C"
LINK_PURPOSE: Final = "capacity-reply"
"""The purpose of the link token: reply to this prompt, from this phone."""

ONE_SECOND: Final = timedelta(seconds=1)
NO_WINDOW_PHRASE: Final = "today"
"""C2 window when the service's unit label names none (DEC-115 item 4)."""

SKIP_INACTIVE: Final = "the service is not active"
SKIP_SUSPENDED: Final = "the service is suspended"
SKIP_OUT_OF_HOURS: Final = "the service is out of hours at the due time"
SKIP_REPLY_WINDOW: Final = "the reply window for this prompt has already closed"
SKIP_NO_REPORTER: Final = "no reporter can be texted for this service"

_LADDER: Final = (
    (LadderStep.REMINDER, WorkKind.REMINDER),
    (LadderStep.PHONE_TASK, WorkKind.PHONE_TASK),
    (LadderStep.ESCALATE, WorkKind.ESCALATE_TO_LEAD),
)

LinkTokenServiceFactory = Callable[[LinkTokenRepository], LinkTokenService]
"""Builds the link-token service on a unit of work's own token repository, so the token is stored
in the same transaction as the prompt (DEC-115 item 1)."""


@dataclass(frozen=True, slots=True)
class SendPromptCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    due_at: datetime


@dataclass(frozen=True, slots=True)
class SendPromptResult:
    sent: bool
    communication_ids: tuple[str, ...]
    skipped_reason: str | None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class _StoredPrompt:
    """What the idempotency store keeps for a key: the result and the fingerprint of the command
    that made it. A replay must match (the DEC-104 pattern)."""

    fingerprint: str
    result: SendPromptResult


def _fingerprint(command: SendPromptCommand) -> str:
    body = repr((command.service_id, command.due_at.astimezone(UTC).isoformat()))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _replay(stored: _StoredPrompt, fingerprint: str) -> SendPromptResult:
    if stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different prompt")
    return replace(stored.result, replayed=True)


def split_unit_label(label: str) -> tuple[str, str]:
    """C2 takes the unit and the window apart (lesson L46). The unit label is the whole phrase
    ("referrals in the next 2 hrs"): the unit is the words before the first " in ", the window
    the rest. A label with no window gives the unit and NO_WINDOW_PHRASE."""
    unit, separator, window = label.partition(" in ")
    if not separator:
        return label, NO_WINDOW_PHRASE
    return unit, f"in {window}"


def _render(
    profile: ServiceProfile,
    latest: CapacityReport | None,
    link: str,
    reply: datetime,
) -> tuple[MessageId, RenderedMessage]:
    if latest is not None:
        return MessageId.C1, render(
            MessageId.C1,
            profile.channel,
            service=profile.name,
            value=latest.value,
            unit=profile.unit_label,
            as_of=format_hhmm(latest.effective_at),
            link=link,
            reply_by=format_hhmm(reply),
        )
    unit, window = split_unit_label(profile.unit_label)
    return MessageId.C2, render(
        MessageId.C2,
        profile.channel,
        service=profile.name,
        unit=unit,
        window=window,
        reply_by=format_hhmm(reply),
        link=link,
    )


def _skip_reason(profile: ServiceProfile | None, suspended: bool, due: datetime) -> str | None:
    if profile is None or not profile.active:
        return SKIP_INACTIVE
    if suspended:
        return SKIP_SUSPENDED
    if not is_in_hours(profile.available_times, due):
        return SKIP_OUT_OF_HOURS
    return None


class SendPrompts:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
        link_tokens: LinkTokenServiceFactory,
        link_base_url: str,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency
        self._link_tokens = link_tokens
        self._link_base_url = link_base_url.rstrip("/")

    async def execute(self, command: SendPromptCommand) -> SendPromptResult:
        if command.due_at.tzinfo is None or command.due_at.utcoffset() is None:
            raise ValidationFailed("due_at", "must be a timezone-aware datetime")
        due = command.due_at.astimezone(UTC)
        fingerprint = _fingerprint(command)
        now = self._clock.now().astimezone(UTC)

        async with self._uow_factory() as uow:
            # The authoritative replay check, before any write (DEC-106 item 2).
            stored = await uow.idempotency.get(command.idempotency_key)
            if isinstance(stored, _StoredPrompt):
                return _replay(stored, fingerprint)

            profile = await uow.services.get(command.service_id)
            if profile is None:
                raise NotFound("no service with this id")
            flags = await uow.flags.service_flags(profile.id)
            suspended = any(flag.code == SERVICE_FLAG_SUSPENDED for flag in flags)
            reason = _skip_reason(profile, suspended, due)
            if reason is None and now >= reply_by(due):
                reason = SKIP_REPLY_WINDOW
            if reason is not None:
                return SendPromptResult(False, (), reason)

            result = await self._send(uow, command, profile, due, now)
            await uow.idempotency.put(command.idempotency_key, _StoredPrompt(fingerprint, result))
            await uow.commit()
        return result

    async def _send(
        self,
        uow: UnitOfWork,
        command: SendPromptCommand,
        profile: ServiceProfile,
        due: datetime,
        now: datetime,
    ) -> SendPromptResult:
        reply = reply_by(due)
        latest = await uow.capacity.latest(profile.id)
        tokens = self._link_tokens(uow.link_tokens)
        communication_ids: list[str] = []

        roles = await uow.people.reporter_roles_for_service(profile.id, now)
        for role in roles:
            phone_hash = await self._phone_hash(uow, role, now)
            if phone_hash is None:
                continue
            communication_id = self._ids.new_id()
            token = await tokens.issue(LINK_PURPOSE, communication_id, phone_hash, reply)
            link = f"{self._link_base_url}/{token}"
            message_id, rendered = _render(profile, latest, link, reply)
            await uow.communications.add(
                Communication(
                    id=communication_id,
                    message_id=message_id.value,
                    channel=profile.channel,
                    recipient_role_id=role.id,
                    about_id=profile.id,
                    payload_text=rendered.text,
                    sent_at=now,
                    delivery_status="queued",
                )
            )
            await uow.outbox.add(
                OutboxMessage(
                    id=self._ids.new_id(),
                    topic=MESSAGES_TOPIC,
                    event_type=SEND_MESSAGE,
                    payload=_send_payload(communication_id, message_id, role, rendered),
                    created_at=now,
                )
            )
            times = ladder_times(due)
            for step, kind in _LADDER:
                await schedule_work(
                    uow,
                    self._ids,
                    kind=kind,
                    about_id=communication_id,
                    due_at=times[step],
                    now=now,
                )
            communication_ids.append(communication_id)

        following = next_due(profile, due + ONE_SECOND)
        if following is not None:
            await schedule_work(
                uow,
                self._ids,
                kind=WorkKind.PROMPT_DUE,
                about_id=profile.id,
                due_at=following,
                now=now,
            )

        sent = bool(communication_ids)
        if sent:
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE,
                    actor=command.actor,
                    entity_ids=(*communication_ids, profile.id),
                    snapshot={"due_at": due.isoformat(), "prompts": len(communication_ids)},
                    at=now,
                )
            )
        return SendPromptResult(
            sent=sent,
            communication_ids=tuple(communication_ids),
            skipped_reason=None if sent else SKIP_NO_REPORTER,
        )

    @staticmethod
    async def _phone_hash(uow: UnitOfWork, role: PractitionerRole, now: datetime) -> str | None:
        """The phone hash of whoever holds the role now (cover honoured). A holder who is missing,
        inactive or has no phone cannot be texted: that role is left out."""
        holder = await uow.people.get_practitioner(role_holder(role, now))
        if holder is None or not holder.active:
            return None
        return holder.phone_hash


def _send_payload(
    communication_id: str, message_id: MessageId, role: PractitionerRole, rendered: RenderedMessage
) -> dict[str, object]:
    payload: dict[str, object] = {
        "communication_id": communication_id,
        "message_id": message_id.value,
        "channel": rendered.channel.value,
        "recipient_role_id": role.id,
        "text": rendered.text,
    }
    if rendered.subject is not None:
        payload["subject"] = rendered.subject
    if rendered.html is not None:
        payload["html"] = rendered.html
    return payload
