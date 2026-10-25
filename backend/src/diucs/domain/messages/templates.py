"""Message templates (D15): the capacity messages C1 to C11, rendered as pure functions.

Wording: docs/spec/domain-rules.md section 9 and the D15 prompt. Field names per id:
docs/spec/contracts.md. DEC-034 records the choices the prompt leaves open: which fields each
channel needs, the email bodies, push wording for C8, and the minimum number of items for C9.

Callers pass time fields already formatted as "HH:MM" strings and the unit phrase as text.
No template holds a patient name, NHS number or postcode, and no field may add one.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from typing import Final, cast

from diucs.domain.codes import Channel
from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.catalogue import MessageId

FOOTER: Final = (
    "The link works once, needs no login, and expires at {reply_by}. "
    "This email has no patient information."
)
BUTTON_STYLE: Final = (
    "display:inline-block;padding:12px 20px;background:#0B5C8C;color:#FFFFFF;"
    "text-decoration:none;border-radius:4px"
)
MIN_MULTI_SERVICE_ITEMS: Final = 2
BOTH: Final = 2


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    message_id: MessageId
    channel: Channel
    text: str
    subject: str | None = None
    html: str | None = None


@dataclass(frozen=True, slots=True)
class _Template:
    required: frozenset[str]
    text: str
    subject: str | None = None
    html: str | None = None


_CAPACITY_FIELDS: Final[Mapping[MessageId, frozenset[str]]] = {
    MessageId.C1: frozenset({"service", "value", "unit", "as_of", "link", "reply_by"}),
    MessageId.C2: frozenset({"service", "unit", "reply_by", "link"}),
    MessageId.C3: frozenset({"service", "value", "unit", "recorded_at", "next_due"}),
    MessageId.C4: frozenset({"service", "value", "unit", "recorded_at", "replaced"}),
    MessageId.C5: frozenset({"cutoff", "rejected", "service", "value", "unit", "reply_by"}),
    MessageId.C6: frozenset({"service"}),
    MessageId.C7: frozenset({"service", "value", "low", "high"}),
    MessageId.C8: frozenset({"service", "reply_by", "link"}),
    MessageId.C9: frozenset({"reply_by", "items"}),
    MessageId.C10: frozenset({"updated", "waiting"}),
    MessageId.C11: frozenset(),
}

_C1_TEXT: Final = (
    "DIUCS: {service}. We have {value} {unit} (as of {as_of}). "
    "Confirm or update: {link} Or reply Y, or a new number. By {reply_by}."
)
_C2_TEXT: Final = (
    "DIUCS: {service}. How many {unit} can you take? Send a number (0 = closed). By {reply_by}."
)
_C8_TEXT: Final = (
    "DIUCS reminder: {service} has not updated. Confirm or update: {link} By {reply_by}."
)
_EMAIL_SUBJECT: Final = "{service}: confirm or update by {reply_by}"
_PUSH_SUBJECT: Final = "{service}: confirm or update"

_TEMPLATES: Final[Mapping[tuple[MessageId, Channel], _Template]] = {
    (MessageId.C1, Channel.TEXT): _Template(required=_CAPACITY_FIELDS[MessageId.C1], text=_C1_TEXT),
    (MessageId.C1, Channel.EMAIL): _Template(
        required=_CAPACITY_FIELDS[MessageId.C1],
        text=f"{_C1_TEXT}\n\n{FOOTER}",
        subject=_EMAIL_SUBJECT,
        html=(
            "<p>DIUCS: {service}. We have {value} {unit} (as of {as_of}).</p>\n"
            f'<p><a href="{{link}}" style="{BUTTON_STYLE}">Confirm or update</a> '
            "Or reply Y, or a new number. By {reply_by}.</p>\n"
            f"<p>{FOOTER}</p>"
        ),
    ),
    (MessageId.C1, Channel.PUSH): _Template(
        required=frozenset({"service", "value", "unit", "reply_by"}),
        text="We have {value} {unit} recorded. Reply by {reply_by}.",
        subject=_PUSH_SUBJECT,
    ),
    (MessageId.C2, Channel.TEXT): _Template(
        required=frozenset({"service", "unit", "reply_by"}), text=_C2_TEXT
    ),
    (MessageId.C2, Channel.EMAIL): _Template(
        required=_CAPACITY_FIELDS[MessageId.C2],
        text=f"{_C2_TEXT}\n\nConfirm or update: {{link}}\n\n{FOOTER}",
        subject=_EMAIL_SUBJECT,
        html=(
            "<p>DIUCS: {service}. How many {unit} can you take? "
            "Send a number (0 = closed). By {reply_by}.</p>\n"
            f'<p><a href="{{link}}" style="{BUTTON_STYLE}">Confirm or update</a></p>\n'
            f"<p>{FOOTER}</p>"
        ),
    ),
    (MessageId.C2, Channel.PUSH): _Template(
        required=frozenset({"service", "unit", "reply_by"}),
        text="How many {unit} can you take? Reply by {reply_by}.",
        subject=_PUSH_SUBJECT,
    ),
    (MessageId.C3, Channel.TEXT): _Template(
        required=_CAPACITY_FIELDS[MessageId.C3],
        text="Thanks. {service}: {value} {unit}, as of {recorded_at}. Next prompt {next_due}.",
    ),
    (MessageId.C4, Channel.TEXT): _Template(
        required=_CAPACITY_FIELDS[MessageId.C4],
        text="Updated: {service} {value} {unit}, as of {recorded_at}. Replaces {replaced}.",
    ),
    (MessageId.C5, Channel.TEXT): _Template(
        required=_CAPACITY_FIELDS[MessageId.C5],
        text=(
            "Too late: the {cutoff} cut-off had passed, so {rejected} was not used. "
            "New question: {service} has {value} {unit} recorded. "
            "Reply Y if right, or send the new number, by {reply_by}."
        ),
    ),
    (MessageId.C6, Channel.TEXT): _Template(
        required=_CAPACITY_FIELDS[MessageId.C6],
        text="Y was used twice already. Please send the number for {service}.",
    ),
    (MessageId.C7, Channel.TEXT): _Template(
        required=_CAPACITY_FIELDS[MessageId.C7],
        text=(
            "{service}: {value} is outside the usual range of {low} to {high}. "
            "If it is right, send {value} again."
        ),
    ),
    (MessageId.C8, Channel.TEXT): _Template(required=_CAPACITY_FIELDS[MessageId.C8], text=_C8_TEXT),
    (MessageId.C8, Channel.EMAIL): _Template(
        required=_CAPACITY_FIELDS[MessageId.C8],
        text=f"{_C8_TEXT}\n\n{FOOTER}",
        subject=_EMAIL_SUBJECT,
        html=(
            "<p>DIUCS reminder: {service} has not updated.</p>\n"
            f'<p><a href="{{link}}" style="{BUTTON_STYLE}">Confirm or update</a> '
            "By {reply_by}.</p>\n"
            f"<p>{FOOTER}</p>"
        ),
    ),
    (MessageId.C8, Channel.PUSH): _Template(
        required=frozenset({"service", "reply_by"}),
        text="{service} has not updated. Reply by {reply_by}.",
        subject=_PUSH_SUBJECT,
    ),
    (MessageId.C9, Channel.TEXT): _Template(
        required=_CAPACITY_FIELDS[MessageId.C9],
        text=(
            "DIUCS: {count} services need an update by {reply_by}. {items_text}. "
            "Reply Y if {both_or_all} right, or {first_reply}, or {second_reply}."
        ),
    ),
    (MessageId.C10, Channel.TEXT): _Template(
        required=_CAPACITY_FIELDS[MessageId.C10], text="Thanks. {changes}"
    ),
    (MessageId.C11, Channel.TEXT): _Template(
        required=_CAPACITY_FIELDS[MessageId.C11],
        text=(
            "DIUCS: reply Y if the figure is right, or send a number (0 = closed). "
            "For a booking, reply CONFIRMED or DECLINE."
        ),
    ),
}


def _rows(name: str, raw: object, arity: int) -> list[tuple[object, ...]]:
    if not isinstance(raw, (list, tuple)):
        raise ValidationFailed(name, "must be a list")
    rows: list[tuple[object, ...]] = []
    for row in raw:
        if not isinstance(row, tuple) or len(row) != arity:
            raise ValidationFailed(name, f"each item needs {arity} parts")
        rows.append(cast(tuple[object, ...], row))
    return rows


def _multi_service_values(raw: object, reply_by: object) -> dict[str, object]:
    rows = _rows("items", raw, 3)
    if len(rows) < MIN_MULTI_SERVICE_ITEMS:
        raise ValidationFailed("items", "a multi-service prompt needs two or more services")
    items: list[tuple[str, str, int]] = []
    for letter, service, value in rows:
        if not (
            isinstance(letter, str)
            and isinstance(service, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            raise ValidationFailed("items", "each item is (letter, service, whole number)")
        items.append((letter, service, value))
    items_text = ". ".join(f"{letter}) {service} {value}" for letter, service, value in items)
    first, second = items[0], items[1]
    return {
        "reply_by": reply_by,
        "count": len(items),
        "items_text": items_text,
        "both_or_all": "both" if len(items) == BOTH else "all",
        "first_reply": f"{first[0]} {first[2] + 1}",
        "second_reply": f"{second[0]} {second[2] + 1}",
    }


def _partial_echo_values(updated: object, waiting: object) -> dict[str, object]:
    changes: list[str] = []
    for letter, service, value in _rows("updated", updated, 3):
        changes.append(f"{letter}) {service} updated to {value}.")
    for letter, service in _rows("waiting", waiting, 2):
        changes.append(
            f"{letter}) {service} still needs a reply: Y {letter}, or {letter} and a number."
        )
    if not changes:
        raise ValidationFailed("updated", "nothing to echo")
    return {"changes": " ".join(changes)}


def _values(message_id: MessageId, fields: Mapping[str, object]) -> dict[str, object]:
    if message_id is MessageId.C9:
        return _multi_service_values(fields["items"], fields["reply_by"])
    if message_id is MessageId.C10:
        return _partial_echo_values(fields["updated"], fields["waiting"])
    return dict(fields)


def render(message_id: MessageId, channel: Channel, **fields: object) -> RenderedMessage:
    """Render one capacity message for one channel.

    Raises ValidationFailed for a field the message does not take, a required field that is
    missing, a channel the message is not sent on, or a multi-service list that cannot be
    worded. Raises NotImplementedError for the booking, invitation and code ids (D16).
    """
    message_id = MessageId(message_id)
    if message_id not in _CAPACITY_FIELDS:
        raise NotImplementedError(f"{message_id.value} is built in D16")
    unexpected = sorted(set(fields) - _CAPACITY_FIELDS[message_id])
    if unexpected:
        raise ValidationFailed(unexpected[0], "not a field of this message")
    template = _TEMPLATES.get((message_id, channel))
    if template is None:
        raise ValidationFailed("channel", f"{message_id.value} is not sent by {channel.value}")
    missing = sorted(template.required - set(fields))
    if missing:
        raise ValidationFailed(missing[0], "required field is missing")

    values = _values(message_id, fields)
    html_values = {key: escape(str(value)) for key, value in values.items()}
    return RenderedMessage(
        message_id=message_id,
        channel=channel,
        text=template.text.format(**values),
        subject=None if template.subject is None else template.subject.format(**values),
        html=None if template.html is None else template.html.format(**html_values),
    )
