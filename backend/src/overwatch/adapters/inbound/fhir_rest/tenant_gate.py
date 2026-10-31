"""The tenant record the REST edge checks a verified token against (TEN-018, H-T23).

A signed token names its tenant and that tenant's epoch. The gate reads the tenant's own record from
the directory (global, read-only, the only code that runs before a scope is bound) and applies the
pure rule `edge_verdict`: the tenant must be active (or suspended read-only, for its administrator's
reads) and the token's epoch must not be behind the record's. The record is cached in this process
for less than RECORD_TTL, so a suspend takes effect within a minute, not at the token's expiry.

The cache holds only records that were found: an unknown tenant is asked again every time. A token
whose epoch is ahead of a cached record reads the record again once before it is judged, so a
resume that this process has not seen yet does not turn a fresh token away.

A directory error is not caught here: it reaches the app's catch-all as a 500, and no handler runs.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.domain.model.tenant import Tenant
from diucs.domain.rules.bff_token import BffClaims
from diucs.domain.rules.edge_access import EdgeVerdict, edge_verdict

# "At most 60 seconds" (audit F section 3.1, tenancy plan): a record is read again when it is this
# old or older.
RECORD_TTL: Final = timedelta(seconds=60)
# Tenant ids reach this cache only from verified tokens, so it is as small as the tenant list; the
# bound is a backstop, not a policy.
MAX_RECORDS: Final = 1024


@dataclass(frozen=True, slots=True)
class _Cached:
    tenant: Tenant
    read_at: datetime


class TenantGate:
    def __init__(self, directory: TenantDirectory, clock: Clock) -> None:
        self._directory = directory
        self._clock = clock
        self._records: dict[str, _Cached] = {}

    async def verdict(self, claims: BffClaims, method: str) -> EdgeVerdict:
        """ALLOWED or REFUSED, never RECORD_BEHIND: that is settled here with one fresh read."""
        record, was_cached = await self._record(claims.tenant)
        verdict = self._judge(record, claims, method)
        if verdict is EdgeVerdict.RECORD_BEHIND and was_cached:
            record = await self._read(claims.tenant)
            verdict = self._judge(record, claims, method)
        if verdict is EdgeVerdict.ALLOWED:
            return verdict
        return EdgeVerdict.REFUSED

    def forget(self, tenant_id: str) -> None:
        """Drop the cached record of this tenant, so the next token is judged on a fresh read. A
        suspension or a resume tells the serving process this at once (`auth.forget_tenant`); every
        other process reads the record again within `RECORD_TTL` anyway (TEN-073)."""
        self._records.pop(tenant_id, None)

    @staticmethod
    def _judge(record: Tenant | None, claims: BffClaims, method: str) -> EdgeVerdict:
        return edge_verdict(
            record,
            claimed_tenant=claims.tenant,
            token_epoch=claims.epoch,
            role=claims.role,
            method=method,
        )

    async def _record(self, tenant_id: str) -> tuple[Tenant | None, bool]:
        cached = self._records.get(tenant_id)
        if cached is not None and self._clock.now() - cached.read_at < RECORD_TTL:
            return cached.tenant, True
        return await self._read(tenant_id), False

    async def _read(self, tenant_id: str) -> Tenant | None:
        record = await self._directory.get(tenant_id)
        self._records.pop(tenant_id, None)
        if record is not None:
            if len(self._records) >= MAX_RECORDS:
                del self._records[next(iter(self._records))]
            self._records[tenant_id] = _Cached(record, self._clock.now())
        return record
