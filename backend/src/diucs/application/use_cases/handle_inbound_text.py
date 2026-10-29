"""HandleInboundText: a text from a reporter's phone, read as a capacity reply (U05).

The text is parsed (D10), judged against the open prompt by the reply policy (D11), and acted on:
a figure goes to ReportCapacity (U01), a Y to ConfirmCapacity (U02), and every refusal is a
Communication plus a SendMessage outbox message, audited as `HandleInboundText`. Reports are never
written here and the rules of U01 and U02 are not repeated. An unknown phone is dropped with no
write and no reply.

Hazard H-31 (DEC-148): a Y confirms the figure on record, so it must not make an old figure
current. D11's confirm branch never looks at the figure's date, so this use case does: when the
figure a Y would confirm was older than CONFIRMABLE_FIGURE_AGE at the moment the prompt named it,
ConfirmCapacity is not called, nothing is recorded, and the reporter is told the figure is out of
date (C12) and asked for a number.

The inbound text is never stored: not in an audit snapshot, not in a Communication. The tenant is
not a field of the command. It is bound at the edge from the number called (DEC-131), and the cache
adds the tenant prefix to every key, so `recheck:{phone_hash}:{service_id}` is tenant-scoped there.
Decisions: DEC-148.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import current_tenant
from diucs.application.use_cases.confirm_capacity import (
    ConfirmCapacityCommand,
    ConfirmCapacityResult,
)
from diucs.application.use_cases.report_capacity import (
    ReportCapacityCommand,
    ReportCapacityResult,
)
from diucs.application.use_cases.send_prompts import split_unit_label
from diucs.domain.codes import Channel, ReportFlagReason, ReportSource, ReportType, Role
from diucs.domain.errors import (
    ConfirmLimitReached,
    Conflict,
    LatestReportChanged,
    NothingToConfirm,
    ValidationFailed,
)
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.people import PractitionerRole
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.freshness import STALE_WARNING_AFTER
from diucs.domain.rules.london_time import format_hhmm, format_stamp
from diucs.domain.rules.multi_service import letters_for
from diucs.domain.rules.reply_parser import (
    BookingConfirm,
    BookingDecline,
    Confirm,
    Number,
    ParsedReply,
    parse_reply,
)
from diucs.domain.rules.reply_policy import (
    CORRECTION_WINDOW,
    AskRecheck,
    PromptState,
    RecordConfirm,
    RecordNumber,
    RejectConfirmLimit,
    RejectLate,
    decide_capacity_reply,
)
from diucs.domain.rules.schedule import reply_by

RECORDED: Final = "recorded"
CONFIRMED: Final = "confirmed"
LATE: Final = "late"
CONFIRM_LIMIT: Final = "confirm-limit"
RECHECK: Final = "recheck"
HELP: Final = "help"
DROPPED: Final = "dropped"
BOOKING_NOT_HANDLED: Final = "booking-not-handled"
STALE_FIGURE: Final = "stale-figure"
NEED_NUMBER: Final = "need-number"

# What a message that answers several items reports, most important first (DEC-148 item 12).
_OUTCOME_ORDER: Final = (
    RECORDED,
    CONFIRMED,
    RECHECK,
    LATE,
    CONFIRM_LIMIT,
    STALE_FIGURE,
    NEED_NUMBER,
    HELP,
)

CONFIRMABLE_FIGURE_AGE: Final = STALE_WARNING_AFTER
"""A Y confirms a figure only if it was no older than this when the prompt named it (DEC-148)."""

CONFIRM_PROCESSING_LIMIT: Final = timedelta(minutes=10)
"""A Y is recorded only if it is processed within this long of being received (DEC-148 item 19)."""

PROMPT_MESSAGES: Final = frozenset(
    message.value
    for message in (
        MessageId.C1,
        MessageId.C2,
        MessageId.C5,
        MessageId.C8,
        MessageId.C9,
        MessageId.C12,
    )
)
"""The messages that ask for a reply: the open prompt is the latest of these (DEC-148 item 3)."""

MESSAGES_TOPIC: Final = "messages.outbound"
SEND_MESSAGE: Final = "SendMessage"
USE_CASE: Final = "HandleInboundText"
AUDIT_ACTION: Final = "C"
ONE_SECOND: Final = timedelta(seconds=1)
_NUMBER: Final = "number"
_CONFIRM: Final = "confirm"


@dataclass(frozen=True, slots=True)
class HandleInboundTextCommand:
    idempotency_key: str
    from_phone_hash: str
    text: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class HandleInboundTextResult:
    outcome: str
    service_ids: tuple[str, ...]
    replayed: bool = False


class _ReportsCapacity(Protocol):
    async def execute(self, command: ReportCapacityCommand) -> ReportCapacityResult: ...


class _ConfirmsCapacity(Protocol):
    async def execute(self, command: ConfirmCapacityCommand) -> ConfirmCapacityResult: ...


def _instant(name: str, value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValidationFailed(name, "must be a timezone-aware datetime")
    return value.astimezone(UTC)


def figure_is_out_of_date(figure_as_of: datetime, prompt_sent_at: datetime) -> bool:
    """True when the figure was older than the window at the moment the prompt named it.

    Both are compared as UTC instants, so a London clock change cannot move the line (lesson L4).
    Exactly the window is still inside it, as D05's stale warning (strictly more than 2 hours). A
    figure reported after the prompt has a negative age and is never out of date.
    """
    as_of = _instant("as_of", figure_as_of)
    sent_at = _instant("sent_at", prompt_sent_at)
    return sent_at - as_of > CONFIRMABLE_FIGURE_AGE


def recorded_since_prompt(report: CapacityReport, prompt_sent_at: datetime) -> bool:
    """True when the store wrote the report at or after the whole second the prompt was sent in.

    This is the record order, not the effective time: a lead may record a figure that was true at
    an earlier time (DEC-140), so a report written after the prompt can carry an effective time
    before it, or exactly at it. The store stamps whole seconds (lesson L65), so the prompt's time
    is cut to the whole second too and a tie counts as since: a figure written in the same second
    as the prompt cannot be told from one written just after it, and the Y fails closed. A report
    with no write time cannot be shown to predate the prompt and counts as since. Both are UTC
    instants, so a London clock change cannot move the line (lesson L4).
    """
    sent = _instant("sent_at", prompt_sent_at).replace(microsecond=0)
    if report.written_at is None:
        return True
    return _instant("written_at", report.written_at) >= sent


def recheck_key(phone_hash: str, service_id: str) -> str:
    """The cache key of an out-of-range figure waiting to be sent again. The cache adds the tenant
    prefix, so this is the key the specification names (U05)."""
    return f"recheck:{phone_hash}:{service_id}"


@dataclass(frozen=True, slots=True)
class _Target:
    """A service a reply can be about: its profile, the role this phone holds for it, and its letter
    on a grouped prompt (None for a prompt about one service)."""

    profile: ServiceProfile
    role_id: str
    letter: str | None

    @property
    def service_id(self) -> str:
        return self.profile.id


@dataclass(frozen=True, slots=True)
class _Reply:
    message_id: MessageId
    role_id: str
    service_id: str
    text: str
    at: datetime | None = None
    """When the reporter is told, if that is not the time the text was received (a Y that waited in
    a queue is answered at the clock, and its reply-by counts from then)."""


@dataclass(frozen=True, slots=True)
class _Write:
    """A figure (`value`) or a confirmation (`value` None) to be written by U01 or U02."""

    value: int | None
    replaced_value: int | None
    flag: ReportFlagReason | None
    expected_latest_id: str | None = None
    """For a confirmation: the report that was judged, which ConfirmCapacity must still find as the
    latest under its lock (DEC-148 item 18)."""

    @property
    def kind(self) -> str:
        return _CONFIRM if self.value is None else _NUMBER


@dataclass(slots=True)
class _Item:
    """What one reply item comes to: a write to make, or a refusal to send."""

    target: _Target
    latest: CapacityReport | None
    outcome: str
    write: _Write | None = None
    reply: _Reply | None = None
    recheck: tuple[str, str, timedelta] | None = None
    recorded_value: int | None = None


@dataclass(slots=True)
class _Plan:
    prompt_id: str
    prompt_sent_at: datetime
    actor: Actor
    grouped: bool
    service_ids: tuple[str, ...]
    told_at: datetime
    items: list[_Item] = field(default_factory=list)
    waiting: list[tuple[str, str]] = field(default_factory=list)
    help_reply: _Reply | None = None
    processing_delay: timedelta = timedelta(0)
    """How long after it was received the text is being processed: a Y is recorded only within
    CONFIRM_PROCESSING_LIMIT of its receipt (DEC-148 item 19). `told_at` is the clock when the plan
    was made, the time a refusal is sent."""


@dataclass(frozen=True, slots=True)
class _StoredInbound:
    """What the idempotency store keeps for a provider message id: the result and a fingerprint of
    the text and phone that made it (DEC-104)."""

    fingerprint: str
    result: HandleInboundTextResult


def _fingerprint(command: HandleInboundTextCommand) -> str:
    """The phone and the text, hashed. The receive time is left out: a redelivery may carry a
    later one. Only the hash is kept, so the text is not stored."""
    body = repr((command.from_phone_hash, command.text))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _replay(stored: object, fingerprint: str) -> HandleInboundTextResult:
    if not isinstance(stored, _StoredInbound) or stored.fingerprint != fingerprint:
        raise Conflict("this provider message id was used for a different text")
    return replace(stored.result, replayed=True)


def _text(message_id: MessageId, **fields: object) -> str:
    return render(message_id, Channel.TEXT, **fields).text


def _help(role_id: str, service_id: str) -> _Reply:
    return _Reply(MessageId.C11, role_id, service_id, _text(MessageId.C11))


def _need_number(target: _Target, now: datetime) -> _Reply:
    """Ask for a number (C2). A unit label with no readable window cannot be worded as C2, and
    nothing is invented (DEC-115 item 13), so the help text goes instead."""
    unit, window = split_unit_label(target.profile.unit_label)
    if not window:
        return _help(target.role_id, target.service_id)
    text = _text(
        MessageId.C2,
        service=target.profile.name,
        unit=unit,
        window=window,
        reply_by=format_hhmm(reply_by(now)),
    )
    return _Reply(MessageId.C2, target.role_id, target.service_id, text)


def _too_late(
    target: _Target,
    latest: CapacityReport | None,
    rejected: str,
    prompt_sent_at: datetime,
    new_reply_by: datetime,
    now: datetime,
) -> _Reply:
    if latest is None:
        return _need_number(target, now)
    text = _text(
        MessageId.C5,
        cutoff=format_hhmm(reply_by(prompt_sent_at)),
        rejected=rejected,
        service=target.profile.name,
        value=latest.value,
        unit=target.profile.unit_label,
        reply_by=format_hhmm(new_reply_by),
    )
    return _Reply(MessageId.C5, target.role_id, target.service_id, text)


def _confirm_limit(target: _Target) -> _Reply:
    # C6 states the confirm limit (TEN-022). Until TEN-026 loads each tenant's policy, the default
    # policy's limit is passed, which is what this use case has always printed.
    text = _text(
        MessageId.C6,
        service=target.profile.name,
        confirm_limit=DEFAULT_POLICY.max_consecutive_confirms,
    )
    return _Reply(MessageId.C6, target.role_id, target.service_id, text)


def _ask_again(target: _Target, value: int) -> _Reply:
    low, high = target.profile.usual_range
    text = _text(MessageId.C7, service=target.profile.name, value=value, low=low, high=high)
    return _Reply(MessageId.C7, target.role_id, target.service_id, text)


def _out_of_date(target: _Target, value: int, as_of: datetime, told_at: datetime) -> _Reply:
    """C12: the figure on record is not one a Y may confirm. The reply-by counts from `told_at`, the
    time the reporter is told, and the message is stored as sent then."""
    text = _text(
        MessageId.C12,
        service=target.profile.name,
        value=value,
        unit=target.profile.unit_label,
        as_of=format_stamp(as_of),
        reply_with="a number" if target.letter is None else f"{target.letter} and a number",
        reply_by=format_hhmm(reply_by(told_at)),
    )
    return _Reply(MessageId.C12, target.role_id, target.service_id, text, told_at)


def _assign(
    replies: Sequence[ParsedReply], targets: Sequence[_Target]
) -> list[tuple[_Target, Confirm | Number]] | None:
    """Pair each parsed reply with the service it is about, or None when any part of the text does
    not name a service of this prompt. Nothing is guessed: a figure with no letter on a grouped
    prompt, an unknown letter, or a letter on a prompt for one service is not understood, and then
    none of the text is acted on."""
    by_letter = {target.letter: target for target in targets}
    grouped = targets[0].letter is not None
    assigned: list[tuple[_Target, Confirm | Number]] = []
    for reply in replies:
        if not isinstance(reply, Confirm | Number):
            return None
        if reply.letter is not None:
            named = by_letter.get(reply.letter)
            if named is None:
                return None
            assigned.append((named, reply))
        elif isinstance(reply, Confirm):
            assigned.extend((target, reply) for target in targets)
        elif grouped:
            return None
        else:
            assigned.append((targets[0], reply))
    return assigned


def _outcome_of(items: Sequence[_Item]) -> tuple[str, tuple[str, ...]]:
    """The outcome of a text and the services it concerns: the most important outcome among its
    items (DEC-148 item 12), and the services whose items had that outcome."""
    outcome = min((item.outcome for item in items), key=_OUTCOME_ORDER.index)
    return outcome, tuple(item.target.service_id for item in items if item.outcome == outcome)


class HandleInboundText:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
        cache: Cache,
        report_capacity: _ReportsCapacity,
        confirm_capacity: _ConfirmsCapacity,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency
        self._cache = cache
        self._report_capacity = report_capacity
        self._confirm_capacity = confirm_capacity

    async def execute(self, command: HandleInboundTextCommand) -> HandleInboundTextResult:
        received = _instant("received_at", command.received_at)
        fingerprint = _fingerprint(command)
        # An early read outside the unit of work. The authoritative check is inside the last one.
        early = await self._idempotency.get(command.idempotency_key)
        if early is not None:
            return _replay(early, fingerprint)
        # The reply is judged at the time it was received, but never at a time after the clock.
        clock_now = self._clock.now().astimezone(UTC)
        now = min(received, clock_now)

        async with self._uow_factory() as uow:
            planned = await self._plan(uow, command, now, clock_now - received, clock_now)
        if isinstance(planned, HandleInboundTextResult):
            return planned
        plan = planned

        for item in plan.items:
            await self._write(command, plan, item, now)
        result = await self._record(command, plan, fingerprint, now)
        if result.replayed:
            return result
        for item in plan.items:
            await self._tidy_cache(command, item)
        return result

    # -- reading: what does this text come to? -----------------------------------------

    async def _plan(
        self,
        uow: UnitOfWork,
        command: HandleInboundTextCommand,
        now: datetime,
        delay: timedelta,
        clock_now: datetime,
    ) -> HandleInboundTextResult | _Plan:
        practitioner = await uow.people.find_by_phone_hash(command.from_phone_hash)
        if practitioner is None:
            return HandleInboundTextResult(DROPPED, ())
        holdings = await uow.people.services_for_phone_hash(command.from_phone_hash, now)
        roles: dict[str, list[PractitionerRole]] = {}
        names: dict[str, str] = {}
        # A reporter role always has a service here (the query reaches it through the service), so
        # the filter only narrows the type.
        held = [(role.service_id, role, name) for role, name in holdings if role.service_id]
        for service_id, role, name in held:
            roles.setdefault(service_id, []).append(role)
            names[service_id] = name
        if not roles:
            return HandleInboundTextResult(DROPPED, ())
        parsed = parse_reply(command.text)
        if any(isinstance(reply, BookingConfirm | BookingDecline) for reply in parsed):
            return HandleInboundTextResult(BOOKING_NOT_HANDLED, ())

        actor = Actor(
            role=Role.REPORTER,
            practitioner_id=practitioner.id,
            device_id=None,
            channel="text",
            service_ids=frozenset(roles),
            tenant_id=current_tenant(),
        )
        prompt = await uow.communications.latest_prompt_for_phone(
            {role.id for role, _ in holdings}, PROMPT_MESSAGES
        )
        about = None if prompt is None else prompt.about_id
        if prompt is None or about is None or about not in roles:
            first = next(iter(roles))
            return self._help_plan(None, actor, (first,), roles[first][0].id, now)
        # Each service with the role this prompt was sent to, and its letter on a grouped prompt.
        members: dict[str, tuple[str | None, str]] | None = {
            about: (None, prompt.recipient_role_id or roles[about][0].id)
        }
        if prompt.message_id == MessageId.C9.value:
            members = await self._group(uow, prompt, roles, names)
        if members is None:
            return self._help_plan(prompt, actor, (about,), roles[about][0].id, now)

        targets: list[_Target] = []
        for service_id, (letter, role_id) in members.items():
            profile = await uow.services.get(service_id)
            if profile is None or not profile.active:
                return HandleInboundTextResult(DROPPED, ())
            targets.append(_Target(profile, role_id, letter))
        assigned = _assign(parsed, targets)
        service_ids = tuple(target.service_id for target in targets)
        if assigned is None:
            return self._help_plan(prompt, actor, service_ids, roles[about][0].id, now)

        plan = _Plan(
            prompt_id=prompt.id,
            prompt_sent_at=prompt.sent_at,
            actor=actor,
            grouped=targets[0].letter is not None,
            service_ids=service_ids,
            told_at=clock_now,
            processing_delay=delay,
        )
        for target, reply in assigned:
            plan.items.append(await self._item(uow, command, plan, target, reply, now))
        if plan.grouped:
            plan.waiting = await self._waiting(uow, plan, targets, assigned)
        return plan

    def _help_plan(
        self,
        prompt: Communication | None,
        actor: Actor,
        service_ids: tuple[str, ...],
        role_id: str,
        now: datetime,
    ) -> _Plan:
        plan = _Plan(
            prompt_id="" if prompt is None else prompt.id,
            prompt_sent_at=now if prompt is None else prompt.sent_at,
            actor=actor,
            grouped=False,
            service_ids=service_ids,
            told_at=now,
        )
        plan.help_reply = _help(role_id, service_ids[0])
        return plan

    async def _group(
        self,
        uow: UnitOfWork,
        prompt: Communication,
        roles: dict[str, list[PractitionerRole]],
        names: dict[str, str],
    ) -> dict[str, tuple[str | None, str]] | None:
        """The services this phone was prompted for by the one C9 that `prompt` belongs to, each
        with its letter and the role the C9 went to, or None when the letters cannot be trusted.

        U04 stores one C9 per grouped service, all with the same send time and text. The letters
        are rebuilt from the names, as the prompt built them, and then checked against the words
        the reporter was sent: a service that has left the phone since would shift every later
        letter, and a reply must never land on the wrong service.
        """
        sent: dict[str, str] = {}
        for service_id, service_roles in roles.items():
            stored = await uow.communications.latest_prompt_for_phone(
                {role.id for role in service_roles}, {MessageId.C9.value}
            )
            if (
                stored is not None
                and stored.sent_at == prompt.sent_at
                and stored.payload_text == prompt.payload_text
                and stored.about_id == service_id
            ):
                sent[service_id] = stored.recipient_role_id or service_roles[0].id
        letters = letters_for([names[service_id] for service_id in sent])
        ordered = sorted(sent, key=lambda service_id: letters[names[service_id]])
        trusted = len(sent) >= 2 and all(
            f"{letters[names[service_id]]}) {names[service_id]} " in prompt.payload_text
            for service_id in ordered
        )
        if not trusted:
            return None
        lettered: dict[str, tuple[str | None, str]] = {
            service_id: (letters[names[service_id]], sent[service_id]) for service_id in ordered
        }
        return lettered

    async def _item(
        self,
        uow: UnitOfWork,
        command: HandleInboundTextCommand,
        plan: _Plan,
        target: _Target,
        reply: Confirm | Number,
        now: datetime,
    ) -> _Item:
        service_id = target.service_id
        latest = await uow.capacity.latest(service_id)
        kind = _NUMBER if isinstance(reply, Number) else _CONFIRM
        written = f"{command.idempotency_key}:{kind}:{service_id}"
        if latest is not None and await self._idempotency.get(written) is not None:
            # An earlier try at this same message already wrote this figure and then failed before
            # it finished. Do not decide again from a state that includes that write.
            done = RECORDED if kind == _NUMBER else CONFIRMED
            return _Item(target, latest, done, recorded_value=latest.value)

        trailing = await uow.capacity.trailing_confirmations(service_id)
        pending = await self._cache.get(recheck_key(command.from_phone_hash, service_id))
        prompt_reply_by = reply_by(plan.prompt_sent_at)
        state = PromptState(
            service_id=service_id,
            reply_by=prompt_reply_by,
            recorded_value=None if latest is None else latest.value,
            consecutive_confirms=trailing,
            last_accepted_at=None if latest is None else latest.effective_at,
            last_accepted_value=None if latest is None else latest.value,
            pending_out_of_range=None if pending is None else int(pending),
            usual_range=target.profile.usual_range,
            letter=target.letter,
        )
        decision = decide_capacity_reply(reply, state, now)
        item = _Item(target, latest, HELP)
        if isinstance(decision, RecordNumber):
            replaced = latest.value if decision.is_correction and latest is not None else None
            item.outcome = RECORDED
            item.write = _Write(decision.value, replaced, decision.flag)
        elif isinstance(decision, RecordConfirm) and pending is not None:
            # DEC-161: a figure the reporter was asked to send again is waiting. A Y is not that
            # answer and does not say which figure is meant, so it records nothing and asks again.
            item.outcome = RECHECK
            item.reply = _ask_again(target, int(pending))
        elif isinstance(decision, RecordConfirm):
            # Hazard H-32: has a number been reported since the prompt named the figure?
            newer = await self._number_after_prompt(uow, service_id, latest, plan.prompt_sent_at)
            self._judge_confirm(item, plan, latest, newer)
        elif isinstance(decision, RejectLate):
            rejected = str(reply.value) if isinstance(reply, Number) else "Y"
            item.outcome = LATE
            item.reply = _too_late(
                target, latest, rejected, plan.prompt_sent_at, decision.new_reply_by, now
            )
        elif isinstance(decision, RejectConfirmLimit):
            item.outcome = CONFIRM_LIMIT
            item.reply = _confirm_limit(target)
        elif isinstance(decision, AskRecheck):
            item.outcome = RECHECK
            item.reply = _ask_again(target, decision.value)
            expiry = prompt_reply_by
            if latest is not None:
                expiry = max(expiry, latest.effective_at + CORRECTION_WINDOW)
            ttl = max(expiry - now, ONE_SECOND)
            item.recheck = (
                recheck_key(command.from_phone_hash, service_id),
                str(decision.value),
                ttl,
            )
        else:
            item.outcome = NEED_NUMBER
            item.reply = _need_number(target, now)
        return item

    @staticmethod
    async def _number_after_prompt(
        uow: UnitOfWork,
        service_id: str,
        latest: CapacityReport | None,
        prompt_sent_at: datetime,
    ) -> bool:
        """True when a number was written for the service since the prompt was sent. A Y is an
        answer to the figure the prompt named; a number that came in since is a figure the
        reporter was never shown, whatever effective time it was given (a lead may record a figure
        for an earlier time, DEC-140): the test is the record order (`recorded_since_prompt`), not
        the effective time. The reports looked at are the latest one and those effective from the
        prompt on; a number written since with an earlier effective time than the latest report
        does not change which figure is current, so the figure the prompt named still is. A
        confirmation repeats a figure and does not count, so the second of two Ys to one prompt is
        still a Y to that figure (hazard H-32, DEC-148 items 17 and 20)."""
        since = await uow.capacity.reports_since(service_id, prompt_sent_at)
        candidates = since if latest is None else [*since, latest]
        return any(
            report.report_type is ReportType.NUMBER
            and recorded_since_prompt(report, prompt_sent_at)
            for report in candidates
        )

    @staticmethod
    def _judge_confirm(
        item: _Item, plan: _Plan, latest: CapacityReport | None, number_after_prompt: bool
    ) -> None:
        """Hazards H-31 and H-32. The policy has said a Y is allowed; it has not looked at the
        figure. A Y is not recorded, and the reporter is sent C12, when the figure was older than
        its window when the prompt named it (H-31), when a number has been reported since the
        prompt (H-32), or when the Y waited more than CONFIRM_PROCESSING_LIMIT between receipt and
        processing, because the confirmation is stamped now and would make the figure current now
        (H-32). Otherwise the judged report is the one ConfirmCapacity must find (DEC-148)."""
        if latest is not None and (
            figure_is_out_of_date(latest.effective_at, plan.prompt_sent_at)
            or number_after_prompt
            or plan.processing_delay > CONFIRM_PROCESSING_LIMIT
        ):
            item.outcome = STALE_FIGURE
            item.reply = _out_of_date(item.target, latest.value, latest.effective_at, plan.told_at)
        else:
            item.outcome = CONFIRMED
            item.write = _Write(None, None, None, None if latest is None else latest.id)

    async def _waiting(
        self,
        uow: UnitOfWork,
        plan: _Plan,
        targets: Sequence[_Target],
        assigned: Sequence[tuple[_Target, Confirm | Number]],
    ) -> list[tuple[str, str]]:
        """The services of the group this text did not answer and that nothing has answered since
        the prompt was sent: the C10 says they still need a reply."""
        mentioned = {target.service_id for target, _ in assigned}
        waiting: list[tuple[str, str]] = []
        for target in targets:
            if target.service_id in mentioned:
                continue
            latest = await uow.capacity.latest(target.service_id)
            if latest is None or latest.effective_at <= plan.prompt_sent_at:
                waiting.append((str(target.letter), target.profile.name))
        return waiting

    # -- writing: through U01 and U02, then this use case's own record ----------------

    async def _write(
        self, command: HandleInboundTextCommand, plan: _Plan, item: _Item, now: datetime
    ) -> None:
        write = item.write
        if write is None:
            return
        target = item.target
        key = f"{command.idempotency_key}:{write.kind}:{target.service_id}"
        echo = not plan.grouped
        try:
            if write.value is None:
                confirmed = await self._confirm_capacity.execute(
                    ConfirmCapacityCommand(
                        idempotency_key=key,
                        actor=plan.actor,
                        service_id=target.service_id,
                        source=ReportSource.TEXT,
                        performer_role_id=target.role_id,
                        send_echo=echo,
                        expected_latest_id=write.expected_latest_id,
                    )
                )
                item.recorded_value = confirmed.confirmed_value
            else:
                await self._report_capacity.execute(
                    ReportCapacityCommand(
                        idempotency_key=key,
                        actor=plan.actor,
                        service_id=target.service_id,
                        value=write.value,
                        source=ReportSource.TEXT,
                        performer_role_id=target.role_id,
                        replaced_value=write.replaced_value,
                        flag=write.flag,
                        send_echo=echo,
                    )
                )
                item.recorded_value = write.value
        except ConfirmLimitReached:
            # Two texts raced: the count under the service lock is the one that counts.
            item.outcome = CONFIRM_LIMIT
            item.reply = _confirm_limit(target)
        except LatestReportChanged as changed:
            # A report landed between the judgement and the write (hazard H-32).
            item.outcome = STALE_FIGURE
            item.reply = _out_of_date(target, changed.latest_value, changed.latest_at, plan.told_at)
        except NothingToConfirm:
            item.outcome = NEED_NUMBER
            item.reply = _need_number(target, now)

    async def _record(
        self,
        command: HandleInboundTextCommand,
        plan: _Plan,
        fingerprint: str,
        now: datetime,
    ) -> HandleInboundTextResult:
        replies = self._replies(plan)
        if plan.items:
            outcome, service_ids = _outcome_of(plan.items)
        else:
            outcome, service_ids = HELP, plan.service_ids
        result = HandleInboundTextResult(outcome, service_ids)
        async with self._uow_factory() as uow:
            stored = await uow.idempotency.get(command.idempotency_key)
            if stored is not None:
                return _replay(stored, fingerprint)
            communication_ids: list[str] = []
            for reply in replies:
                communication_ids.append(await self._send(uow, plan, reply, now))
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE,
                    actor=plan.actor,
                    entity_ids=(*communication_ids, *service_ids),
                    snapshot={
                        "outcome": outcome,
                        "items": len(plan.items),
                        "messages": [reply.message_id.value for reply in replies],
                    },
                    at=now,
                )
            )
            await uow.idempotency.put(command.idempotency_key, _StoredInbound(fingerprint, result))
            await uow.commit()
        return result

    def _replies(self, plan: _Plan) -> list[_Reply]:
        """The messages to send: the help text, each refusal, and, for a grouped prompt, one C10 for
        what was recorded, in place of a C3 for each service."""
        if plan.help_reply is not None:
            return [plan.help_reply]
        replies = [item.reply for item in plan.items if item.reply is not None]
        if plan.grouped:
            updated = [item for item in plan.items if item.outcome in (RECORDED, CONFIRMED)]
            if updated:
                replies.append(self._thanks(updated, plan.waiting))
        return replies

    @staticmethod
    def _thanks(updated: Sequence[_Item], waiting: list[tuple[str, str]]) -> _Reply:
        rows = [
            (
                str(item.target.letter),
                item.target.profile.name,
                item.recorded_value,
            )
            for item in updated
        ]
        text = _text(MessageId.C10, updated=rows, waiting=waiting)
        return _Reply(MessageId.C10, updated[0].target.role_id, updated[0].target.service_id, text)

    async def _send(self, uow: UnitOfWork, plan: _Plan, reply: _Reply, now: datetime) -> str:
        communication = Communication(
            id=self._ids.new_id(),
            message_id=reply.message_id.value,
            channel=Channel.TEXT,
            recipient_role_id=reply.role_id,
            about_id=reply.service_id,
            payload_text=reply.text,
            sent_at=reply.at or now,
            delivery_status="queued",
            in_response_to=plan.prompt_id or None,
        )
        await uow.communications.add(communication)
        await uow.outbox.add(
            OutboxMessage(
                id=self._ids.new_id(),
                topic=MESSAGES_TOPIC,
                event_type=SEND_MESSAGE,
                payload={
                    "communication_id": communication.id,
                    "message_id": reply.message_id.value,
                    "channel": Channel.TEXT.value,
                    "recipient_role_id": reply.role_id,
                    "text": reply.text,
                },
                created_at=now,
            )
        )
        return communication.id

    async def _tidy_cache(self, command: HandleInboundTextCommand, item: _Item) -> None:
        """After the record is committed: keep the out-of-range figure just asked about, and forget
        one that a recorded figure or a Y has settled. Done last, so a retry of a failed message
        does not read its own first attempt as a repeat."""
        key = recheck_key(command.from_phone_hash, item.target.service_id)
        if item.recheck is not None:
            await self._cache.set(key, item.recheck[1], item.recheck[2])
        elif item.outcome in (RECORDED, CONFIRMED):
            await self._cache.delete(key)
