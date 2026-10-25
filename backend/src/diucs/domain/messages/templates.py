"""Message templates: the capacity messages C1 to C11 (D15) and the booking, invitation, code
and alert messages B1 to B7, I1 to I3 and K1 to K4 (D16), rendered as pure functions.

Wording: docs/spec/domain-rules.md section 9 and the D15 and D16 prompts. Field names per id:
docs/spec/contracts.md. DEC-034 records the capacity choices the prompt leaves open: which fields
each channel needs, the email bodies, push wording for C8, and the minimum number of items for C9.
DEC-037 records the booking, invitation, code and alert choices: the B2, B3 and K2 email and push
wording (not yet IG-approved), the B7 minimum of two references, and the [ASSUMED] texts.

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
MIN_MULTI_REFERENCES: Final = 2
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


_FIELDS: Final[Mapping[MessageId, frozenset[str]]] = {
    MessageId.B1: frozenset(
        {"reference", "service", "age_band", "need", "urgency", "link", "reply_by"}
    ),
    MessageId.B2: frozenset(
        {"reference", "service", "age_band", "need", "urgency", "link", "reply_by"}
    ),
    MessageId.B3: frozenset({"reference", "service", "reply_by"}),
    MessageId.B4: frozenset({"reference", "service", "confirmed_at"}),
    MessageId.B5: frozenset({"reference"}),
    MessageId.B6: frozenset({"reference", "cancelled_at"}),
    MessageId.B7: frozenset({"references"}),
    MessageId.I1: frozenset({"service", "link"}),
    MessageId.I2: frozenset({"link"}),
    MessageId.I3: frozenset({"service"}),
    MessageId.K1: frozenset({"code"}),
    MessageId.K2: frozenset({"service", "review_by"}),
    MessageId.K3: frozenset({"title", "body"}),
    MessageId.K4: frozenset({"service"}),
    MessageId.C1: frozenset({"service", "value", "unit", "as_of", "link", "reply_by"}),
    MessageId.C2: frozenset({"service", "unit", "window", "reply_by", "link"}),
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
    "DIUCS: {service}. How many {unit} can you take {window}? "
    "Send a number (0 = closed). By {reply_by}."
)
_C8_TEXT: Final = (
    "DIUCS reminder: {service} has not updated. Confirm or update: {link} By {reply_by}."
)
_EMAIL_SUBJECT: Final = "{service}: confirm or update by {reply_by}"
_PUSH_SUBJECT: Final = "{service}: confirm or update"

_B1_TEXT: Final = (
    "DIUCS REQUEST {reference}: {service}. Age {age_band}, {need}, {urgency}. "
    "Referral details follow in SystmOne. Reply CONFIRMED or DECLINE, or open {link} by {reply_by}."
)
_B2_LINES: Final = (
    "Booking request {reference} for {service}.\n"
    "Age band {age_band}\n"
    "Need: {need}\n"
    "Response wanted: {urgency}\n"
    "Referral details follow in SystmOne.\n"
    "Please review and reply by {reply_by}.\n"
)
_B2_NO_BOOKING: Final = (
    "Opening the link does not book anything. You confirm on the next page. "
    "The link works once and needs no login."
)
_B7_TEXT: Final = (
    "You have more than one open request: {references}. Reply CONFIRMED or DECLINE "
    "with the reference, for example CONFIRMED {first_reference}."
)
_K2_TEXT: Final = "Due {review_by}. Confirm or update in 2 minutes."

_TEMPLATES: Final[Mapping[tuple[MessageId, Channel], _Template]] = {
    (MessageId.C1, Channel.TEXT): _Template(required=_FIELDS[MessageId.C1], text=_C1_TEXT),
    # IG-pending (DEC-034 item 3): the email body and HTML are not owner-approved.
    (MessageId.C1, Channel.EMAIL): _Template(
        required=_FIELDS[MessageId.C1],
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
        required=frozenset({"service", "unit", "window", "reply_by"}), text=_C2_TEXT
    ),
    (MessageId.C2, Channel.EMAIL): _Template(
        required=_FIELDS[MessageId.C2],
        # IG-pending (DEC-034 item 3): email body and HTML are not owner-approved.
        text=f"{_C2_TEXT}\n\nConfirm or update: {{link}}\n\n{FOOTER}",
        subject=_EMAIL_SUBJECT,
        html=(
            "<p>DIUCS: {service}. How many {unit} can you take {window}? "
            "Send a number (0 = closed). By {reply_by}.</p>\n"
            f'<p><a href="{{link}}" style="{BUTTON_STYLE}">Confirm or update</a></p>\n'
            f"<p>{FOOTER}</p>"
        ),
    ),
    (MessageId.C2, Channel.PUSH): _Template(
        required=frozenset({"service", "unit", "window", "reply_by"}),
        text="How many {unit} can you take {window}? Reply by {reply_by}.",
        subject=_PUSH_SUBJECT,
    ),
    (MessageId.C3, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.C3],
        text="Thanks. {service}: {value} {unit}, as of {recorded_at}. Next prompt {next_due}.",
    ),
    (MessageId.C4, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.C4],
        text="Updated: {service} {value} {unit}, as of {recorded_at}. Replaces {replaced}.",
    ),
    (MessageId.C5, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.C5],
        text=(
            "Too late: the {cutoff} cut-off had passed, so {rejected} was not used. "
            "New question: {service} has {value} {unit} recorded. "
            "Reply Y if right, or send the new number, by {reply_by}."
        ),
    ),
    (MessageId.C6, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.C6],
        text="Y was used twice already. Please send the number for {service}.",
    ),
    (MessageId.C7, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.C7],
        text=(
            "{service}: {value} is outside the usual range of {low} to {high}. "
            "If it is right, send {value} again."
        ),
    ),
    (MessageId.C8, Channel.TEXT): _Template(required=_FIELDS[MessageId.C8], text=_C8_TEXT),
    (MessageId.C8, Channel.EMAIL): _Template(
        required=_FIELDS[MessageId.C8],
        text=f"{_C8_TEXT}\n\n{FOOTER}",
        subject=_EMAIL_SUBJECT,
        html=(
            "<p>DIUCS reminder: {service} has not updated.</p>\n"
            f'<p><a href="{{link}}" style="{BUTTON_STYLE}">Confirm or update</a> '
            "By {reply_by}.</p>\n"
            f"<p>{FOOTER}</p>"
        ),
    ),
    # IG-pending (DEC-034 item 4): this push wording is not in the spec and is not approved.
    (MessageId.C8, Channel.PUSH): _Template(
        required=frozenset({"service", "reply_by"}),
        text="{service} has not updated. Reply by {reply_by}.",
        subject=_PUSH_SUBJECT,
    ),
    (MessageId.C9, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.C9],
        text=(
            "DIUCS: {count} services need an update by {reply_by}. {items_text}. "
            "Reply Y if {both_or_all} right, or {first_reply}, or {second_reply}."
        ),
    ),
    (MessageId.C10, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.C10], text="Thanks. {changes}"
    ),
    (MessageId.C11, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.C11],
        text=(
            "DIUCS: reply Y if the figure is right, or send a number (0 = closed). "
            "For a booking, reply CONFIRMED or DECLINE."
        ),
    ),
    (MessageId.B1, Channel.TEXT): _Template(required=_FIELDS[MessageId.B1], text=_B1_TEXT),
    # IG-pending (DEC-037 item 1): email and push wording is not yet IG-approved.
    (MessageId.B2, Channel.EMAIL): _Template(
        required=_FIELDS[MessageId.B2],
        text=(f"{_B2_LINES}Review request: {{link}}\n\n{_B2_NO_BOOKING}"),
        subject="Booking request {reference}: {service}, reply by {reply_by}",
        html=(
            "<p>Booking request {reference} for {service}.</p>\n"
            "<p>Age band {age_band}<br>Need: {need}<br>Response wanted: {urgency}</p>\n"
            "<p>Referral details follow in SystmOne.</p>\n"
            "<p>Please review and reply by {reply_by}.</p>\n"
            f'<p><a href="{{link}}" style="{BUTTON_STYLE}">Review request</a></p>\n'
            f"<p>{_B2_NO_BOOKING}</p>"
        ),
    ),
    # IG-pending (DEC-037 item 1): push wording is not yet IG-approved.
    (MessageId.B3, Channel.PUSH): _Template(
        required=_FIELDS[MessageId.B3],
        text="Reply by {reply_by}. Not booked until you confirm.",
        subject="Booking request {reference}: {service}",
    ),
    (MessageId.B4, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.B4],
        text="Booked: {reference}, {service}, confirmed {confirmed_at}. Thank you.",
    ),
    (MessageId.B5, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.B5],
        text=(
            "Noted: {reference} declined. "
            "Optional reason: reply 1 full, 2 outside criteria, 3 other."
        ),
    ),
    # [ASSUMED] wording (domain-rules section 9 id list; DEC-037 item 4).
    (MessageId.B6, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.B6],
        text=(
            "DIUCS: booking {reference} was cancelled by the SPOA at {cancelled_at}. "
            "No action needed."
        ),
    ),
    (MessageId.B7, Channel.TEXT): _Template(required=_FIELDS[MessageId.B7], text=_B7_TEXT),
    (MessageId.I1, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.I1],
        text=(
            "DIUCS: You are invited to report capacity for {service}. "
            "Set up takes about 3 minutes: {link} Valid for 48 hrs."
        ),
    ),
    (MessageId.I2, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.I2],
        text=(
            "DIUCS: You are invited to see Dorset urgent care capacity on your phone. "
            "Set up takes about 3 minutes: {link} Valid for 48 hrs."
        ),
    ),
    # [ASSUMED] wording (DEC-037 item 4).
    (MessageId.I3, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.I3],
        text="DIUCS test: {service}. Reply Y to show you receive prompts.",
    ),
    # [ASSUMED] wording (DEC-037 item 4).
    (MessageId.K1, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.K1],
        text="DIUCS code: {code}. It works for 10 minutes. Do not share it.",
    ),
    # IG-pending (DEC-037 item 1): email and push wording is not yet IG-approved.
    (MessageId.K2, Channel.EMAIL): _Template(
        required=_FIELDS[MessageId.K2],
        text=_K2_TEXT,
        subject="{service} criteria: review due",
        html="<p>Due {review_by}. Confirm or update in 2 minutes.</p>",
    ),
    (MessageId.K2, Channel.PUSH): _Template(
        required=_FIELDS[MessageId.K2],
        text=_K2_TEXT,
        subject="{service} criteria: review due",
    ),
    (MessageId.K3, Channel.PUSH): _Template(
        required=_FIELDS[MessageId.K3],
        text="{body}",
        subject="{title}",
    ),
    # [ASSUMED] wording (DEC-037 item 4).
    (MessageId.K4, Channel.TEXT): _Template(
        required=_FIELDS[MessageId.K4],
        text=(
            "DIUCS: {service} is suspended. Prompts have stopped. "
            "The SPOA shift lead will phone you."
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


def _reference_values(raw: object) -> dict[str, object]:
    # A bare string is iterable, so it is refused before any joining: "4821" must not join as
    # "4, 8, 2, 1".
    if not isinstance(raw, (list, tuple)):
        raise ValidationFailed("references", "must be a list of references")
    references = list(raw)
    if len(references) < MIN_MULTI_REFERENCES:
        raise ValidationFailed("references", "more than one open request needs two or more")
    if not all(isinstance(reference, str) and reference for reference in references):
        raise ValidationFailed("references", "each reference is non-empty text")
    return {
        "references": ", ".join(references),
        "first_reference": references[0],
    }


def _values(message_id: MessageId, fields: Mapping[str, object]) -> dict[str, object]:
    if message_id is MessageId.C9:
        return _multi_service_values(fields["items"], fields["reply_by"])
    if message_id is MessageId.C10:
        return _partial_echo_values(fields["updated"], fields["waiting"])
    if message_id is MessageId.B7:
        return _reference_values(fields["references"])
    return dict(fields)


def render(message_id: MessageId, channel: Channel, **fields: object) -> RenderedMessage:
    """Render one message for one channel.

    Raises ValidationFailed for a field the message does not take, a required field that is
    missing, a channel the message is not sent on, or a list (multi-service items, B7 references)
    that cannot be worded.
    """
    message_id = MessageId(message_id)
    unexpected = sorted(set(fields) - _FIELDS[message_id])
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
