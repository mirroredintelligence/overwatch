"""The Twilio signature (I07): base64(HMAC-SHA1(token, url + each POST name and value sorted by
name)). The expected values are computed in the test with hmac and hashlib, not by the code under
test."""

import base64
import hashlib
import hmac

from hypothesis import given
from hypothesis import strategies as st

from diucs.adapters.inbound.sms_webhook.routes import twilio_signature

URL = "https://diucs.example/webhooks/sms/twilio"
TOKEN = "i07-test-token"
PARAMS = {
    "To": "+447700900001",
    "From": "+447700900123",
    "Body": "4",
    "MessageSid": "SM1",
    "AccountSid": "AC1",
}


def _independent(url: str, params: dict[str, str], token: bytes) -> str:
    data = url + "".join(name + params[name] for name in sorted(params))
    return base64.b64encode(hmac.new(token, data.encode("utf-8"), hashlib.sha1).digest()).decode()


def test_it_matches_a_value_computed_independently_with_hmac_and_hashlib() -> None:
    expected = _independent(URL, PARAMS, TOKEN.encode())
    assert twilio_signature(URL, PARAMS, TOKEN) == expected


def test_it_matches_a_literal_computed_once_with_openssl() -> None:
    # printf '%s' 'https://diucs.example/webhooks/sms/twilioAccountSidAC1Body4From+447700900123'\
    #   'MessageSidSM1To+447700900001' | openssl dgst -sha1 -hmac i07-test-token -binary | base64
    assert twilio_signature(URL, PARAMS, TOKEN) == "JRXb5JswbCZN3KZyZZtf+OZVo6Y="


def test_the_order_the_parameters_arrive_in_does_not_matter() -> None:
    reordered = dict(reversed(list(PARAMS.items())))
    assert twilio_signature(URL, reordered, TOKEN) == twilio_signature(URL, PARAMS, TOKEN)


def test_names_sort_by_code_point_so_an_upper_case_name_comes_before_a_lower_case_one() -> None:
    params = {"b": "2", "B": "1", "a": "3"}
    assert twilio_signature(URL, params, TOKEN) == _independent(URL, params, TOKEN.encode())
    # "B" < "a" < "b": the data is url + B1 + a3 + b2, not a case-insensitive order.
    other_order = _independent(URL, {"a": "3", "b": "2", "B": "1"}, TOKEN.encode())
    assert twilio_signature(URL, params, TOKEN) == other_order


def test_an_empty_value_is_part_of_the_signed_text_and_a_missing_name_is_not() -> None:
    with_empty = {**PARAMS, "Extra": ""}
    assert twilio_signature(URL, with_empty, TOKEN) == _independent(URL, with_empty, TOKEN.encode())
    assert twilio_signature(URL, with_empty, TOKEN) != twilio_signature(URL, PARAMS, TOKEN)


def test_a_non_ascii_value_is_signed_as_utf8() -> None:
    params = {**PARAMS, "Body": "café ✓ \U0001f600"}
    assert twilio_signature(URL, params, TOKEN) == _independent(URL, params, TOKEN.encode())


def test_the_url_and_the_token_both_change_the_signature() -> None:
    base = twilio_signature(URL, PARAMS, TOKEN)
    assert twilio_signature(URL + "/status", PARAMS, TOKEN) != base
    assert twilio_signature(URL + "?a=1", PARAMS, TOKEN) != base
    assert twilio_signature(URL, PARAMS, TOKEN + "x") != base


def test_a_token_as_text_and_as_bytes_give_the_same_signature() -> None:
    assert twilio_signature(URL, PARAMS, TOKEN) == twilio_signature(URL, PARAMS, TOKEN.encode())


_text = st.text(max_size=30)


@given(
    params=st.dictionaries(_text, _text, max_size=8),
    url=_text,
    token=st.binary(min_size=1, max_size=40),
)
def test_for_any_input_it_equals_the_independent_computation(
    params: dict[str, str], url: str, token: bytes
) -> None:
    assert twilio_signature(url, params, token) == _independent(url, params, token)


@given(
    params=st.dictionaries(_text, _text, min_size=1, max_size=8),
    extra=_text,
    data=st.data(),
)
def test_changing_any_value_changes_the_signature(
    params: dict[str, str], extra: str, data: st.DataObject
) -> None:
    name = data.draw(st.sampled_from(sorted(params)))
    changed = {**params, name: params[name] + "x" + extra}
    assert twilio_signature(URL, changed, TOKEN) != twilio_signature(URL, params, TOKEN)
