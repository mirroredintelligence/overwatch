"""Tests for diucs.domain.messages.privacy_guard and the build-time sweep over every template (D17).

Rules: docs/spec/domain-rules.md section 9 and 10; hazard H-09; DEC-047 for the choices the
prompt leaves open. Every sample value here is synthetic: rule-book samples (UCR West, 4821,
DT4) or invented probes ("Mrs Smith", "DT4 8XX", "943 476 5919"). None is a real patient, name,
NHS number or postcode. The probe values are shaped like patient data on purpose, so the guard
can be seen to catch them.
"""

import re
from typing import Final

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from diucs.domain.codes import Channel, NeedCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.messages import templates as templates_module
from diucs.domain.messages.catalogue import (
    TENANT_TEXT_FIELD_NAMES,
    TENANT_TEXT_FIELDS,
    MessageId,
    tenant_text_fields_for,
)
from diucs.domain.messages.privacy_guard import (
    DEPLOYMENT_TERMS,
    FORBIDDEN_FIELDS,
    find_deployment_terms,
    find_patient_data,
)
from diucs.domain.messages.templates import RenderedMessage, render
from diucs.domain.rules.tenant_settings import check_tenant_text

TEXT, EMAIL, PUSH = Channel.TEXT, Channel.EMAIL, Channel.PUSH

# Channels each id renders on: DEC-034 item 2 (C ids) and DEC-037 item 2 (B, I and K ids).
EXPECTED_CHANNELS: dict[MessageId, frozenset[Channel]] = {
    MessageId.C1: frozenset({TEXT, EMAIL, PUSH}),
    MessageId.C2: frozenset({TEXT, EMAIL, PUSH}),
    MessageId.C3: frozenset({TEXT}),
    MessageId.C4: frozenset({TEXT}),
    MessageId.C5: frozenset({TEXT}),
    MessageId.C6: frozenset({TEXT}),
    MessageId.C7: frozenset({TEXT}),
    MessageId.C8: frozenset({TEXT, EMAIL, PUSH}),
    MessageId.C9: frozenset({TEXT}),
    MessageId.C10: frozenset({TEXT}),
    MessageId.C11: frozenset({TEXT}),
    MessageId.C12: frozenset({TEXT}),
    MessageId.B1: frozenset({TEXT}),
    MessageId.B2: frozenset({EMAIL}),
    MessageId.B3: frozenset({PUSH}),
    MessageId.B4: frozenset({TEXT}),
    MessageId.B5: frozenset({TEXT}),
    MessageId.B6: frozenset({TEXT}),
    MessageId.B7: frozenset({TEXT}),
    MessageId.I1: frozenset({TEXT}),
    MessageId.I2: frozenset({TEXT}),
    MessageId.I3: frozenset({TEXT}),
    MessageId.K1: frozenset({TEXT}),
    MessageId.K2: frozenset({EMAIL, PUSH}),
    MessageId.K3: frozenset({PUSH}),
    MessageId.K4: frozenset({TEXT}),
}

_CAPACITY_LINK = "diucs.example/k3F9a"
_BOOKING_LINK = "diucs.example/b4821"

