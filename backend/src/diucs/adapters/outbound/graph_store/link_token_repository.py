"""Neo4j store for link tokens (P10, DEC-004, DEC-057, L01). Only the token hash is stored.

Layout: (:LinkToken {id, tenantId, tokenHash, phoneHash, purpose, aboutId, expiresAt, usedAt}). The
id is the token hash, so the node has no second identifier to keep in step. tokenHash is unique
(migration 0021) and stays unique across tenants by design (DEC-131 item 5), so a second tenant
cannot store a hash the first holds. A link token belongs to the tenant it was issued in (DEC-167
item 2): every statement writes `tenantId: $tenant` on the node and matches it, so another tenant's
link is not found, marked used or read. Times are written in UTC and read back in UTC.
"""

from datetime import UTC, datetime
from typing import Any, Final, Literal

from neo4j import AsyncManagedTransaction
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    TenantSeed,
    Unique,
)
from diucs.domain.errors import Conflict, ValidationFailed
from diucs.domain.rules.tokens import LinkTokenRecord, check_phone_hash

# Scenarios (DEC-142 item 5, DEC-167 item 2). Both tenants hold a link with the same id, phone hash,
# prompt id and times; the purpose and the burn key differ (`Marked`), so a row that came from the
# wrong tenant looks different. The token hash is the one key the schema keeps unique across
# tenants (`link_token_hash`), so it is a `Unique`: the generated test runs each statement that
# looks a link up by it with the other tenant's hash too, and it must find nothing. The create is
# proved with a plain new hash: each probe is rolled back, so the two tenants' runs never collide.
_EXPIRES: Final = datetime(2026, 10, 25, 12, 30, tzinfo=UTC)
_USED: Final = datetime(2026, 10, 25, 12, 10, tzinfo=UTC)
_PHONE: Final = "f" * 64
_HASH: Final = Unique("link-hash", "link_token_hash")
_OPEN_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "link",
            ("LinkToken",),
            {
                "id": "link-1",
                "tokenHash": _HASH,
                "phoneHash": _PHONE,
                "purpose": Marked("purpose"),
                "aboutId": "c-1",
                "expiresAt": _EXPIRES,
            },
        ),
    )
)
_BURNED_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "link",
            ("LinkToken",),
            {
                "id": "link-1",
                "tokenHash": _HASH,
                "phoneHash": _PHONE,
                "purpose": "capacity-reply",
                "aboutId": "c-1",
                "expiresAt": _EXPIRES,
                "usedAt": _USED,
                "burnKey": Marked("key"),
            },
        ),
    )
)
# The create is proved beside a link whose hash differs between the tenants (`Marked`): it needs no
# shared hash, and so leans on no constraint.
_ADD_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "link",
            ("LinkToken",),
            {
                "id": "link-1",
                "tokenHash": Marked("link-hash"),
                "phoneHash": _PHONE,
                "purpose": "capacity-reply",
                "aboutId": "c-1",
                "expiresAt": _EXPIRES,
            },
        ),
    )
)
_ADD_SCENARIO: Final = Scenario(
    "store a new link token beside the tenant's own",
    seed=_ADD_SEED,
    params={
        "id": "link-new",
        "tokenHash": "link-hash-new",
        "phoneHash": _PHONE,
        "purpose": "capacity-reply",
        "aboutId": "c-1",
        "expiresAt": _EXPIRES,
        "usedAt": None,
    },
    new=("id", "tokenHash"),
    expect=Expect(
        rows=({"written": 1},),
        nodes={"LinkToken": 1},
        after=(
            NodeSpec(
                ("LinkToken",),
                {"id": "link-new", "tokenHash": "link-hash-new", "purpose": "capacity-reply"},
            ),
        ),
    ),
)
_GET_SCENARIO: Final = Scenario(
    "read the tenant's link token by its hash",
    seed=_OPEN_SEED,
    params={"tokenHash": _HASH},
    lookup=("tokenHash",),
    expect=Expect(rows=({"props": {"purpose": Marked("purpose"), "aboutId": "c-1"}},)),
)
_MARK_SCENARIO: Final = Scenario(
    "burn the tenant's link token once",
    seed=_OPEN_SEED,
    params={"tokenHash": _HASH, "at": _USED, "key": "key-1"},
    lookup=("tokenHash",),
    new=("at", "key"),
    expect=Expect(
        rows=({"n": 1},),
        after=(NodeSpec(("LinkToken",), {"usedAt": _USED, "burnKey": "key-1"}),),
    ),
)
_BURN_KEY_SCENARIO: Final = Scenario(
    "read the key that burned the tenant's link token",
    seed=_BURNED_SEED,
    params={"tokenHash": _HASH},
    lookup=("tokenHash",),
    expect=Expect(rows=({"key": Marked("key")},)),
)

# The open invitation of a phone (U25): the phone's hash and the purpose, unused and not yet expired
# at `now`. Both tenants hold a link for the same phone hash and purpose, so the lookup collides
# across them (the scenario's lookup), and only the bound tenant's link comes back.
_BEFORE_EXPIRY: Final = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
_OPEN_FOR_PHONE_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "invite",
            ("LinkToken",),
            {
                "id": "invite-1",
                # Marked, not Unique: the lookup is by phone, so the hash needs no shared value.
                "tokenHash": Marked("invite-hash"),
                "phoneHash": _PHONE,
                "purpose": "invite",
                "aboutId": Marked("about"),
                "expiresAt": _EXPIRES,
            },
        ),
    )
)
_OPEN_FOR_PHONE_SCENARIO: Final = Scenario(
    "find the tenant's open invitation link for a phone",
    seed=_OPEN_FOR_PHONE_SEED,
    params={"phoneHash": _PHONE, "purpose": "invite", "now": _BEFORE_EXPIRY},
    lookup=("phoneHash",),
    new=("now",),
    expect=Expect(rows=({"props": {"purpose": "invite", "aboutId": Marked("about")}},)),
)

