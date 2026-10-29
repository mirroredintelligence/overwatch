"""Secret references and the shape of the keys a directory lookup takes (TEN-007).

A reference names a secret and is never the secret. It is `<kind>/<tenant>/<name>`, so a number
that points at another tenant's token is refused, and the refusal never repeats the value. A key
that is not the shape it names (a number that is not E.164, a host with a port) is not looked up.
"""

import dataclasses

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.application.ports.outbound.tenants import (
    TenantLine,
    check_secret_ref,
    normalise_account_sid,
    normalise_directory_id,
    normalise_e164,
    normalise_host,
    secret_ref,
    twilio_token_ref,
)
from diucs.domain.errors import ValidationFailed
from tests.support.tenant_samples import make_tenant

TENANT = "example-icb"
OTHER = "other-trust"
SID = "AC" + "1" * 32


# Secret references


def test_a_reference_is_the_kind_the_tenant_and_the_name() -> None:
    assert secret_ref("twilio", TENANT, "auth-token") == "twilio/example-icb/auth-token"
    assert twilio_token_ref(TENANT) == "twilio/example-icb/auth-token"
    assert secret_ref("email", OTHER, "smtp-password.v2") == "email/other-trust/smtp-password.v2"


@pytest.mark.parametrize("tenant", ["platform", "net-abcd1234", "X", "a b", "", "has/slash"])
def test_no_reference_is_built_for_a_value_that_is_not_a_tenant_id(tenant: str) -> None:
    with pytest.raises(ValidationFailed):
        twilio_token_ref(tenant)


@pytest.mark.parametrize(
    ("kind", "name"),
    [
        ("Twilio", "auth-token"),
        ("twilio", "Auth"),
        ("twilio", ""),
        ("", "auth-token"),
        ("twi/lio", "auth-token"),
        ("twilio", "a/b"),
        ("twilio", "a b"),
        ("twilio", ".hidden"),
        ("twilio", "x" * 65),
        ("t" * 33, "auth-token"),
    ],
)
def test_a_kind_or_name_outside_the_pattern_builds_no_reference(kind: str, name: str) -> None:
    with pytest.raises(ValidationFailed):
        secret_ref(kind, TENANT, name)


def test_a_reference_of_the_tenant_is_accepted_as_it_is() -> None:
    assert check_secret_ref("twilio/example-icb/auth-token", TENANT) == (
        "twilio/example-icb/auth-token"
    )


@pytest.mark.parametrize(
    "value",
    [
        "twilio/other-trust/auth-token",  # another tenant's secret
        "twilio/example-icb",  # two parts
        "twilio/example-icb/auth/token",  # four parts
        "/twilio/example-icb/auth-token",
        "twilio/example-icb/auth-token/",
        "twilio//auth-token",
        "twilio/example-icb/../auth-token",
        "Twilio/example-icb/auth-token",
        "twilio/example-icb/auth token",
        "twilio/example-icb/auth-token\n",
        "link-token",  # a platform secret is not a tenant's
        "",
        "twilio/example-icb/" + "x" * 65,
        b"twilio/example-icb/auth-token",
        None,
        7,
    ],
)
def test_a_value_that_is_not_the_reference_of_this_tenant_is_refused(value: object) -> None:
    with pytest.raises(ValidationFailed):
        check_secret_ref(value, TENANT)


def test_a_refusal_never_repeats_the_value() -> None:
    value = "twilio/other-trust/auth-token"
    with pytest.raises(ValidationFailed) as raised:
        check_secret_ref(value, TENANT)
    assert value not in str(raised.value)
    assert OTHER not in str(raised.value)


@given(st.text(max_size=80))
def test_a_reference_is_accepted_only_when_it_is_the_tenants_and_a_refusal_is_one_fixed_text(
    text: str,
) -> None:
    try:
        accepted = check_secret_ref(text, TENANT)
    except ValidationFailed as refusal:
        assert str(refusal) == "secret_ref: is not a valid secret reference"
    else:
        assert accepted == text
        assert text.split("/")[1] == TENANT
        assert len(text.split("/")) == 3


