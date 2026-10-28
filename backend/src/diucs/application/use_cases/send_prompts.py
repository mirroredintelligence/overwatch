"""SendPrompts: send the capacity question for one service that is due (U03, DEC-115, DEC-116).

When a prompt is due, each textable reporter gets a text with a one-time link. The communication
records (with the link replaced), the link tokens (hash only), the ladder, the next prompt, the
audit entry and the outbox messages are written in one unit of work. The outbox holds the content
sealed with AES-256-GCM, its associated data being the outbox message id, the tenant and the
recipient role, so no token text is ever stored and sealed content cannot be moved (DEC-116).
Rules: domain-rules 1.4 (schedule), 1.5 (ladder), 2.1 and 9 (C1, C2), 7 (link tokens).
"""

import hashlib
import json
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
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.work import WorkKind
from diucs.domain.errors import Conflict, DomainError, NotFound, ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import RenderedMessage, render
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED
from diucs.domain.model.people import PractitionerRole, role_holder
from diucs.domain.model.service import ServiceProfile
from diucs.domain.rules.london_time import to_london
from diucs.domain.rules.opening_hours import is_in_hours
from diucs.domain.rules.schedule import LadderStep, ladder_times, next_due, reply_by

MESSAGES_TOPIC: Final = "messages.outbound"
SEND_MESSAGE: Final = "SendMessage"
USE_CASE: Final = "SendPrompts"
AUDIT_ACTION: Final = "C"
LINK_PURPOSE: Final = "capacity-reply"
"""The purpose of the link token: reply to this prompt, from this phone."""

LINK_PLACEHOLDER: Final = "[link]"
"""What the communication record holds in place of the link (the token is never stored)."""

ONE_SECOND: Final = timedelta(seconds=1)
NO_SKIP: Final = "none"

SKIP_INACTIVE: Final = "the service is not active"
SKIP_SUSPENDED: Final = "the service is suspended"
SKIP_OUT_OF_HOURS: Final = "the service is out of hours at the due time"
SKIP_REPLY_WINDOW: Final = "the reply window for this prompt has already closed"
SKIP_NO_WINDOW: Final = "the unit label has no readable window, so the first prompt is not sent"
SKIP_NO_REPORTER: Final = "no reporter can be texted for this service"

_LADDER: Final = (
    (LadderStep.REMINDER, WorkKind.REMINDER),
    (LadderStep.PHONE_TASK, WorkKind.PHONE_TASK),
    (LadderStep.ESCALATE, WorkKind.ESCALATE_TO_LEAD),
)

