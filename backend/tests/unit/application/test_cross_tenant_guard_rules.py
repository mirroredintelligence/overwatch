"""The pure rules of the cross-tenant support guard (TEN-084, DEC-528 to DEC-531, DEC-134 item 5,
DEC-136 item 6, audit F 4.2).

Deny by default. Access to one tenant by a platform support person needs, together: a principal
that came from the operator directory (an operator token with the `support` role, never a tenant
token and never the platform operator, who has no data access); a code the tenant's own
administrator issued; one tenant; and an hour. These rules say who may issue, who may be a
principal, how long an access lasts and when a held access still stands. Nothing here does I/O or
reads a clock: every instant is an argument.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from diucs.application.actor import Actor
from diucs.application.cross_tenant_guard import (
    ACCESS_VALID_FOR,
    CODE_VALID_FOR,
    CrossTenantDenied,
    Elevation,
    Grant,
    PlatformPrincipal,
    access_expiry,
    check_action,
    check_issuer,
    decode_elevation,
    decode_grant,
    denial,
    encode_elevation,
    encode_grant,
)
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.bff_token import OperatorClaims

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
REF = "ref-support-person-0123456789"
OTHER_REF = "ref-another-support-9876543210"
HASH = "a" * 64


def actor(role: Role, tenant: str = "tenant-a", practitioner: str | None = "admin-1") -> Actor:
    return Actor(
        role=role,
        practitioner_id=practitioner,
        device_id=None,
        channel="api",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def elevation(**changes: object) -> Elevation:
    base = Elevation(
        access_id="access-1",
        tenant_id="tenant-a",
        principal_ref=REF,
        opened_at=NOW,
        expires_at=NOW + ACCESS_VALID_FOR,
        grant_hash=HASH,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


PRINCIPAL = PlatformPrincipal(account_ref=REF, role=Role.SUPPORT)


def test_an_access_lasts_one_hour_and_a_code_four() -> None:
    assert timedelta(hours=1) == ACCESS_VALID_FOR
    assert timedelta(hours=4) == CODE_VALID_FOR


# ----------------------------------------------------------------------- the principal


def test_a_principal_is_made_from_the_claims_of_an_operator_token_of_a_support_person() -> None:
    claims = OperatorClaims(sub=REF, role=Role.SUPPORT, expires_at=NOW + timedelta(hours=1))

    assert PlatformPrincipal.from_claims(claims) == PRINCIPAL


def test_the_platform_operator_has_no_data_access_and_is_no_principal() -> None:
    claims = OperatorClaims(sub=REF, role=Role.PLATFORM_OPERATOR, expires_at=NOW)

    with pytest.raises(CrossTenantDenied):
        PlatformPrincipal.from_claims(claims)


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.SUPPORT])
def test_no_role_but_support_is_a_principal(role: Role) -> None:
    with pytest.raises(CrossTenantDenied):
        PlatformPrincipal(account_ref=REF, role=role)


@pytest.mark.parametrize("ref", ["", "short", "has space in it 123", "a" * 129, None, 7])
def test_a_principal_needs_an_account_reference_of_the_shape_the_records_take(ref: object) -> None:
    with pytest.raises(CrossTenantDenied):
        PlatformPrincipal(account_ref=ref, role=Role.SUPPORT)  # type: ignore[arg-type]


def test_a_tenant_token_actor_is_not_a_principal() -> None:
    with pytest.raises(CrossTenantDenied):
        PlatformPrincipal.from_claims(actor(Role.SUPPORT))  # type: ignore[arg-type]


# ----------------------------------------------------------------------- who may issue a code


def test_the_tenants_administrator_may_issue() -> None:
    check_issuer(actor(Role.TENANT_ADMIN))


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.TENANT_ADMIN])
def test_no_other_role_may_issue(role: Role) -> None:
    with pytest.raises(CrossTenantDenied):
        check_issuer(actor(role))


def test_an_administrator_with_no_person_may_not_issue() -> None:
    with pytest.raises(CrossTenantDenied):
        check_issuer(actor(Role.TENANT_ADMIN, practitioner=None))


def test_something_that_is_not_an_actor_may_not_issue() -> None:
    with pytest.raises(CrossTenantDenied):
        check_issuer(object())  # type: ignore[arg-type]


# ----------------------------------------------------------------------- how long


def test_an_access_lasts_an_hour_from_the_moment_it_opens() -> None:
    assert access_expiry(NOW, NOW + CODE_VALID_FOR) == NOW + timedelta(hours=1)


def test_an_access_never_outlasts_the_code_that_opened_it() -> None:
    late = NOW + timedelta(hours=3, minutes=30)

    assert access_expiry(late, NOW + CODE_VALID_FOR) == NOW + timedelta(hours=4)


def test_an_access_is_never_longer_than_an_hour_whatever_the_code() -> None:
    assert access_expiry(NOW, NOW + timedelta(days=30)) == NOW + timedelta(hours=1)


def test_an_access_is_whole_seconds_in_utc() -> None:
    moment = datetime(2026, 10, 30, 9, 0, 0, 500_000, tzinfo=UTC)

    assert access_expiry(moment, NOW + CODE_VALID_FOR).microsecond == 0


def test_a_naive_instant_has_no_expiry() -> None:
    with pytest.raises(ValidationFailed):
        access_expiry(datetime(2026, 10, 30, 9, 0), NOW + CODE_VALID_FOR)
    with pytest.raises(ValidationFailed):
        access_expiry(NOW, datetime(2026, 10, 30, 13, 0))


# ----------------------------------------------------------------------- deny by default


def test_an_access_stands_for_its_principal_on_its_tenant_until_it_expires() -> None:
    assert denial(PRINCIPAL, elevation(), "tenant-a", NOW + timedelta(minutes=59)) is None


def test_an_access_ends_at_the_instant_it_names() -> None:
    held = elevation()

    assert denial(PRINCIPAL, held, "tenant-a", held.expires_at - timedelta(seconds=1)) is None
    assert denial(PRINCIPAL, held, "tenant-a", held.expires_at) == "expired"
    assert denial(PRINCIPAL, held, "tenant-a", held.expires_at + timedelta(seconds=1)) == "expired"


def test_no_access_is_a_denial() -> None:
    assert denial(PRINCIPAL, None, "tenant-a", NOW) == "no-access"


def test_an_access_to_one_tenant_is_not_an_access_to_another() -> None:
    assert denial(PRINCIPAL, elevation(), "tenant-b", NOW) == "other-tenant"


def test_an_access_of_one_person_is_not_another_persons() -> None:
    other = PlatformPrincipal(account_ref=OTHER_REF, role=Role.SUPPORT)

    assert denial(other, elevation(), "tenant-a", NOW) == "other-principal"


@pytest.mark.parametrize("bad", [None, "support", object()])
def test_a_principal_that_is_not_one_is_denied(bad: object) -> None:
    assert denial(bad, elevation(), "tenant-a", NOW) == "no-principal"  # type: ignore[arg-type]


def test_an_access_that_is_not_an_elevation_is_denied() -> None:
    assert denial(PRINCIPAL, object(), "tenant-a", NOW) == "no-access"  # type: ignore[arg-type]


def test_a_naive_instant_is_a_denial_and_never_an_allow() -> None:
    assert denial(PRINCIPAL, elevation(), "tenant-a", datetime(2026, 10, 30, 9, 30)) == "expired"


@pytest.mark.parametrize("tenant", [None, "", 7, "net-region-1", "platform", "Tenant-A"])
def test_a_tenant_that_is_not_a_tenant_id_is_denied(tenant: object) -> None:
    assert denial(PRINCIPAL, elevation(), tenant, NOW) == "other-tenant"  # type: ignore[arg-type]


# ----------------------------------------------------------------------- an action word


@pytest.mark.parametrize("word", ["read-session", "list", "a", "read-trace-1"])
def test_an_action_is_a_short_lower_case_word(word: str) -> None:
    assert check_action(word) == word


@pytest.mark.parametrize(
    "word", ["", "Read", "read session", "x" * 41, "read/session", "1read", None, 7, "read\n"]
)
def test_anything_else_is_not_an_action(word: object) -> None:
    with pytest.raises(ValidationFailed):
        check_action(word)  # type: ignore[arg-type]


# ----------------------------------------------------------------------- what the cache holds


def grant() -> Grant:
    return Grant(
        code_hash=HASH,
        issued_by_ref="admin-1",
        issued_at=NOW,
        expires_at=NOW + CODE_VALID_FOR,
    )


def test_a_grant_and_an_elevation_come_back_unchanged() -> None:
    assert decode_grant(encode_grant(grant())) == grant()
    assert decode_elevation(encode_elevation(elevation())) == elevation()


def test_a_grant_holds_a_hash_and_never_a_code() -> None:
    text = encode_grant(grant())

    assert HASH in text
    assert "XXXX" not in text


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "not json",
        "[]",
        "{}",
        '{"v": 2}',
        encode_grant(grant()).replace(HASH, "not-a-hash"),
        encode_grant(grant()).replace("2026-10-30T09:00:00Z", "2026-10-30 09:00:00"),
        encode_grant(grant()).replace('"v":1', '"v":1,"extra":1'),
    ],
)
def test_a_damaged_grant_is_none(text: object) -> None:
    assert decode_grant(text) is None  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t.replace("access-1", ""),
        lambda t: t.replace("tenant-a", "net-region-1"),
        lambda t: t.replace(REF, "x"),
        lambda t: t.replace('"v":1', '"v":1,"extra":1'),
        lambda t: t.replace("2026-10-30T10:00:00Z", "2026-10-30T08:00:00Z"),  # ends before it opens
        lambda t: t.replace("2026-10-30T10:00:00Z", "2026-10-30T11:00:01Z"),  # over an hour
        lambda t: t.replace("2026-10-30T10:00:00Z", "tomorrow"),
    ],
)
def test_a_damaged_elevation_is_none(mutate: object) -> None:
    text = encode_elevation(elevation())

    assert decode_elevation(mutate(text)) is None  # type: ignore[operator]


@pytest.mark.parametrize("text", [None, "", "not json", "[]", "{}", 7])
def test_text_that_is_not_an_elevation_is_none(text: object) -> None:
    assert decode_elevation(text) is None  # type: ignore[arg-type]


def test_an_elevation_cannot_be_built_longer_than_an_hour_or_ending_before_it_opens() -> None:
    with pytest.raises(ValidationFailed):
        elevation(expires_at=NOW + ACCESS_VALID_FOR + timedelta(seconds=1))
    with pytest.raises(ValidationFailed):
        elevation(expires_at=NOW)


def test_an_elevation_shows_no_reference_and_no_hash_in_a_repr() -> None:
    shown = repr(elevation())

    assert REF not in shown and HASH not in shown