# One synthetic, non-patient sample per id. Every field the id takes is given, so the sweep
# renders the full template. Shapes must avoid postcodes and NHS-number shapes.
SAMPLE_FIELDS: dict[MessageId, dict[str, object]] = {
    MessageId.C1: {
        "service": "UCR West",
        "value": 3,
        "unit": "referrals in the next 2 hrs",
        "as_of": "08:15",
        "link": _CAPACITY_LINK,
        "reply_by": "10:30",
    },
    MessageId.C2: {
        "service": "UCR West",
        "unit": "referrals",
        "window": "in the next 2 hrs",
        "reply_by": "08:30",
        "link": _CAPACITY_LINK,
    },
    MessageId.C3: {
        "service": "UCR West",
        "value": 4,
        "unit": "referrals",
        "recorded_at": "08:06",
        "next_due": "10:00",
    },
    MessageId.C4: {
        "service": "UCR West",
        "value": 3,
        "unit": "referrals",
        "recorded_at": "14:14",
        "replaced": 4,
    },
    MessageId.C5: {
        "cutoff": "12:30",
        "rejected": 5,
        "service": "UCR West",
        "value": 3,
        "unit": "referrals",
        "reply_by": "13:11",
    },
    MessageId.C6: {"service": "UCR West", "confirm_limit": 2},
    MessageId.C7: {"service": "UCR West", "value": 40, "low": 0, "high": 12},
    MessageId.C8: {"service": "UCR West", "reply_by": "10:30", "link": _CAPACITY_LINK},
    MessageId.C9: {
        "reply_by": "10:30",
        "items": [("A", "UCR West", 3), ("B", "UCR East", 1)],
    },
    MessageId.C10: {
        "updated": [("B", "UCR East", 2)],
        "waiting": [("A", "UCR West")],
    },
    MessageId.C11: {},
    MessageId.C12: {
        "service": "UCR West",
        "value": 3,
        "unit": "referrals in the next 2 hrs",
        "as_of": "22 Oct 17:00",
        "reply_with": "a number",
        "reply_by": "12:35",
    },
    MessageId.B1: {
        "reference": "4821",
        "service": "UCR West",
        "age_band": "80+",
        "need": "frailty",
        "urgency": "within 2 hrs",
        "link": _BOOKING_LINK,
        "reply_by": "14:26",
        "referral_system_name": "SystmOne",
    },
    MessageId.B2: {
        "reference": "4821",
        "service": "UCR West",
        "age_band": "80+",
        "need": "frailty",
        "urgency": "within 2 hrs",
        "link": _BOOKING_LINK,
        "reply_by": "14:26",
        "referral_system_name": "SystmOne",
    },
    MessageId.B3: {"reference": "4821", "service": "UCR West", "reply_by": "14:26"},
    MessageId.B4: {"reference": "4821", "service": "UCR West", "confirmed_at": "14:19"},
    MessageId.B5: {"reference": "4821"},
    MessageId.B6: {"reference": "4821", "cancelled_at": "14:40"},
    MessageId.B7: {"references": ["4821", "4830"]},
    MessageId.I1: {"service": "UCR West", "link": "diucs.example/i/Qx82"},
    MessageId.I2: {"link": "diucs.example/i/Ab41", "system_name": "Dorset urgent care capacity"},
    MessageId.I3: {"service": "UCR West"},
    MessageId.K1: {"code": "482917"},
    MessageId.K2: {"service": "UCR West", "review_by": "30 Oct"},
    MessageId.K3: {"title": "Capacity alert", "body": "UCR West: not updated"},
    MessageId.K4: {"service": "UCR West", "coordination_team_name": "The SPOA shift lead"},
}

# Scalar probe values for the field-level test: a name in title form, as it could reach a field.
PROBE = "Mrs Smith"


def _all_text(rendered: RenderedMessage) -> str:
    """Every piece of text a recipient sees. Joined with newlines so pieces never fuse."""
    return "\n".join(part for part in (rendered.text, rendered.subject, rendered.html) if part)


# --- The guard itself -----------------------------------------------------------------------


def test_a_postcode_with_a_space_is_found() -> None:
    assert find_patient_data("Patient at DT4 8XX") == ["DT4 8XX"]


def test_a_district_alone_is_not_a_postcode() -> None:
    assert find_patient_data("Area DT4 only") == []


@pytest.mark.parametrize("text", ["NHS 943 476 5919", "9434765919", "943-476-5919"])
def test_an_nhs_shaped_number_is_found_in_every_grouping(text: str) -> None:
    assert len(find_patient_data(text)) == 1


@pytest.mark.parametrize("text", ["Call 07700 900123", "REQUEST 4821"])
def test_a_phone_number_and_a_booking_reference_are_not_flagged(text: str) -> None:
    assert find_patient_data(text) == []


def test_a_personal_title_with_a_capitalised_word_is_found() -> None:
    assert find_patient_data("Seen by Mrs Smith") == ["Mrs Smith"]


# --- Boundary cases beyond the prompt's seven tests (DEC-047) -------------------------------


@pytest.mark.parametrize(
    "text", ["dt48xx", "DT48XX", "DT4\t8XX", "DT4  8XX", "QZ9 9ZZ", "dt4 8xx."]
)
def test_postcode_shapes_are_found_whatever_the_case_or_spacing(text: str) -> None:
    assert len(find_patient_data(text)) == 1


@pytest.mark.parametrize(
    "text",
    [
        "DT4",
        "UCR West, 2 referrals",
        "diucs.example/b4821",
        "diucs.example/i/Qx82",
        "14:26 on 2026-10-25",
        "Call 0800 123 4567",
    ],
)
def test_text_without_a_postcode_or_number_shape_is_not_flagged(text: str) -> None:
    assert find_patient_data(text) == []


