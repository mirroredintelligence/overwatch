"""A tenant's admin-consent invites on Neo4j (DEC-1316).

One node per invite in the tenant's own scope: `(:AdminConsentInvite {tenantId, inviteId,
directoryId, emailHash, emailMasked, stateHash, status, createdAt, expiresAt, consentedAt,
revokedAt, lastReason, servicePrincipalId})`. Every statement is a registered `NamedQuery` that
names `tenantId: $tenant`, so another tenant's invite is never matched. Only hashes are stored: the
state's SHA-256 and the administrator address's keyed hash; the masked address is what the
operator's page shows.
Migration 0202 makes `(tenantId, inviteId)` unique.

A node the domain refuses when read is `TenantRecordInvalid` with a fixed message (fail closed).
"""

from datetime import UTC, datetime
from typing import Any, Final, Literal

from overwatch.adapters.outbound.graph_store.driver import ScopedTx, run_query
from overwatch.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from overwatch.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    TenantSeed,
)
from overwatch.application.ports.outbound.tenants import TenantRecordInvalid
from overwatch.domain.errors import ValidationFailed
from overwatch.domain.rules.admin_consent import AdminConsentInvite, InviteStatus

RECORD_MESSAGE: Final = "an admin consent record is not valid"

_T: Final = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
_T2: Final = datetime(2026, 11, 1, 13, 0, tzinfo=UTC)
_T_END: Final = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
_DIRECTORY: Final = "11111111-1111-1111-1111-111111111111"
_EMAIL_HASH: Final = "a" * 64
_STATE_HASH: Final = "b" * 64
_NEW_STATE_HASH: Final = "c" * 64

_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "i",
            ("AdminConsentInvite",),
            {
                "inviteId": "inv-1",
                "directoryId": _DIRECTORY,
                "emailHash": _EMAIL_HASH,
                "emailMasked": Marked("mask"),
                "stateHash": _STATE_HASH,
                "status": "pending",
                "createdAt": _T,
                "expiresAt": _T_END,
            },
        ),
    )
)

_SP: Final = "22222222-2222-2222-2222-222222222222"
_SEED_CONSENTED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "i",
            ("AdminConsentInvite",),
            {
                "inviteId": "inv-1",
                "directoryId": _DIRECTORY,
                "emailHash": _EMAIL_HASH,
                "emailMasked": Marked("mask"),
                "stateHash": _STATE_HASH,
                "status": "consented",
                "createdAt": _T,
                "expiresAt": _T_END,
                "consentedAt": _T2,
            },
        ),
    )
)

_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-ACI-ADD": Scenario(
        "create an invite beside the tenant's own",
        seed=_SEED,
        params={
            "inviteId": "inv-2",
            "directoryId": _DIRECTORY,
            "emailHash": _EMAIL_HASH,
            "emailMasked": "n***@example.org",
            "stateHash": _NEW_STATE_HASH,
            "status": "pending",
            "createdAt": _T2,
            "expiresAt": _T_END,
        },
        new=("inviteId", "emailMasked", "stateHash"),
        expect=Expect(
            rows=({"written": 1},),
            nodes={"AdminConsentInvite": 1},
            after=(NodeSpec(("AdminConsentInvite",), {"inviteId": "inv-2", "status": "pending"}),),
        ),
    ),
    "Q-ACI-BY-STATE": Scenario(
        "read the tenant's invite by the hash of its state",
        seed=_SEED,
        params={"stateHash": _STATE_HASH},
        lookup=("stateHash",),
        expect=Expect(rows=({"props": {"emailMasked": Marked("mask"), "status": "pending"}},)),
    ),
    "Q-ACI-LATEST": Scenario(
        "read the tenant's invites, newest first",
        seed=_SEED,
        expect=Expect(rows=({"props": {"emailMasked": Marked("mask")}},)),
    ),
    "Q-ACI-REVOKE-OPEN": Scenario(
        "revoke the tenant's pending invites",
        seed=_SEED,
        params={"at": _T2},
        expect=Expect(
            rows=({"revoked": 1},),
            after=(NodeSpec(("AdminConsentInvite",), {"inviteId": "inv-1", "status": "revoked"}),),
        ),
    ),
    "Q-ACI-CONSENT": Scenario(
        "move the tenant's pending invite to consented once",
        seed=_SEED,
        params={"inviteId": "inv-1", "at": _T2, "servicePrincipalId": _SP},
        lookup=("inviteId",),
        new=("servicePrincipalId",),
        expect=Expect(
            rows=({"moved": 1},),
            after=(
                NodeSpec(
                    ("AdminConsentInvite",),
                    {"inviteId": "inv-1", "status": "consented", "servicePrincipalId": _SP},
                ),
            ),
        ),
    ),
    "Q-ACI-CONSENTED": Scenario(
        "read the tenant's consented invites, newest first",
        seed=_SEED_CONSENTED,
        expect=Expect(rows=({"props": {"emailMasked": Marked("mask")}},)),
    ),
    "Q-ACI-SP": Scenario(
        "keep the service principal on the tenant's consented invite that has none",
        seed=_SEED_CONSENTED,
        params={"inviteId": "inv-1", "servicePrincipalId": _SP},
        lookup=("inviteId",),
        new=("servicePrincipalId",),
        expect=Expect(
            rows=({"saved": 1},),
            after=(
                NodeSpec(("AdminConsentInvite",), {"inviteId": "inv-1", "servicePrincipalId": _SP}),
            ),
        ),
    ),
    "Q-ACI-REASON": Scenario(
        "keep the words for why the tenant's last check did not confirm",
        seed=_SEED,
        params={"inviteId": "inv-1", "reason": "not installed yet"},
        lookup=("inviteId",),
        new=("reason",),
        expect=Expect(
            rows=({"saved": 1},),
            after=(
                NodeSpec(
                    ("AdminConsentInvite",),
                    {"inviteId": "inv-1", "lastReason": "not installed yet"},
                ),
            ),
        ),
    ),
}

