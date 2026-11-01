"""The admin-consent rules (DEC-1316): the state, the address hash and mask, the consent link, and
what an invite is at a given time. Pure: no store, no clock."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from overwatch.domain.errors import ValidationFailed
from overwatch.domain.rules.admin_consent import (
    INVITE_VALID_FOR,
    AdminConsentInvite,
    EffectiveStatus,
    InviteStatus,
    check_email,
    consent_url,
    effective_status,
    hash_email,
    hash_state,
    mask_email,
    new_state,
    tenant_hint,
)

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
DIRECTORY = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"
CLIENT = "7fb43bde-6a6d-4aed-9cac-9118de48ab52"
RETURN = "https://overwatch.mirroredintelligence.com/admin-consent/return"
SECRET = b"test-only-secret-0123456789abcdef0123"


def _invite(**changes: object) -> AdminConsentInvite:
    fields: dict[str, object] = {
        "invite_id": "inv-1",
        "directory_id": DIRECTORY,
        "email_hash": "a" * 64,
        "email_masked": "a***@example.org",
        "state_hash": "b" * 64,
        "status": InviteStatus.PENDING,
        "created_at": NOW,
        "expires_at": NOW + INVITE_VALID_FOR,
    }
    fields.update(changes)
    return AdminConsentInvite(**fields)  # type: ignore[arg-type]


def test_an_invite_is_valid_for_seven_days() -> None:
    assert timedelta(days=7) == INVITE_VALID_FOR


def test_a_state_names_its_tenant_and_carries_256_random_bits() -> None:
    state = new_state("new-org")
    tenant, _, random = state.partition(".")
    assert tenant == "new-org" and len(random) == 43
    assert tenant_hint(state) == "new-org"
    assert new_state("new-org") != state


@pytest.mark.parametrize(
    "text",
    ["", "no-dot", "new-org.short", "NEW.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", None, 5],
)
def test_text_that_is_not_a_state_names_no_tenant(text: object) -> None:
    assert tenant_hint(text) is None


def test_the_state_is_stored_as_a_hash_that_is_not_the_state() -> None:
    state = new_state("new-org")
    digest = hash_state(state)
    assert len(digest) == 64 and state not in digest and digest == hash_state(state)
    assert hash_state(state + "x") != digest


def test_the_address_is_normalised_and_hashed_under_the_secret() -> None:
    first = hash_email("Admin@Example.org ", SECRET)
    assert first == hash_email("admin@example.org", SECRET)
    assert first != hash_email("admin@example.org", SECRET + b"x")
    assert "admin" not in first


@pytest.mark.parametrize("bad", ["", "no-at", "a@", "@b.org", "a b@c.org", "a..b@c.org", None, 3])
def test_a_value_that_is_not_one_address_is_refused_without_echoing_it(bad: object) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_email(bad)
    assert str(bad) not in str(refused.value) or bad in ("", None)


def test_the_mask_keeps_one_letter_and_the_domain() -> None:
    assert mask_email("Jane.Doe@Example.org") == "j***@example.org"


def test_the_consent_link_is_microsofts_adminconsent_for_that_directory() -> None:
    state = new_state("new-org")
    url = urlparse(consent_url(DIRECTORY, CLIENT, RETURN, state))
    assert url.scheme == "https" and url.netloc == "login.microsoftonline.com"
    assert url.path == f"/{DIRECTORY}/adminconsent"
    query = parse_qs(url.query)
    assert query == {"client_id": [CLIENT], "redirect_uri": [RETURN], "state": [state]}


def test_a_directory_that_is_not_a_guid_makes_no_link() -> None:
    with pytest.raises(ValidationFailed):
        consent_url("../common", CLIENT, RETURN, new_state("new-org"))


def test_a_pending_invite_expires_on_its_time_without_a_write() -> None:
    invite = _invite()
    assert effective_status(invite, NOW) is EffectiveStatus.PENDING
    assert effective_status(invite, invite.expires_at - timedelta(seconds=1)) is (
        EffectiveStatus.PENDING
    )
    assert effective_status(invite, invite.expires_at) is EffectiveStatus.EXPIRED


def test_consented_and_revoked_do_not_expire() -> None:
    late = NOW + timedelta(days=30)
    assert (
        effective_status(_invite(status=InviteStatus.CONSENTED, consented_at=NOW), late)
        is EffectiveStatus.CONSENTED
    )
    assert (
        effective_status(_invite(status=InviteStatus.REVOKED, revoked_at=NOW), late)
        is EffectiveStatus.REVOKED
    )


def test_an_invite_that_contradicts_itself_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        _invite(status=InviteStatus.CONSENTED)  # consented with no time
    with pytest.raises(ValidationFailed):
        _invite(consented_at=NOW)  # a time while pending
    with pytest.raises(ValidationFailed):
        _invite(email_hash="not-a-hash")
    with pytest.raises(ValidationFailed):
        _invite(expires_at=NOW)
    with pytest.raises(ValidationFailed):
        _invite(created_at=datetime(2026, 11, 1, 9, 0))