@pytest.mark.parametrize("text", ["943 476-5919", "9434765919", "x 9434765919 y"])
def test_nhs_shape_is_found_with_mixed_separators_or_beside_words(text: str) -> None:
    assert len(find_patient_data(text)) == 1


@pytest.mark.parametrize("text", ["94347659190", "09434765919", "943 476 59190"])
def test_a_digit_run_longer_than_ten_is_not_an_nhs_shape(text: str) -> None:
    assert find_patient_data(text) == []


@pytest.mark.parametrize("text", ["Dr Jones", "Mr. Brown", "Miss Jones", "MRS Smith", "mrs Smith"])
def test_title_forms_are_found_whatever_the_case_of_the_title(text: str) -> None:
    assert len(find_patient_data(text)) == 1


@pytest.mark.parametrize("text", ["Mrs", "Mrs.", "Mrs smith"])
def test_a_title_needs_a_capitalised_word_after_it(text: str) -> None:
    assert find_patient_data(text) == []


def test_forbidden_fields_are_the_prompt_list() -> None:
    expected = frozenset(
        {
            "name",
            "patient_name",
            "nhs_number",
            "postcode",
            "address",
            "dob",
            "date_of_birth",
            "free_text",
            # TEN-022: a text or email carries no tenant id, slug, subaccount sid or number.
            "tenant",
            "tenant_id",
            "tenant_slug",
            "account_sid",
            "sender_number",
            "from_number",
        }
    )
    assert expected == FORBIDDEN_FIELDS


# --- The sweep over every template ----------------------------------------------------------


def test_every_message_id_has_a_sample() -> None:
    assert set(SAMPLE_FIELDS) == set(MessageId)


def test_every_id_lists_its_channels_in_the_expected_table() -> None:
    assert set(EXPECTED_CHANNELS) == set(MessageId)


@pytest.mark.parametrize("message_id", list(MessageId), ids=lambda m: m.value)
def test_every_channel_renders_without_patient_data(message_id: MessageId) -> None:
    for channel in Channel:
        if channel in EXPECTED_CHANNELS[message_id]:
            rendered = render(message_id, channel, **SAMPLE_FIELDS[message_id])
            assert find_patient_data(_all_text(rendered)) == [], (message_id, channel)
        else:
            with pytest.raises(ValidationFailed):
                render(message_id, channel, **SAMPLE_FIELDS[message_id])


@pytest.mark.parametrize("message_id", list(MessageId), ids=lambda m: m.value)
def test_a_forbidden_field_is_refused_for_every_id(message_id: MessageId) -> None:
    for field in sorted(FORBIDDEN_FIELDS):
        fields = {**SAMPLE_FIELDS[message_id], field: "Mrs Smith"}
        with pytest.raises(ValidationFailed):
            render(message_id, TEXT, **fields)


PROBE_POSTCODE = "DT4 8XX"
PROBE_NHS = "943 476 5919"
PROBES = (PROBE_POSTCODE, PROBE_NHS, PROBE, "943-476-5919")


def _probe_cases(message_id: MessageId, probe: str) -> list[tuple[str, dict[str, object]]]:
    """Each field of the id, in turn, carrying the probe. Lists get the probe in one element."""
    sample = SAMPLE_FIELDS[message_id]
    cases: list[tuple[str, dict[str, object]]] = []
    for field, value in sample.items():
        if isinstance(value, list):
            continue
        cases.append((field, {**sample, field: probe}))
    if message_id is MessageId.C9:
        cases.append(("items", {**sample, "items": [("A", probe, 3), ("B", "UCR East", 1)]}))
    if message_id is MessageId.C10:
        cases.append(("updated", {**sample, "updated": [("B", probe, 2)]}))
        cases.append(("waiting", {**sample, "waiting": [("A", probe)]}))
    if message_id is MessageId.B7:
        cases.append(("references", {**sample, "references": [probe, "4830"]}))
    return cases


