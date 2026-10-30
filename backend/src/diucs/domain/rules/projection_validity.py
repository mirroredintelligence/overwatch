"""Stub (red commit)."""

from datetime import datetime

from diucs.domain.model.service import ServiceProfile


def next_status_change(
    profile: ServiceProfile, last_report_at: datetime | None, now: datetime
) -> datetime | None:
    return None
