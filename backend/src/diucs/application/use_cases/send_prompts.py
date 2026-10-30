"""SendPrompts: send the capacity question for one service that is due (U03, DEC-115, DEC-116).

When a prompt is due, each textable reporter gets a text with a one-time link. The communication
records (with the link replaced), the link tokens (hash only), the ladder, the next prompt, the
audit entry and the outbox messages are written in one unit of work. The outbox holds the content
sealed with AES-256-GCM, its associated data being the outbox message id, the tenant and the
recipient role, so no token text is ever stored and sealed content cannot be moved (DEC-116).
Rules: domain-rules 1.4 (schedule), 1.5 (ladder), 2.1 and 9 (C1, C2), 7 (link tokens).

A phone that reports for several services due within GROUP_WINDOW of each other gets one grouped
prompt (C9) instead of one text each (U04, DEC-156, domain-rules 2.4). One Communication is stored
for each grouped service (all C9, one send time, one text), and only letter A's is sent, so that
U05 can tell which service a letter means. Each grouped service keeps its own ladder and next
prompt, and the result of its own job is stored in the same unit of work, so that job does nothing
when it runs.
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
from diucs.application.ports.outbound.messaging import GROUPED_STATUS, Communication
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.work import WorkKind
from diucs.domain.codes import Channel
from diucs.domain.errors import Conflict, DomainError, NotFound, ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import RenderedMessage, render
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED
from diucs.domain.model.people import PractitionerRole, role_holder
from diucs.domain.model.service import ServiceProfile
from diucs.domain.rules.freshness import STALE_WARNING_AFTER
from diucs.domain.rules.london_time import format_hhmm, format_stamp
from diucs.domain.rules.multi_service import GROUP_WINDOW, GroupedItem, group_due
from diucs.domain.rules.opening_hours import is_in_hours
from diucs.domain.rules.schedule import LadderStep, current_due, ladder_times, next_due, reply_by

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
    """What a prompt did. `communication_ids` are the messages recorded for this service.
    `grouped_service_ids` is every service prompted in one C9 with it, itself included, in letter
    order, or empty when it was prompted on its own (DEC-156 item 9)."""

    sent: bool
    communication_ids: tuple[str, ...]
    skipped_reason: str | None
    replayed: bool = False
    grouped_service_ids: tuple[str, ...] = ()


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


def prompt_key(service_id: str, due: datetime) -> str:
    """The idempotency key of the prompt for this service at this due instant, in UTC. The job that
    runs a `prompt-due` builds its command key with this, so that a grouped prompt can store a
    result under the key of every service it covers (DEC-156 item 5)."""
    return f"prompt:{service_id}:{due.astimezone(UTC).isoformat()}"


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
            as_of=format_stamp(latest.effective_at),
            link=link,
            reply_by=format_hhmm(reply),
        )
    unit, window_text = window
    return MessageId.C2, render(
        MessageId.C2,
        profile.channel,
        service=profile.name,
        unit=unit,
        window=window_text,
        reply_by=format_hhmm(reply),
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


@dataclass(frozen=True, slots=True)
class _Prompted:
    """A service this command prompts: its profile, its latest figure and its due instant."""

    profile: ServiceProfile
    latest: CapacityReport | None
    due: datetime


@dataclass(frozen=True, slots=True)
class _Member:
    """A service in a grouped prompt: what it is, the role this phone holds for it, the figure shown
    and its letter."""

    prompted: _Prompted
    role: PractitionerRole
    figure: int
    item: GroupedItem


@dataclass(frozen=True, slots=True)
class _Group:
    """The one C9 a phone gets: its services in letter order and the rendered text."""

    phone_hash: str
    members: tuple[_Member, ...]
    rendered: RenderedMessage


def _too_old_to_confirm(latest: CapacityReport, now: datetime) -> bool:
    """True when a Y could not confirm this figure: it was more than STALE_WARNING_AFTER old when
    the prompt is sent, the line U05 draws (`figure_is_out_of_date`, DEC-148 item 2, DEC-156
    item 4). Exactly that age is still inside."""
    return now - latest.effective_at > STALE_WARNING_AFTER


def _grouped_ids(groups: list[_Group], service_id: str) -> tuple[str, ...]:
    """Every service prompted in a group with this one, itself included, in letter order. Empty
    when it is in no group."""
    ids: list[str] = []
    for group in groups:
        if any(m.prompted.profile.id == service_id for m in group.members):
            ids.extend(
                m.prompted.profile.id for m in group.members if m.prompted.profile.id not in ids
            )
    return tuple(ids)


async def _reporters(
    uow: UnitOfWork, service_id: str, now: datetime
) -> list[tuple[PractitionerRole, str]]:
    """Each reporter role of the service that can be texted, with its holder's phone hash."""
    found: list[tuple[PractitionerRole, str]] = []
    for role in await uow.people.reporter_roles_for_service(service_id, now):
        phone_hash = await _phone_hash(uow, role, now)
        if phone_hash is not None:
            found.append((role, phone_hash))
    return found


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
            await self._audit(uow, command, profile.id, due, now, (), (), reason)
            return SendPromptResult(False, (), reason)

        me = _Prompted(profile, latest, due)
        reporters = await _reporters(uow, profile.id, now)
        groups = await self._groups(uow, me, reporters, now)
        # Every service this command prompts: the one asked for, and the others in its groups. Their
        # own jobs will do nothing, so each must be fully served here (DEC-156 item 5).
        prompted: dict[str, _Prompted] = {profile.id: me}
        for group in groups:
            for member in group.members:
                prompted.setdefault(member.prompted.profile.id, member.prompted)
        sent_by_group = {
            (member.prompted.profile.id, group.phone_hash)
            for group in groups
            for member in group.members
        }

        recorded: dict[str, list[str]] = {service_id: [] for service_id in prompted}
        for group in groups:
            await self._send_group(uow, group, now, recorded)
        for service_id, one in prompted.items():
            roles = (
                reporters if service_id == profile.id else await _reporters(uow, service_id, now)
            )
            singles = [
                (role, phone) for role, phone in roles if (service_id, phone) not in sent_by_group
            ]
            await self._send_singles(uow, one, singles, now, recorded[service_id])

        for service_id, one in prompted.items():
            ids = recorded[service_id]
            if ids:
                for communication_id in ids:
                    await self._ladder(uow, communication_id, one.due, now)
            else:
                # Nobody can be texted: the chase is about the service (DEC-115 item 15).
                await self._ladder(uow, service_id, one.due, now)
            await self._rearm(uow, one.profile, one.due, now)
            if service_id != profile.id:
                await self._store_for_member(
                    uow, command, one, tuple(ids), _grouped_ids(groups, service_id)
                )
        mine = tuple(recorded[profile.id])
        reason = None if mine else SKIP_NO_REPORTER
        everything = tuple(
            communication_id for ids in recorded.values() for communication_id in ids
        )
        await self._audit(
            uow, command, profile.id, due, now, everything, tuple(prompted)[1:], reason
        )
        return SendPromptResult(
            sent=bool(mine),
            communication_ids=mine,
            skipped_reason=reason,
            grouped_service_ids=_grouped_ids(groups, profile.id),
        )

    async def _groups(
        self,
        uow: UnitOfWork,
        me: _Prompted,
        reporters: list[tuple[PractitionerRole, str]],
        now: datetime,
    ) -> list[_Group]:
        """The group each of this service's reporter phones is prompted in, if any. Only a text
        prompt with a figure can be grouped (DEC-156 items 2 and 3)."""
        latest = me.latest
        if (
            latest is None
            or me.profile.channel is not Channel.TEXT
            or _too_old_to_confirm(latest, now)
        ):
            return []
        groups: list[_Group] = []
        seen: set[str] = set()
        for role, phone_hash in reporters:
            if phone_hash in seen:
                continue
            seen.add(phone_hash)
            group = await self._group_for_phone(uow, me, latest.value, role, phone_hash, now)
            if group is not None:
                groups.append(group)
        return groups

    async def _group_for_phone(
        self,
        uow: UnitOfWork,
        me: _Prompted,
        my_figure: int,
        my_role: PractitionerRole,
        phone_hash: str,
        now: datetime,
    ) -> _Group | None:
        """The services this phone is prompted for together with `me`, or None when it is alone.
        The other services are looked up through the unit of work, so only this tenant's are seen
        (DEC-156 item 10)."""
        held: dict[str, PractitionerRole] = {}
        for role, _ in await uow.people.services_for_phone_hash(phone_hash, now):
            if role.service_id and role.service_id != me.profile.id:
                held.setdefault(role.service_id, role)
        members: list[tuple[_Prompted, PractitionerRole, int]] = [(me, my_role, my_figure)]
        for service_id, role in held.items():
            other = await self._eligible(uow, service_id, me.due, now)
            if other is not None:
                members.append((other[0], role, other[1]))
        if len(members) < 2:
            return None
        try:
            batches = group_due(
                [(one.profile.id, one.profile.name, one.due) for one, _, _ in members]
            )
        except ValidationFailed:
            # Names that letters cannot tell apart, or too many services for the alphabet: nobody is
            # grouped, and every service is prompted by its own job (DEC-156 item 6).
            return None
        batch = next(b for b in batches if any(i.service_id == me.profile.id for i in b.items))
        if len(batch.items) < 2:
            return None
        by_id = {one.profile.id: (one, role, figure) for one, role, figure in members}
        lettered = sorted(batch.items, key=lambda item: str(item.letter))
        chosen = [_Member(*by_id[i.service_id], item=i) for i in lettered]
        try:
            rendered = render(
                MessageId.C9,
                Channel.TEXT,
                reply_by=format_hhmm(batch.reply_by),
                items=[(str(m.item.letter), m.prompted.profile.name, m.figure) for m in chosen],
            )
        except ValidationFailed:
            return None
        return _Group(phone_hash, tuple(chosen), rendered)

    async def _eligible(
        self, uow: UnitOfWork, service_id: str, near: datetime, now: datetime
    ) -> tuple[_Prompted, int] | None:
        """Another service of the phone, as it can be grouped: a text service with a figure, active,
        not suspended and in hours at a due time within GROUP_WINDOW of `near` whose own prompt has
        not already been handled. None for any other (DEC-156 items 2 to 4)."""
        profile = await uow.services.get(service_id)
        if profile is None or profile.channel is not Channel.TEXT:
            return None
        latest = await uow.capacity.latest(service_id)
        if latest is None or _too_old_to_confirm(latest, now):
            return None
        suspended = any(
            flag.code == SERVICE_FLAG_SUSPENDED
            for flag in await uow.flags.service_flags(service_id)
        )
        times = [current_due(profile, near), next_due(profile, near)]
        close = sorted(
            (t for t in times if t is not None and abs(t - near) < GROUP_WINDOW),
            key=lambda t: abs(t - near),
        )
        for due in close:
            if await uow.idempotency.get(prompt_key(service_id, due)) is not None:
                continue
            window = split_unit_label(profile.unit_label)
            if _skip_reason(profile, suspended, due, now, True, window) is None:
                return _Prompted(profile, latest, due), latest.value
        return None

    async def _send_group(
        self, uow: UnitOfWork, group: _Group, now: datetime, recorded: dict[str, list[str]]
    ) -> None:
        """One C9 Communication for each service of the group, in letter order. Only letter A's is
        queued and has an outbox message; the others are 'grouped' (DEC-156 item 7)."""
        for index, member in enumerate(group.members):
            communication_id = self._ids.new_id()
            first = index == 0
            await uow.communications.add(
                Communication(
                    id=communication_id,
                    message_id=MessageId.C9.value,
                    channel=Channel.TEXT,
                    recipient_role_id=member.role.id,
                    about_id=member.prompted.profile.id,
                    payload_text=group.rendered.text,
                    sent_at=now,
                    delivery_status="queued" if first else GROUPED_STATUS,
                )
            )
            if first:
                await self._enqueue(
                    uow, communication_id, MessageId.C9, member.role, group.rendered, now
                )
            recorded[member.prompted.profile.id].append(communication_id)

    async def _send_singles(
        self,
        uow: UnitOfWork,
        one: _Prompted,
        reporters: list[tuple[PractitionerRole, str]],
        now: datetime,
        recorded: list[str],
    ) -> None:
        """The prompt for one service on its own to each reporter, as before grouping (U03)."""
        reply = reply_by(one.due)
        window = split_unit_label(one.profile.unit_label)
        tokens = self._link_tokens(uow.link_tokens)
        for role, phone_hash in reporters:
            communication_id = self._ids.new_id()
            token = await tokens.issue(LINK_PURPOSE, communication_id, phone_hash, reply)
            link = f"{self._link_base_url}/{token}"
            message_id, rendered = _render(one.profile, one.latest, window, link, reply)
            await uow.communications.add(
                Communication(
                    id=communication_id,
                    message_id=message_id.value,
                    channel=one.profile.channel,
                    recipient_role_id=role.id,
                    about_id=one.profile.id,
                    payload_text=rendered.text.replace(link, LINK_PLACEHOLDER),
                    sent_at=now,
                    delivery_status="queued",
                )
            )
            await self._enqueue(uow, communication_id, message_id, role, rendered, now)
            recorded.append(communication_id)

    async def _enqueue(
        self,
        uow: UnitOfWork,
        communication_id: str,
        message_id: MessageId,
        role: PractitionerRole,
        rendered: RenderedMessage,
        now: datetime,
    ) -> None:
        outbox_id = self._ids.new_id()
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

    async def _store_for_member(
        self,
        uow: UnitOfWork,
        command: SendPromptCommand,
        one: _Prompted,
        communication_ids: tuple[str, ...],
        grouped: tuple[str, ...],
    ) -> None:
        """Store the result under the key of the grouped service's own prompt, so that its job does
        nothing when it runs. The fingerprint is that of the command the job will send: this
        command's actor, its service and its due time (DEC-104, DEC-156 item 5)."""
        own = replace(command, service_id=one.profile.id, due_at=one.due)
        result = SendPromptResult(
            sent=bool(communication_ids),
            communication_ids=communication_ids,
            skipped_reason=None if communication_ids else SKIP_NO_REPORTER,
            grouped_service_ids=grouped,
        )
        await uow.idempotency.put(
            prompt_key(one.profile.id, one.due), _StoredPrompt(_fingerprint(own), result)
        )

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
        grouped_service_ids: tuple[str, ...],
        skipped_reason: str | None,
    ) -> None:
        """One entry for the command. It names every message written and every service prompted, so
        a grouped prompt is traceable from each of its services (DEC-156 item 11)."""
        await uow.audit.append(
            AuditEntry(
                action=AUDIT_ACTION,
                use_case=USE_CASE,
                actor=command.actor,
                entity_ids=(*communication_ids, service_id, *grouped_service_ids),
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
    inactive or has no phone cannot be texted: that role is left out. So is a holder whose new
    phone waits for the lead's call-back (U37): the old one may be lost, so nothing is texted to the
    number until the lead has phoned the register number. The cover is the holder while a cover is
    in force, and with no one to text the ladder tells the lead."""
    holder = await uow.people.get_practitioner(role_holder(role, now))
    if holder is None or not holder.active:
        return None
    if await uow.devices.awaiting_callback(holder.id):
        return None
    return holder.phone_hash