@pytest.mark.parametrize("probe", PROBES)
@pytest.mark.parametrize("message_id", list(MessageId), ids=lambda m: m.value)
def test_every_field_refuses_a_patient_shape_in_render(message_id: MessageId, probe: str) -> None:
    """Every field of every id: a postcode, an NHS shape or a name is refused by render itself.

    This is the per-field probe. The synthetic samples prove only that the samples are clean; this
    proves the guard runs on whatever a caller passes.
    """
    channel = min(EXPECTED_CHANNELS[message_id], key=lambda c: c.value)
    for _field, fields in _probe_cases(message_id, probe):
        with pytest.raises(ValidationFailed):
            render(message_id, channel, **fields)


def test_a_postcode_in_service_is_refused_on_c1() -> None:
    fields = {**SAMPLE_FIELDS[MessageId.C1], "service": "DT4 8XX"}
    with pytest.raises(ValidationFailed):
        render(MessageId.C1, TEXT, **fields)


def test_an_nhs_shape_in_the_k3_body_is_refused() -> None:
    fields = {"title": "Capacity alert", "body": "Patient 943 476 5919 at DT4 8XX"}
    with pytest.raises(ValidationFailed):
        render(MessageId.K3, PUSH, **fields)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("need", "John Smith"),
        ("age_band", "John Smith"),
        ("urgency", "John Smith"),
        ("reference", "John Smith"),
    ],
)
def test_a_name_in_a_b1_field_is_refused(field: str, value: str) -> None:
    fields = {**SAMPLE_FIELDS[MessageId.B1], field: value}
    with pytest.raises(ValidationFailed):
        render(MessageId.B1, TEXT, **fields)


@pytest.mark.parametrize("reference", ["482", "0482", "04821", "48210", "REF-2K7Q", "4821 "])
def test_a_reference_must_be_four_digits_without_a_leading_zero(reference: str) -> None:
    fields = {**SAMPLE_FIELDS[MessageId.B5], "reference": reference}
    with pytest.raises(ValidationFailed):
        render(MessageId.B5, TEXT, **fields)


@pytest.mark.parametrize("age_band", ["81", "80 +", "Age 80+", "80+ years"])
def test_an_age_band_must_be_a_rule_book_band(age_band: str) -> None:
    fields = {**SAMPLE_FIELDS[MessageId.B1], "age_band": age_band}
    with pytest.raises(ValidationFailed):
        render(MessageId.B1, TEXT, **fields)


@pytest.mark.parametrize("urgency", ["soon", "Within 2 hrs", "10:30", "within 2 hrs."])
def test_an_urgency_must_be_a_rule_book_wording(urgency: str) -> None:
    fields = {**SAMPLE_FIELDS[MessageId.B1], "urgency": urgency}
    with pytest.raises(ValidationFailed):
        render(MessageId.B1, TEXT, **fields)


@pytest.mark.parametrize(
    "need",
    [
        "jane smith",
        "Jane Smith",
        "fall and frailty",
        "frailty.",
        "frailty 943 476 5919",
        "DT4 8XX",
        "frailty ",
        "",
    ],
)
def test_a_free_text_need_is_refused(need: str) -> None:
    """need is a NeedCategory code (contracts.md, domain-rules section 3). Nothing else passes."""
    fields = {**SAMPLE_FIELDS[MessageId.B1], "need": need}
    with pytest.raises(ValidationFailed):
        render(MessageId.B1, TEXT, **fields)


@pytest.mark.parametrize("need", [member.value for member in NeedCategory])
def test_every_need_category_is_accepted(need: str) -> None:
    fields = {**SAMPLE_FIELDS[MessageId.B1], "need": need}
    assert render(MessageId.B1, TEXT, **fields).text


@pytest.mark.parametrize("urgency", ["within 2 hrs", "today", "planned"])
def test_every_urgency_wording_the_rule_book_names_is_accepted(urgency: str) -> None:
    """Urgency has three members (contracts.md, domain-rules 3); the rule book names all three."""
    fields = {**SAMPLE_FIELDS[MessageId.B1], "urgency": urgency}
    assert render(MessageId.B1, TEXT, **fields).text


def test_b7_refuses_a_malformed_reference_in_the_list() -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.B7, TEXT, references=["4821", "48"])


def test_b7_refuses_a_leading_zero_reference_in_the_list() -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.B7, TEXT, references=["4821", "0482"])


def test_b1_with_a_postcode_is_refused() -> None:
    fields = {**SAMPLE_FIELDS[MessageId.B1], "postcode": "DT4 8XX"}
    with pytest.raises(ValidationFailed):
        render(MessageId.B1, TEXT, **fields)