_QUERIES: Final[dict[str, tuple[str, Literal["read", "write"]]]] = {
    "Q-ACI-ADD": (
        "CREATE (i:AdminConsentInvite {tenantId: $tenant, inviteId: $inviteId, "
        "directoryId: $directoryId, emailHash: $emailHash, emailMasked: $emailMasked, "
        "stateHash: $stateHash, status: $status, createdAt: $createdAt, expiresAt: $expiresAt}) "
        "RETURN count(i) AS written",
        "write",
    ),
    "Q-ACI-BY-STATE": (
        "MATCH (i:AdminConsentInvite {stateHash: $stateHash, tenantId: $tenant}) "
        "RETURN properties(i) AS props",
        "read",
    ),
    # No LIMIT: the caller takes the first row, and a missing tenant predicate would add the other
    # tenant's invite, which the generated test then sees.
    "Q-ACI-LATEST": (
        "MATCH (i:AdminConsentInvite {tenantId: $tenant}) "
        "RETURN properties(i) AS props ORDER BY i.createdAt DESC",
        "read",
    ),
    "Q-ACI-REVOKE-OPEN": (
        "MATCH (i:AdminConsentInvite {status: 'pending', tenantId: $tenant}) "
        "SET i.status = 'revoked', i.revokedAt = $at "
        "RETURN count(i) AS revoked",
        "write",
    ),
    # Lock first, then read the status (lessons L73 and L99): two confirmations at once are told
    # apart by the status the second reads after the first has committed.
    "Q-ACI-CONSENT": (
        "MATCH (i:AdminConsentInvite {inviteId: $inviteId, tenantId: $tenant}) "
        "SET i.inviteId = i.inviteId "
        "WITH i WHERE i.status = 'pending' "
        "SET i.status = 'consented', i.consentedAt = $at, i.lastReason = null, "
        "i.servicePrincipalId = $servicePrincipalId "
        "RETURN count(i) AS moved",
        "write",
    ),
    "Q-ACI-CONSENTED": (
        "MATCH (i:AdminConsentInvite {status: 'consented', tenantId: $tenant}) "
        "RETURN properties(i) AS props ORDER BY i.consentedAt DESC",
        "read",
    ),
    "Q-ACI-SP": (
        "MATCH (i:AdminConsentInvite {inviteId: $inviteId, status: 'consented', "
        "tenantId: $tenant}) "
        "SET i.servicePrincipalId = $servicePrincipalId "
        "RETURN count(i) AS saved",
        "write",
    ),
    "Q-ACI-REASON": (
        "MATCH (i:AdminConsentInvite {inviteId: $inviteId, tenantId: $tenant}) "
        "SET i.lastReason = $reason "
        "RETURN count(i) AS saved",
        "write",
    ),
}

