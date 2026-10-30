"""The identity verifier port's value and its fake (TEN-043, DEC-522).

The verifier is an external provider (Microsoft Entra ID): the real adapter checks the signature,
issuer, audience, expiry and nonce of the ID token and is built against a real directory at deploy.
What the back end relies on is the port: a `VerifiedIdentity` that is exactly a directory id, an
object id and the groups and app roles the token carried, or `IdentityRejected` with a fixed
message. The fake accepts only the credentials a test registers, for the audience it registered
them for, and never shows a credential, an id or a group in a repr, a message or a record.
"""

import pytest

from diucs.adapters.testing.fake_identity_verifier import FakeIdentityVerifier
from diucs.application.ports.outbound.identity_verifier import (
    IDENTITY_REJECTED_MESSAGE,
    Audience,
    IdentityRejected,
    VerifiedIdentity,
)
from diucs.domain.errors import ValidationFailed

pytestmark = pytest.mark.asyncio(loop_scope="session")

D1 = "11111111-1111-4111-8111-111111111111"
OID = "33333333-3333-4333-8333-333333333333"
G1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CREDENTIAL = "synthetic-entra-id-token-0001"


def identity(**changes: object) -> VerifiedIdentity:
    fields: dict[str, object] = {
        "directory_id": D1,
        "object_id": OID,
        "group_ids": frozenset({G1}),
        "app_roles": frozenset({"DIUCS.Support"}),
    }
    fields.update(changes)
    return VerifiedIdentity(**fields)  # type: ignore[arg-type]


def test_the_audiences_are_staff_and_operator() -> None:
    assert {a.value for a in Audience} == {"staff", "operator"}


def test_an_identity_holds_what_it_was_given_in_lower_case() -> None:
    made = identity(
        directory_id=D1.upper(), object_id=OID.upper(), group_ids=frozenset({G1.upper()})
    )

    assert (made.directory_id, made.object_id, made.group_ids) == (D1, OID, frozenset({G1}))


@pytest.mark.parametrize(
    "changes",
    [
        {"directory_id": ""},
        {"directory_id": "not-a-guid"},
        {"directory_id": None},
        {"directory_id": D1 + "x"},
        {"object_id": ""},
        {"object_id": "not-a-guid"},
        {"object_id": 7},
        {"group_ids": frozenset({"not-a-guid"})},
        {"group_ids": frozenset({7})},
        {"group_ids": [G1]},
        {"app_roles": frozenset({7})},
        {"app_roles": frozenset({""})},
        {"app_roles": ["DIUCS.Support"]},
        {"app_roles": frozenset({"x" * 129})},
    ],
)
def test_an_identity_that_is_not_two_guids_and_two_sets_is_refused_without_naming_a_value(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        identity(**changes)

    assert "not-a-guid" not in str(refused.value)


def test_an_identity_shows_none_of_its_values() -> None:
    made = identity()

    shown = repr(made) + str(made)
    for text in (D1, OID, G1, "DIUCS.Support"):
        assert text not in shown


def test_an_identity_with_no_groups_and_no_roles_is_valid() -> None:
    made = identity(group_ids=frozenset(), app_roles=frozenset())

    assert made.group_ids == frozenset() and made.app_roles == frozenset()


async def test_a_registered_credential_gives_its_identity_for_its_audience() -> None:
    verifier = FakeIdentityVerifier()
    verifier.accepts(CREDENTIAL, identity(), Audience.STAFF)

    assert await verifier.verify(CREDENTIAL, Audience.STAFF) == identity()


async def test_a_credential_is_for_the_audience_it_was_registered_for_only() -> None:
    verifier = FakeIdentityVerifier()
    verifier.accepts(CREDENTIAL, identity(), Audience.STAFF)

    with pytest.raises(IdentityRejected):
        await verifier.verify(CREDENTIAL, Audience.OPERATOR)


async def test_the_audience_defaults_to_staff() -> None:
    verifier = FakeIdentityVerifier()
    verifier.accepts(CREDENTIAL, identity())

    assert await verifier.verify(CREDENTIAL, Audience.STAFF) == identity()


@pytest.mark.parametrize("credential", ["", "unknown", None, 7, b"bytes", "x" * 20000])
async def test_an_unknown_or_malformed_credential_is_rejected_with_the_fixed_message(
    credential: object,
) -> None:
    verifier = FakeIdentityVerifier()
    verifier.accepts(CREDENTIAL, identity())

    with pytest.raises(IdentityRejected) as refused:
        await verifier.verify(credential, Audience.STAFF)  # type: ignore[arg-type]

    assert str(refused.value) == IDENTITY_REJECTED_MESSAGE
    assert str(credential) not in str(refused.value) or credential in ("", "unknown")


async def test_the_fake_records_the_audiences_asked_and_never_a_credential() -> None:
    verifier = FakeIdentityVerifier()
    verifier.accepts(CREDENTIAL, identity())

    await verifier.verify(CREDENTIAL, Audience.STAFF)
    with pytest.raises(IdentityRejected):
        await verifier.verify("nope", Audience.OPERATOR)

    assert verifier.audiences_asked == (Audience.STAFF, Audience.OPERATOR)
    assert CREDENTIAL not in repr(verifier) + repr(vars(verifier))


def test_registering_a_credential_that_is_not_text_is_refused() -> None:
    for bad in ("", None, 7):
        with pytest.raises(TypeError):
            FakeIdentityVerifier().accepts(bad, identity())  # type: ignore[arg-type]