def test_b7_refuses_an_empty_reference() -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.B7, TEXT, references=["4821", ""])


def test_output_the_guard_flags_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A template that printed a patient shape would be caught here, whatever the caller sent.

    The guard is replaced for this test by one that flags only long text, which is the rendered
    output and not a short field value. The real templates hold no such text (the sweep proves it).
    """
    monkeypatch.setattr(
        templates_module, "find_patient_data", lambda text: ["hit"] if len(text) > 40 else []
    )
    with pytest.raises(ValidationFailed):
        render(MessageId.C1, TEXT, **SAMPLE_FIELDS[MessageId.C1])


@pytest.mark.parametrize("message_id", list(MessageId), ids=lambda m: m.value)
def test_the_field_guard_alone_refuses_every_probe_by_field_name(
    message_id: MessageId, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the output guard disabled, each field must still be refused by its own name.

    This is what stops the field guard being an equivalent mutant: if it were removed, the
    output guard alone would catch the probe only where the template prints the field.
    """
    assert hasattr(templates_module, "_output_has_patient_data"), "output guard seam is missing"
    monkeypatch.setattr(templates_module, "_output_has_patient_data", lambda text: False)
    channel = min(EXPECTED_CHANNELS[message_id], key=lambda c: c.value)
    for probe in PROBES:
        for field, fields in _probe_cases(message_id, probe):
            with pytest.raises(ValidationFailed) as refusal:
                render(message_id, channel, **fields)
            assert refusal.value.field == field, (message_id, probe, field)


# --- Tenant text fields (TEN-022) ------------------------------------------------------------

# The four messages that take a tenant's words, with the field each one takes.
WORDING_CASES: Final = (
    (MessageId.I2, TEXT, "system_name", 60),
    (MessageId.B1, TEXT, "referral_system_name", 40),
    (MessageId.B2, EMAIL, "referral_system_name", 40),
    (MessageId.K4, TEXT, "coordination_team_name", 60),
)
REFUSED_WORDING: Final = (
    "",
    " x",
    "x ",
    "a  b",
    "a/b",
    "http://x",
    "a{b}",
    "<b>x</b>",
    "x\ny",
    "DT4 8XX",
    "943 476 5919",
    "Mrs Smith",
    7,
    None,
    b"Dorset",
)
ACCEPTED_WORDING: Final = ("Dorset urgent care capacity", "EMIS Web", "Tom & Co (north)")


class _TextSubclass(str):
    """A str subclass looks like text but is not exactly a str."""


@pytest.mark.parametrize(("message_id", "channel", "field", "maximum"), WORDING_CASES)
def test_a_tenant_field_refuses_each_bad_value_and_names_the_field(
    message_id: MessageId, channel: Channel, field: str, maximum: int
) -> None:
    bad_values: list[object] = [
        *REFUSED_WORDING,
        _TextSubclass("Dorset"),
        "a" * (maximum + 1),
    ]
    for value in bad_values:
        with pytest.raises(ValidationFailed) as refusal:
            render(message_id, channel, **{**SAMPLE_FIELDS[message_id], field: value})
        assert refusal.value.field == field, (message_id, value)
        if isinstance(value, str) and value:
            assert value not in refusal.value.message, (message_id, value)
            assert value not in str(refusal.value), (message_id, value)


@pytest.mark.parametrize(("message_id", "channel", "field", "maximum"), WORDING_CASES)
def test_a_tenant_field_accepts_plain_wording_up_to_its_maximum(
    message_id: MessageId, channel: Channel, field: str, maximum: int
) -> None:
    for value in (*ACCEPTED_WORDING, "a" * maximum):
        rendered = render(message_id, channel, **{**SAMPLE_FIELDS[message_id], field: value})
        assert value in (rendered.text or ""), (message_id, value)


@given(
    value=st.from_regex(
        r"[A-Za-z0-9][A-Za-z0-9 .,'&()+\-]{0,38}[A-Za-z0-9.)]", fullmatch=True
    ).filter(lambda text: "  " not in text and not find_patient_data(text))
)
def test_any_plain_wording_is_printed_verbatim_unless_the_output_guard_refuses_the_output(
    value: str,
) -> None:
    """Plain wording is accepted by the field check and printed as it is. The one refusal left is
    the output guard (defence after substitution): a name that ends in a title, such as "MR", next
    to the template's capitalised word ("MR. Reply") has a patient-data shape. That refusal is
    fail-closed and names the text field; nothing else may refuse plain wording."""
    assume(len(value) <= 40)
    assert check_tenant_text("referral_system_name", value) == value
    fields = {**SAMPLE_FIELDS[MessageId.B1], "referral_system_name": value}
    try:
        rendered = render(MessageId.B1, TEXT, **fields)
    except ValidationFailed as refusal:
        assert refusal.field == "text", value
        assert find_patient_data(f"in {value}. Reply"), value
        return
    assert f"Referral details follow in {value}. Reply" in rendered.text