_MONTHS: Final = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
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
    that made it (DEC-104). A skip is stored too, because it writes the next prompt."""

    fingerprint: str
    result: SendPromptResult


def _fingerprint(command: SendPromptCommand) -> str:
    """The command body and the actor who sent it, as DEC-104 requires (DEC-115 item 14)."""
    body = repr(
        (
            command.service_id,
            command.due_at.astimezone(UTC).isoformat(),
            command.actor.role.value,
            command.actor.practitioner_id,
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _replay(stored: _StoredPrompt, fingerprint: str) -> SendPromptResult:
    if stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different prompt")
    return replace(stored.result, replayed=True)


def split_unit_label(label: str) -> tuple[str, str]:
    """C2 takes the unit and the window apart (lesson L46). The unit is the words before the first
    " in ", the window the rest, which starts with "in". When either part is empty the label is not
    readable: the result is the whole label and an empty window, and nothing is worded from it
    (DEC-115 item 13)."""
    unit, separator, window = label.partition(" in ")
    if not separator or not unit.strip() or not window.strip():
        return label, ""
    return unit, f"in {window}"


def _stamp(instant: datetime) -> str:
    """The full date and time of a figure in London, for C1 (DEC-115 item 11): "23 Oct 08:15"."""
    local = to_london(instant)
    return f"{local.day} {_MONTHS[local.month - 1]} {local.strftime('%H:%M')}"


def _hhmm(instant: datetime) -> str:
    return to_london(instant).strftime("%H:%M")


def _render(
    profile: ServiceProfile,
    latest: CapacityReport | None,
    window: tuple[str, str],
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
            as_of=_stamp(latest.effective_at),
            link=link,
            reply_by=_hhmm(reply),
        )
    unit, window_text = window
    return MessageId.C2, render(
        MessageId.C2,
        profile.channel,
        service=profile.name,
        unit=unit,
        window=window_text,
        reply_by=_hhmm(reply),
        link=link,
    )


def _skip_reason(
    profile: ServiceProfile,
    suspended: bool,
    due: datetime,
    now: datetime,
    has_report: bool,
    window: tuple[str, str],
) -> str | None:
    if not profile.active:
        return SKIP_INACTIVE
    if suspended:
        return SKIP_SUSPENDED
    if not is_in_hours(profile.available_times, due):
        return SKIP_OUT_OF_HOURS
    if now >= reply_by(due):
        return SKIP_REPLY_WINDOW
    if not has_report and not window[1]:
        return SKIP_NO_WINDOW
    return None


def _send_payload(
    outbox_id: str,
    communication_id: str,
    message_id: MessageId,
    role: PractitionerRole,
    rendered: RenderedMessage,
    sealer: ContentSealer,
    tenant_id: str,
) -> dict[str, object]:
    content = json.dumps(
        {"text": rendered.text, "subject": rendered.subject, "html": rendered.html},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return {
        "communication_id": communication_id,
        "message_id": message_id.value,
        "channel": rendered.channel.value,
        "recipient_role_id": role.id,
        "sealed_content": sealer.seal(
            content,
            message_id=outbox_id,
            tenant_id=tenant_id,
            recipient_role_id=role.id,
        ),
    }


class SendPrompts:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
        link_tokens: LinkTokenServiceFactory,
        link_base_url: str,
        sealer: ContentSealer,
        tenant_id: str,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency
        self._link_tokens = link_tokens
        self._link_base_url = link_base_url.rstrip("/")
        self._sealer = sealer
        self._tenant_id = tenant_id

    async def execute(self, command: SendPromptCommand) -> SendPromptResult:
        if command.due_at.tzinfo is None or command.due_at.utcoffset() is None:
            raise ValidationFailed("due_at", "must be a timezone-aware datetime")
        due = command.due_at.astimezone(UTC)
        fingerprint = _fingerprint(command)
        # An early read outside the unit of work (as U01). The authoritative check is inside it.
        early = await self._idempotency.get(command.idempotency_key)
        if isinstance(early, _StoredPrompt):
            return _replay(early, fingerprint)
        now = self._clock.now().astimezone(UTC)

        async with self._uow_factory() as uow:
            stored = await uow.idempotency.get(command.idempotency_key)
            if isinstance(stored, _StoredPrompt):
                return _replay(stored, fingerprint)
            profile = await uow.services.get(command.service_id)
            if profile is None:
                raise NotFound("no service with this id")
            flags = await uow.flags.service_flags(profile.id)
            suspended = any(flag.code == SERVICE_FLAG_SUSPENDED for flag in flags)
            result = await self._decide(uow, command, profile, due, now, suspended)
            await uow.idempotency.put(command.idempotency_key, _StoredPrompt(fingerprint, result))
            await uow.commit()
        return result

    async def _decide(
        self,
        uow: UnitOfWork,
        command: SendPromptCommand,
        profile: ServiceProfile,
        due: datetime,
        now: datetime,
        suspended: bool,
    ) -> SendPromptResult:
        latest = await uow.capacity.latest(profile.id)
        window = split_unit_label(profile.unit_label)
        reason = _skip_reason(profile, suspended, due, now, latest is not None, window)
        if reason is not None:
            # A skip sends nothing, but the chain goes on (DEC-115 item 12).
            await self._rearm(uow, profile, due, now)
            await self._audit(uow, command, profile.id, due, now, (), reason)
            return SendPromptResult(False, (), reason)

        communication_ids = await self._send_to_reporters(uow, profile, latest, window, due, now)
        if communication_ids:
            for communication_id in communication_ids:
                await self._ladder(uow, communication_id, due, now)
            reason = None
        else:
            # Nobody can be texted: the chase is about the service (DEC-115 item 15).
            await self._ladder(uow, profile.id, due, now)
            reason = SKIP_NO_REPORTER
        await self._rearm(uow, profile, due, now)
        await self._audit(uow, command, profile.id, due, now, tuple(communication_ids), reason)
        return SendPromptResult(
            sent=bool(communication_ids),
            communication_ids=tuple(communication_ids),
            skipped_reason=reason,
        )

    async def _send_to_reporters(
        self,
        uow: UnitOfWork,
        profile: ServiceProfile,
        latest: CapacityReport | None,
        window: tuple[str, str],
        due: datetime,
        now: datetime,
    ) -> list[str]:
        reply = reply_by(due)
        tokens = self._link_tokens(uow.link_tokens)
        communication_ids: list[str] = []
        for role in await uow.people.reporter_roles_for_service(profile.id, now):
            phone_hash = await _phone_hash(uow, role, now)
            if phone_hash is None:
                continue
            communication_id = self._ids.new_id()
            outbox_id = self._ids.new_id()
            token = await tokens.issue(LINK_PURPOSE, communication_id, phone_hash, reply)
            link = f"{self._link_base_url}/{token}"
            message_id, rendered = _render(profile, latest, window, link, reply)
            await uow.communications.add(
                Communication(
                    id=communication_id,
                    message_id=message_id.value,
                    channel=profile.channel,
                    recipient_role_id=role.id,
                    about_id=profile.id,
                    payload_text=rendered.text.replace(link, LINK_PLACEHOLDER),
                    sent_at=now,
                    delivery_status="queued",
                )
            )
            await uow.outbox.add(
                OutboxMessage(
                    id=outbox_id,
                    topic=MESSAGES_TOPIC,
                    event_type=SEND_MESSAGE,
                    payload=_send_payload(
                        outbox_id,
                        communication_id,
                        message_id,
                        role,
                        rendered,
                        self._sealer,
                        self._tenant_id,
                    ),
                    created_at=now,
                )
            )
            communication_ids.append(communication_id)
        return communication_ids

    async def _ladder(self, uow: UnitOfWork, about_id: str, due: datetime, now: datetime) -> None:
        times = ladder_times(due)
        for step, kind in _LADDER:
            await schedule_work(
                uow, self._ids, kind=kind, about_id=about_id, due_at=times[step], now=now
            )

    async def _rearm(
        self, uow: UnitOfWork, profile: ServiceProfile, due: datetime, now: datetime
    ) -> None:
        following = next_due(profile, due + ONE_SECOND)
        if following is None:
            # A valid profile always has one (every window yields due times). Refuse rather than
            # send this prompt and drop the chain (DEC-115 item 29).
            raise DomainError("a profile with available times always has a next due instant")
        await schedule_work(
            uow,
            self._ids,
            kind=WorkKind.PROMPT_DUE,
            about_id=profile.id,
            due_at=following,
            now=now,
        )

    async def _audit(
        self,
        uow: UnitOfWork,
        command: SendPromptCommand,
        service_id: str,
        due: datetime,
        now: datetime,
        communication_ids: tuple[str, ...],
        skipped_reason: str | None,
    ) -> None:
        await uow.audit.append(
            AuditEntry(
                action=AUDIT_ACTION,
                use_case=USE_CASE,
                actor=command.actor,
                entity_ids=(*communication_ids, service_id),
                snapshot={
                    "due_at": due.isoformat(),
                    "prompts": len(communication_ids),
                    "skipped_reason": NO_SKIP if skipped_reason is None else skipped_reason,
                },
                at=now,
            )
        )


async def _phone_hash(uow: UnitOfWork, role: PractitionerRole, now: datetime) -> str | None:
    """The phone hash of whoever holds the role now (cover honoured). A holder who is missing,
    inactive or has no phone cannot be texted: that role is left out."""
    holder = await uow.people.get_practitioner(role_holder(role, now))
    if holder is None or not holder.active:
        return None
    return holder.phone_hash
