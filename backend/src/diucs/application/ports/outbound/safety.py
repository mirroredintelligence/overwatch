"""Outbound port: safety concerns and problem reports, stored as Tasks (U41). Adapter:
Neo4jSafetyReportRepository (graph_store/safety_report_repository.py).

The free text is not here: a report holds only the handle of its text in the protected store
(ProtectedTextStore). The concern references come from a per-tenant counter, read and advanced in
the caller's unit of work.
"""

from typing import Protocol

from diucs.domain.model.safety import SafetyReport


class SafetyReportRepository(Protocol):
    async def next_concern_reference(self) -> str:
        """Advance the tenant's concern counter and return its reference ("SC-0001", "SC-0002")."""
        ...

    async def add(self, report: SafetyReport) -> None:
        """Store a new report. An id that exists raises Conflict."""
        ...

    async def get(self, report_id: str) -> SafetyReport | None:
        """The stored report, or None."""
        ...