ALLOWED_WORDING: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,'&()+-]*")


@given(value=st.text(max_size=50).filter(lambda text: not ALLOWED_WORDING.fullmatch(text)))
def test_any_text_outside_the_wording_alphabet_is_refused_and_nothing_else_is_raised(
    value: str,
) -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.I2, TEXT, **{**SAMPLE_FIELDS[MessageId.I2], "system_name": value})


# Place-name guard (test 10): whole words, case-insensitive, in order.


def test_find_deployment_terms_matches_whole_words_case_insensitively_in_order() -> None:
    assert find_deployment_terms("a Dorset b") == ["Dorset"]
    assert find_deployment_terms("DORSET") == ["DORSET"]
    assert find_deployment_terms("dorset") == ["dorset"]
    assert find_deployment_terms("SPOA.") == ["SPOA"]
    assert find_deployment_terms("EMIS and Dorset") == ["EMIS", "Dorset"]
    assert find_deployment_terms("Dorsetshire") == []
    assert find_deployment_terms("Poolenthal") == []
    assert find_deployment_terms("UCR West") == []
    assert find_deployment_terms("DIUCS") == []


def test_the_deployment_terms_are_the_first_deployments_names() -> None:
    assert DEPLOYMENT_TERMS == (
        "Dorset",
        "SPOA",
        "SystmOne",
        "EMIS",
        "Bournemouth",
        "Poole",
        "Christchurch",
        "Weymouth",
        "Dorchester",
    )


def _template_text(raw: str) -> str:
    """The words of a raw template: markup becomes a space, {placeholders} are removed."""
    without_tags = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\{[a-z_]+\}", "", without_tags)


@pytest.mark.parametrize(
    ("key", "template"),
    list(templates_module._TEMPLATES.items()),
    ids=lambda value: str(value)[:40],
)
def test_no_raw_template_names_a_deployment_term(key: object, template: object) -> None:
    for raw in (
        template.text,
        getattr(template, "subject", None),
        getattr(template, "html", None),
    ):
        if raw is None:
            continue
        words = _template_text(raw)
        assert find_deployment_terms(words) == [], key
        for term in DEPLOYMENT_TERMS:
            assert not re.search(rf"\b{re.escape(term)}\b", words, re.IGNORECASE), (key, term)


# Proper-noun sweep (test 11): a backstop for names that are not in the list.

ALLOWED_CAPITALISED: Final = frozenset({"DIUCS", "REQUEST", "CONFIRMED", "DECLINE"})


def _sentences(raw: str) -> list[str]:
    cleaned = re.sub(r"<[^>]+>", "\n", raw)
    cleaned = re.sub(r"\{[a-z_]+\}", "", cleaned)
    return [part.strip() for part in re.split(r"\. |: |\? |! |\n", cleaned) if part.strip()]


def test_no_template_has_a_capitalised_or_capital_word_outside_the_allowed_set() -> None:
    offenders: list[str] = []
    for key, template in templates_module._TEMPLATES.items():
        for raw in (template.text, template.subject, template.html):
            if raw is None:
                continue
            for sentence in _sentences(raw):
                words = re.findall(r"[A-Za-z]{3,}", sentence)
                for position, word in enumerate(words):
                    if word.isupper() and word not in ALLOWED_CAPITALISED:
                        offenders.append(f"{key}: {word} (all capitals)")
                    elif (
                        position > 0
                        and word[0].isupper()
                        and word not in ALLOWED_CAPITALISED
                        and not word.isupper()
                    ):
                        offenders.append(f"{key}: {word} (mid-sentence capital)")
    assert offenders == []


# Wording parity (test 12): the tenant's words are the only tenant-varying text.

SENTINELS: Final = {
    "system_name": ("Alpha Sys", "Bravo Sys"),
    "referral_system_name": ("Alpha Ref", "Bravo Ref"),
    "coordination_team_name": ("Alpha Team", "Bravo Team"),
}