_QUERIES: dict[str, tuple[str, Literal["read", "write"], Scenario]] = {
    "Q-LINK-ADD": (
        "CREATE (t:LinkToken {id: $id, tenantId: $tenant, tokenHash: $tokenHash, "
        "phoneHash: $phoneHash, purpose: $purpose, aboutId: $aboutId, expiresAt: $expiresAt, "
        "usedAt: $usedAt}) "
        "RETURN count(t) AS written",
        "write",
        _ADD_SCENARIO,
    ),
    "Q-LINK-GET": (
        "MATCH (t:LinkToken {tokenHash: $tokenHash, tenantId: $tenant}) "
        "RETURN properties(t) AS props",
        "read",
        _GET_SCENARIO,
    ),
    # Lock first, then read. A MATCH ... WHERE usedAt IS NULL ... SET reads usedAt before any
    # write lock is held, so concurrent callers all see it unset (measured: 8 of 8, then 16 of 16,
    # won). Setting a property that does not exist (usedAt) to null is a no-op that takes no lock,
    # so the lock is taken on tokenHash, which always exists, and the WHERE then reads usedAt.
    "Q-LINK-MARK-USED": (
        "MATCH (t:LinkToken {tokenHash: $tokenHash, tenantId: $tenant}) "
        "SET t.tokenHash = t.tokenHash "
        "WITH t WHERE t.usedAt IS NULL "
        "SET t.usedAt = $at, t.burnKey = $key RETURN count(t) AS n",
        "write",
        _MARK_SCENARIO,
    ),
    "Q-LINK-BURN-KEY": (
        "MATCH (t:LinkToken {tokenHash: $tokenHash, tenantId: $tenant}) RETURN t.burnKey AS key",
        "read",
        _BURN_KEY_SCENARIO,
    ),
    # An unused link that has not expired (check_link: now before expiresAt). Missing usedAt is
    # null (lesson L74), so IS NULL reads an unused link.
    "Q-LINK-OPEN-FOR-PHONE": (
        "MATCH (t:LinkToken {phoneHash: $phoneHash, purpose: $purpose, tenantId: $tenant}) "
        "WHERE t.usedAt IS NULL AND t.expiresAt > $now "
        "RETURN properties(t) AS props ORDER BY t.expiresAt DESC LIMIT 1",
        "read",
        _OPEN_FOR_PHONE_SCENARIO,
    ),
}

for _query_id, (_cypher, _mode, _scenario) in _QUERIES.items():
    REGISTRY.register(NamedQuery(id=_query_id, cypher=_cypher, mode=_mode, scenario=_scenario))


def _utc(value: Any) -> datetime:
    native: datetime = value.to_native()
    return native.astimezone(UTC)


def _from_props(props: dict[str, Any]) -> LinkTokenRecord:
    used = props.get("usedAt")
    return LinkTokenRecord(
        token_hash=str(props["tokenHash"]),
        purpose=str(props["purpose"]),
        about_id=str(props["aboutId"]),
        phone_hash=props.get("phoneHash"),
        expires_at=_utc(props["expiresAt"]),
        used_at=_utc(used) if used is not None else None,
    )


class Neo4jLinkTokenRepository:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def add(self, record: LinkTokenRecord) -> None:
        """Store one token hash. A phone field that is not a hash is refused, and a second add of
        the same hash is Conflict; both are decided before the write, so a refused add leaves no
        node (DEC-053 item 16, H-09)."""
        check_phone_hash(record.phone_hash)
        if await self.get_by_hash(record.token_hash) is not None:
            raise Conflict("link token already exists")
        try:
            await self._run(
                "Q-LINK-ADD",
                id=record.token_hash,
                tokenHash=record.token_hash,
                phoneHash=record.phone_hash,
                purpose=record.purpose,
                aboutId=record.about_id,
                expiresAt=record.expires_at.astimezone(UTC),
                usedAt=None if record.used_at is None else record.used_at.astimezone(UTC),
            )
        except ConstraintError as error:
            raise Conflict("link token already exists") from error

    async def get_by_hash(self, token_hash: str) -> LinkTokenRecord | None:
        rows = await self._run("Q-LINK-GET", tokenHash=token_hash)
        return _from_props(rows[0]["props"]) if rows else None

    async def mark_used(self, token_hash: str, at: datetime, key: str) -> bool:
        """Set usedAt and the burn key once. True only for the caller whose write set it."""
        rows = await self._run(
            "Q-LINK-MARK-USED", tokenHash=token_hash, at=at.astimezone(UTC), key=key
        )
        return int(rows[0]["n"]) == 1

    async def burn_key(self, token_hash: str) -> str | None:
        """The key of the attempt that burned the link, or None if it is unused or unknown."""
        rows = await self._run("Q-LINK-BURN-KEY", tokenHash=token_hash)
        return rows[0]["key"] if rows else None

    async def open_for_phone(
        self, purpose: str, phone_hash: str, now: datetime
    ) -> LinkTokenRecord | None:
        """The open link of this purpose for this phone hash at `now`, or None. When several are
        open, the one that expires last. A malformed hash or a naive `now` is refused."""
        check_phone_hash(phone_hash)
        if now.utcoffset() is None:
            raise ValidationFailed("now", "must be a timezone-aware datetime")
        rows = await self._run(
            "Q-LINK-OPEN-FOR-PHONE",
            phoneHash=phone_hash,
            purpose=purpose,
            now=now.astimezone(UTC),
        )
        return _from_props(rows[0]["props"]) if rows else None

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        return await run_query(self._tx, REGISTRY.get(query_id), **params)
