"""Outbound port: the verifier of a person's sign-in with Microsoft Entra ID (TEN-043, DEC-522).

The BFF no longer mints the back-end token (DEC-134 item 2): it hands the back end the credential
the person signed in with (the ID token), and the back end has it verified here before it issues a
token of its own. A verifier checks everything about the credential that the provider vouches for:
the signature against the directory's keys, the issuer, the audience (the application the token was
issued to, for the staff app or the operator console), the expiry and the nonce. It answers with
the facts the exchange needs, or refuses; it decides nothing about tenants or roles.

`VerifiedIdentity` holds a directory id (the token's `tid`), an object id (`oid`), the groups the
token carried and the app roles it carried. A directory id and an object id are GUIDs in lower
case; an object id is unique only within its directory, so the two always travel together. The
value shows none of its fields in a repr or a message.

The real adapter needs an Entra app registration (a tenant, a client id, the JWKS endpoint) and is
built at deploy against a real directory; the fake is `adapters/testing/fake_identity_verifier.py`.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Protocol

from diucs.domain.errors import ValidationFailed

IDENTITY_REJECTED_MESSAGE: Final = "the sign-in could not be verified"
WRONG_TYPE_MESSAGE: Final = "has the wrong type"
MAX_APP_ROLE_LENGTH: Final = 128

_GUID: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class Audience(StrEnum):
    """Which door the sign-in is for: the staff app of a tenant, or the operator console. A
    credential is verified for one of them, against that app registration's own audience."""

    STAFF = "staff"
    OPERATOR = "operator"


class IdentityRejected(Exception):
    """The credential could not be verified, for any reason. The message is fixed and holds nothing
    of the credential."""

    def __init__(self) -> None:
        super().__init__(IDENTITY_REJECTED_MESSAGE)


def _guid(name: str, value: object) -> str:
    if type(value) is not str or _GUID.fullmatch(value.lower()) is None:
        raise ValidationFailed(name, "must be a GUID")
    return value.lower()


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    directory_id: str
    object_id: str
    group_ids: frozenset[str] = field(default_factory=frozenset)
    app_roles: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "directory_id", _guid("directory_id", self.directory_id))
        object.__setattr__(self, "object_id", _guid("object_id", self.object_id))
        if type(self.group_ids) is not frozenset:
            raise ValidationFailed("group_ids", WRONG_TYPE_MESSAGE)
        object.__setattr__(
            self, "group_ids", frozenset(_guid("group_ids", group) for group in self.group_ids)
        )
        if type(self.app_roles) is not frozenset or not all(
            type(role) is str and 0 < len(role) <= MAX_APP_ROLE_LENGTH for role in self.app_roles
        ):
            raise ValidationFailed("app_roles", WRONG_TYPE_MESSAGE)

    def __repr__(self) -> str:
        return "VerifiedIdentity()"

    __str__ = __repr__


class IdentityVerifier(Protocol):
    async def verify(self, credential: str, audience: Audience) -> VerifiedIdentity:
        """The identity the credential proves for this audience, or `IdentityRejected`. Any other
        failure (the provider cannot be reached) is raised as it is, never read as a refusal."""
        ...
