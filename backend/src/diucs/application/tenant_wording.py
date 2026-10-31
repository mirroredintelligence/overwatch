"""The wording of the tenant a message is for, from its configuration in force (TEN-022, KI-490,
KI-492, H-T15).

`WordingFor` is the seam of the use cases that print a tenant's words (a booking request names its
referral system). In the serving process this is the source: the configuration version in force of
the bound tenant, through the configuration read port. It reads for the BOUND tenant only: a scope
that is not the bound tenant is a wiring fault and nothing is read, and a network scope has no
wording. A tenant with no wording set gets None, and the use case refuses (no default words).

It opens a unit of work of its own when it reads, so a caller asks for the wording before its own
unit opens (a unit cannot open inside another, `UnitOfWorkAlreadyOpen`).
"""

from typing import Protocol

from diucs.application.tenancy import (
    ScopeId,
    ScopeKind,
    TenantMismatch,
    TenantNotBound,
    current_scope,
)
from diucs.domain.model.tenant import TenantWording


class WordingReader(Protocol):
    async def wording(self) -> TenantWording | None:
        """The wording of the configuration in force of the bound tenant, or None."""
        ...


class ConfiguredWording:
    def __init__(self, reader: WordingReader) -> None:
        self._reader = reader

    async def __call__(self, scope: ScopeId) -> TenantWording | None:
        if scope.kind is not ScopeKind.TENANT:
            raise TenantNotBound
        if current_scope() != scope:
            raise TenantMismatch
        return await self._reader.wording()
