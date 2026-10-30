"""Fake identity verifier (TEN-043): accepts only the credentials a test registers.

An external-provider fake (Microsoft Entra ID is never called in a test). A credential is registered
for one audience with the identity it proves; any other credential, and a registered one asked for
another audience, is `IdentityRejected`. It records the audiences it was asked for, in order, and
never the credentials: a repr, a message and a record show none.
"""

from diucs.application.ports.outbound.identity_verifier import (
    Audience,
    IdentityRejected,
    VerifiedIdentity,
)


class _Registered:
    """The registered credentials behind a repr that shows none."""

    def __init__(self) -> None:
        self.by_key: dict[tuple[str, Audience], VerifiedIdentity] = {}

    def __repr__(self) -> str:
        return f"<{len(self.by_key)} credentials hidden>"


class FakeIdentityVerifier:
    def __init__(self) -> None:
        self._registered = _Registered()
        self._asked: list[Audience] = []

    def accepts(
        self, credential: str, identity: VerifiedIdentity, audience: Audience = Audience.STAFF
    ) -> None:
        if type(credential) is not str or not credential:
            raise TypeError("a credential must be non-empty text")
        self._registered.by_key[(credential, audience)] = identity

    async def verify(self, credential: str, audience: Audience) -> VerifiedIdentity:
        self._asked.append(audience)
        if type(credential) is not str:
            raise IdentityRejected
        found = self._registered.by_key.get((credential, audience))
        if found is None:
            raise IdentityRejected
        return found

    @property
    def audiences_asked(self) -> tuple[Audience, ...]:
        return tuple(self._asked)
