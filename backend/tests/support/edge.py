"""The REST edge's test fixtures (TEN-018): a tenant directory that records what it was asked, and a
container of fixed parts for an app that reaches no store.

Pure: no Neo4j, no network. Every tenant here is a made-up organisation.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.domain.model.tenant import Tenant, TenantStatus
from tests.support.tenant_samples import make_tenant

EDGE_NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


class RecordingTenantDirectory:
    """`get` only, as the edge reads it. A record can be an exception, raised when it is asked for,
    and a record can be replaced mid-test (a suspend, a resume)."""

    def __init__(self, *records: Tenant | Exception) -> None:
        self.asked: list[str] = []
        self._records: dict[str, Tenant | Exception] = {}
        for record in records:
            self.put(record)

    def put(self, record: Tenant | Exception, tenant_id: str | None = None) -> None:
        key = tenant_id if tenant_id is not None else record.id  # type: ignore[union-attr]
        self._records[key] = record

    def drop(self, tenant_id: str) -> None:
        del self._records[tenant_id]

    async def get(self, tenant_id: str) -> Tenant | None:
        self.asked.append(tenant_id)
        record = self._records.get(tenant_id)
        if isinstance(record, Exception):
            raise record
        return record


def active_tenants(*ids: str, epoch: int = 1) -> RecordingTenantDirectory:
    return RecordingTenantDirectory(
        *(make_tenant(TenantStatus.ACTIVE, id=tenant_id, epoch=epoch) for tenant_id in ids)
    )


def _no_unit_of_work() -> Any:
    raise AssertionError("a unit of work was opened by a test that reaches no store")


@dataclass
class EdgeContainer:
    """What `create_app` reads from the composition root, for a test that reaches no store."""

    tenants: Any
    clock: FixedClock = field(default_factory=lambda: FixedClock(EDGE_NOW))
    ids: SequentialIds = field(default_factory=SequentialIds)
    uow_factory: Any = _no_unit_of_work
    terminology: Any = None
    validator: Any = None