ADMIN_CONSENT_QUERY_IDS: Final[tuple[str, ...]] = tuple(_QUERIES)
for _query_id, (_cypher, _mode) in _QUERIES.items():
    REGISTRY.register(
        NamedQuery(id=_query_id, cypher=_cypher, mode=_mode, scenario=_SCENARIOS[_query_id])
    )


def _invalid() -> TenantRecordInvalid:
    return TenantRecordInvalid(RECORD_MESSAGE)


def _instant(value: Any) -> datetime:
    native = value.to_native() if hasattr(value, "to_native") else value
    if type(native) is not datetime or native.utcoffset() is None:
        raise _invalid()
    return native.astimezone(UTC)


def _optional_instant(value: Any) -> datetime | None:
    return None if value is None else _instant(value)


def _text(props: dict[str, Any], key: str) -> str:
    value = props.get(key)
    if type(value) is not str:
        raise _invalid()
    return value


def invite_params(invite: AdminConsentInvite) -> dict[str, Any]:
    return {
        "inviteId": invite.invite_id,
        "directoryId": invite.directory_id,
        "emailHash": invite.email_hash,
        "emailMasked": invite.email_masked,
        "stateHash": invite.state_hash,
        "status": invite.status.value,
        "createdAt": invite.created_at,
        "expiresAt": invite.expires_at,
    }


def invite_from_props(props: dict[str, Any]) -> AdminConsentInvite:
    try:
        reason = props.get("lastReason")
        if reason is not None and type(reason) is not str:
            raise _invalid()
        sp = props.get("servicePrincipalId")
        if sp is not None and type(sp) is not str:
            raise _invalid()
        return AdminConsentInvite(
            invite_id=_text(props, "inviteId"),
            directory_id=_text(props, "directoryId"),
            email_hash=_text(props, "emailHash"),
            email_masked=_text(props, "emailMasked"),
            state_hash=_text(props, "stateHash"),
            status=InviteStatus(_text(props, "status")),
            created_at=_instant(props.get("createdAt")),
            expires_at=_instant(props.get("expiresAt")),
            consented_at=_optional_instant(props.get("consentedAt")),
            revoked_at=_optional_instant(props.get("revokedAt")),
            last_reason=reason,
            service_principal_id=sp,
        )
    except (ValidationFailed, ValueError) as error:
        raise _invalid() from error


class Neo4jAdminConsentRepository:
    """The tenant's invites on the unit of work's transaction. The tenant is the scope the unit
    opened with; nothing here takes one."""

    def __init__(self, tx: ScopedTx) -> None:
        self._tx = tx

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        return await run_query(self._tx, REGISTRY.get(query_id), **params)

    async def add(self, invite: AdminConsentInvite) -> None:
        await self._run("Q-ACI-ADD", **invite_params(invite))

    async def by_state_hash(self, state_hash: str) -> AdminConsentInvite | None:
        rows = await self._run("Q-ACI-BY-STATE", stateHash=state_hash)
        return invite_from_props(rows[0]["props"]) if rows else None

    async def latest(self) -> AdminConsentInvite | None:
        rows = await self._run("Q-ACI-LATEST")
        return invite_from_props(rows[0]["props"]) if rows else None

    async def revoke_open(self, at: datetime) -> int:
        rows = await self._run("Q-ACI-REVOKE-OPEN", at=at)
        return int(rows[0]["revoked"])

    async def mark_consented(
        self, invite_id: str, at: datetime, service_principal_id: str | None = None
    ) -> bool:
        rows = await self._run(
            "Q-ACI-CONSENT", inviteId=invite_id, at=at, servicePrincipalId=service_principal_id
        )
        return int(rows[0]["moved"]) == 1

    async def consented(self) -> AdminConsentInvite | None:
        rows = await self._run("Q-ACI-CONSENTED")
        return invite_from_props(rows[0]["props"]) if rows else None

    async def set_service_principal(self, invite_id: str, service_principal_id: str) -> None:
        await self._run("Q-ACI-SP", inviteId=invite_id, servicePrincipalId=service_principal_id)

    async def set_reason(self, invite_id: str, reason: str) -> None:
        await self._run("Q-ACI-REASON", inviteId=invite_id, reason=reason)


__all__ = [
    "ADMIN_CONSENT_QUERY_IDS",
    "Neo4jAdminConsentRepository",
    "invite_from_props",
    "invite_params",
]
