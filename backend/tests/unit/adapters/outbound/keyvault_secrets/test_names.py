"""The one mapping from a secret reference to a Key Vault name (DEC-1304 item 2).

`<kind>/<tenant>/<name>` becomes `<kind>--<tenant>--<name>`. Only lower-case letters, digits, single
hyphens and `/` between non-empty parts are accepted, so the mapping is one-to-one. A refused name
gives None, and the store never asks the vault for it.
"""

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.adapters.outbound.keyvault_secrets import vault_secret_name
from diucs.application.ports.outbound.tenants import secret_ref, twilio_token_ref
from diucs.domain.rules.tenant_keys import PER_TENANT_KEY_NAMES

PART = st.from_regex(r"[a-z0-9]+(-[a-z0-9]+)*", fullmatch=True)
VALID_NAMES = st.lists(PART, min_size=1, max_size=4).map("/".join)
VAULT_CHARSET = re.compile(r"[a-z0-9-]{1,127}")


def test_a_platform_secret_keeps_its_name() -> None:
    assert vault_secret_name("bff-jwt") == "bff-jwt"
    assert vault_secret_name("webpush-vapid-private-key") == "webpush-vapid-private-key"


def test_a_slash_becomes_two_hyphens() -> None:
    assert vault_secret_name("twilio/tenant-a/auth-token") == "twilio--tenant-a--auth-token"


def test_the_conventional_references_map() -> None:
    assert vault_secret_name(twilio_token_ref("tenant-a")) == "twilio--tenant-a--auth-token"
    assert vault_secret_name(secret_ref("email", "tenant-a", "smtp.login")) is None  # a dot


@pytest.mark.parametrize("name", sorted(PER_TENANT_KEY_NAMES | {"edge-origin", "session-secret"}))
def test_every_platform_name_of_the_code_is_accepted_unchanged(name: str) -> None:
    assert vault_secret_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "/",
        "a/",
        "/a",
        "a//b",
        "a--b",
        "a/b--c",
        "-a",
        "a-",
        "a/-b",
        "a-/b",
        "A",
        "twilio/Tenant-A/token",
        "a_b",
        "a.b",
        "a b",
        "a\nb",
        "a\n",
        "é",
        "a/b/",
        "a\x00",
        "../a",
    ],
)
def test_a_name_outside_the_rule_is_refused(name: str) -> None:
    assert vault_secret_name(name) is None


@pytest.mark.parametrize("value", [None, b"bff-jwt", 7, ["a"]])
def test_a_name_that_is_not_text_is_refused(value: object) -> None:
    assert vault_secret_name(value) is None  # type: ignore[arg-type]


def test_a_mapped_name_of_127_characters_is_the_longest() -> None:
    assert vault_secret_name("a" * 127) == "a" * 127
    assert vault_secret_name("a" * 128) is None
    # The slash grows by one character: 63 + 1 + 63 maps to 128.
    assert vault_secret_name("a" * 62 + "/" + "b" * 63) == "a" * 62 + "--" + "b" * 63
    assert vault_secret_name("a" * 63 + "/" + "b" * 63) is None


def test_a_tenant_id_the_platform_accepts_may_have_no_vault_name() -> None:
    # H-831: a tenant id is `[a-z0-9][a-z0-9-]{1,30}`, which allows `--` and a trailing hyphen. Such
    # an id has no vault name, so its secrets cannot be read: refused, never a collision.
    assert vault_secret_name(secret_ref("twilio", "a--b", "auth-token")) is None
    assert vault_secret_name(secret_ref("twilio", "ab-", "auth-token")) is None


@given(VALID_NAMES)
def test_a_valid_name_maps_into_the_vault_alphabet_and_back(name: str) -> None:
    mapped = vault_secret_name(name)
    if mapped is None:
        assert len(name.replace("/", "--")) > 127
        return
    assert VAULT_CHARSET.fullmatch(mapped)
    assert mapped.replace("--", "/") == name


@given(VALID_NAMES, VALID_NAMES)
def test_the_mapping_is_injective_over_valid_names(first: str, second: str) -> None:
    one, two = vault_secret_name(first), vault_secret_name(second)
    if one is not None and one == two:
        assert first == second


def test_the_collision_a_single_hyphen_would_make_is_two_names() -> None:
    first = vault_secret_name("twilio/a-b/c")
    second = vault_secret_name("twilio/a/b-c")

    assert first == "twilio--a-b--c"
    assert second == "twilio--a--b-c"
    assert first != second


@given(st.text(max_size=200))
def test_no_text_raises_and_an_accepted_one_is_in_the_alphabet(text: str) -> None:
    mapped = vault_secret_name(text)
    assert mapped is None or VAULT_CHARSET.fullmatch(mapped)