# The shape of a lookup key


@pytest.mark.parametrize("value", ["+447700900123", "+14155550100", "+3225550123"])
def test_an_e164_number_is_kept_as_it_is(value: str) -> None:
    assert normalise_e164(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "07700 900123",  # national, not E.164
        "+44 7700 900123",  # spaces
        "447700900123",  # no plus
        "+0447700900123",  # country code cannot start with 0
        "+4477",  # too short
        "+4477009001230000",  # too long (16 digits)
        "+44770090012a",
        "+447700900123\n",
        "",
        None,
        447700900123,
        b"+447700900123",
    ],
)
def test_a_number_that_is_not_e164_is_not_looked_up(value: object) -> None:
    assert normalise_e164(value) is None


def test_an_account_sid_is_ac_and_thirty_two_hex_digits() -> None:
    assert normalise_account_sid(SID) == SID
    assert normalise_account_sid("AC" + "f" * 32) == "AC" + "f" * 32


@pytest.mark.parametrize(
    "value",
    [
        "AC" + "1" * 31,
        "AC" + "1" * 33,
        "AC" + "g" * 32,
        "ac" + "1" * 32,
        "SK" + "1" * 32,
        "AC 1",
        "",
        None,
        12,
        SID + "\n",
    ],
)
def test_a_value_that_is_not_an_account_sid_is_not_looked_up(value: object) -> None:
    assert normalise_account_sid(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("acme.example.org", "acme.example.org"),
        ("Acme.Example.ORG", "acme.example.org"),
        ("acme.example.org.", "acme.example.org"),
        ("a-b.c1.example", "a-b.c1.example"),
        ("localhost", "localhost"),
    ],
)
def test_a_host_is_lower_case_and_without_the_final_dot(value: str, expected: str) -> None:
    assert normalise_host(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "acme.example.org:8443",  # the port is the caller's to remove
        "acme_site.example.org",
        "-acme.example.org",
        "acme-.example.org",
        "acme..example.org",
        ".acme.example.org",
        "acme example.org",
        "https://acme.example.org",
        "acme.example.org/",
        "ünï.example.org",
        "\u212aacme.example.org",  # the Kelvin sign lower-cases to a plain k
        "a" * 64 + ".example.org",  # a label over 63
        ("a" * 60 + ".") * 5 + "org",  # over 253 in all
        "",
        ".",
        None,
        5,
    ],
)
def test_a_value_that_is_not_a_host_name_is_not_looked_up(value: object) -> None:
    assert normalise_host(value) is None


def test_a_directory_id_is_a_guid_in_lower_case() -> None:
    guid = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"
    assert normalise_directory_id(guid) == guid
    assert normalise_directory_id(guid.upper()) == guid


@pytest.mark.parametrize(
    "value",
    [
        "0f5a7c1e3b2d4c6a9e8f1a2b3c4d5e6f",
        "{0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f}",
        "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6",
        "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6g",
        "common",
        "",
        None,
        1,
    ],
)
def test_a_value_that_is_not_a_guid_is_not_looked_up(value: object) -> None:
    assert normalise_directory_id(value) is None


@given(st.text(max_size=60))
def test_no_normaliser_raises_for_any_text(text: str) -> None:
    for normalise in (
        normalise_e164,
        normalise_account_sid,
        normalise_host,
        normalise_directory_id,
    ):
        result = normalise(text)
        assert result is None or isinstance(result, str)


# The line


def test_a_line_holds_the_reference_and_has_no_field_for_a_secret() -> None:
    line = TenantLine(
        tenant=make_tenant(id=TENANT),
        number="+447700900123",
        account_sid=SID,
        secret_ref=twilio_token_ref(TENANT),
    )
    assert {field.name for field in dataclasses.fields(line)} == {
        "tenant",
        "number",
        "account_sid",
        "secret_ref",
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        line.number = "+447700900124"  # type: ignore[misc]