def test_two_wordings_differ_only_in_the_tenant_words() -> None:
    covered: set[MessageId] = set()
    for message_id, channel, _field, _maximum in WORDING_CASES:
        covered.add(message_id)
        assert tenant_text_fields_for(message_id) == frozenset({_field}), message_id
        fields_a = dict(SAMPLE_FIELDS[message_id])
        fields_b = dict(SAMPLE_FIELDS[message_id])
        for name in tenant_text_fields_for(message_id):
            fields_a[name] = SENTINELS[name][0]
            fields_b[name] = SENTINELS[name][1]
        alpha = _all_text(render(message_id, channel, **fields_a))
        bravo = _all_text(render(message_id, channel, **fields_b))
        for name in tenant_text_fields_for(message_id):
            alpha_word, bravo_word = SENTINELS[name]
            assert alpha_word in alpha and bravo_word in bravo, (message_id, name)
            alpha = alpha.replace(alpha_word, "X")
            bravo = bravo.replace(bravo_word, "X")
        assert alpha == bravo, message_id
    assert covered == {MessageId.I2, MessageId.B1, MessageId.B2, MessageId.K4}


# Guard behaviour after substitution (tests 13 to 16).


def test_the_sample_fields_are_exactly_the_fields_each_id_takes() -> None:
    for message_id in MessageId:
        assert set(SAMPLE_FIELDS[message_id]) == set(templates_module._FIELDS[message_id]), (
            message_id
        )
        assert tenant_text_fields_for(message_id) <= set(SAMPLE_FIELDS[message_id])


def test_defence_in_depth_when_the_wording_check_is_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = {**SAMPLE_FIELDS[MessageId.B1], "referral_system_name": PROBE_POSTCODE}
    with pytest.raises(ValidationFailed):
        render(MessageId.B1, TEXT, **probe)
    monkeypatch.setattr(templates_module, "check_tenant_text", lambda field, value: value)
    with pytest.raises(ValidationFailed):
        render(MessageId.B1, TEXT, **probe)
    monkeypatch.setattr(templates_module, "_refuse_patient_data", lambda fields: None)
    with pytest.raises(ValidationFailed) as refusal:
        render(MessageId.B1, TEXT, **probe)
    assert refusal.value.field == "text"


def test_no_rendered_output_carries_a_tenant_id_or_slug() -> None:
    for message_id in MessageId:
        for channel in EXPECTED_CHANNELS[message_id]:
            rendered = render(message_id, channel, **SAMPLE_FIELDS[message_id])
            assert "acme-icb" not in _all_text(rendered), (message_id, channel)


@pytest.mark.parametrize("message_id", list(MessageId), ids=lambda m: m.value)
def test_every_forbidden_tenant_field_is_refused_by_render(message_id: MessageId) -> None:
    for field in (
        "tenant",
        "tenant_id",
        "tenant_slug",
        "account_sid",
        "sender_number",
        "from_number",
    ):
        with pytest.raises(ValidationFailed):
            render(message_id, TEXT, **{**SAMPLE_FIELDS[message_id], field: "acme-icb"})


def test_tenant_text_fields_for_maps_the_four_ids_and_nothing_else() -> None:
    assert tenant_text_fields_for(MessageId.I2) == frozenset({"system_name"})
    assert tenant_text_fields_for(MessageId.B1) == frozenset({"referral_system_name"})
    assert tenant_text_fields_for(MessageId.B2) == frozenset({"referral_system_name"})
    assert tenant_text_fields_for(MessageId.K4) == frozenset({"coordination_team_name"})
    others = [
        m for m in MessageId if m not in {MessageId.I2, MessageId.B1, MessageId.B2, MessageId.K4}
    ]
    assert len(others) == len(MessageId) - 4
    assert all(tenant_text_fields_for(m) == frozenset() for m in others)


def test_the_mapping_keys_and_names_and_the_render_fields_agree() -> None:
    assert set(TENANT_TEXT_FIELDS) <= set(MessageId)
    for message_id, names in TENANT_TEXT_FIELDS.items():
        assert names <= TENANT_TEXT_FIELD_NAMES
        assert names <= templates_module._FIELDS[message_id]
    assert (
        frozenset({"system_name", "referral_system_name", "coordination_team_name"})
        == TENANT_TEXT_FIELD_NAMES
    )
