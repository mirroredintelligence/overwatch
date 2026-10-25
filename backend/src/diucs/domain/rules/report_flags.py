"""Report flag rules (D12). STUB for the red commit (DEC-010): constants and a signature only.

Rules: docs/spec/domain-rules.md section 2.3. Names: docs/spec/contracts.md, rules/report_flags.py row.
"""

from collections.abc import Sequence
from datetime import timedelta

from diucs.domain.codes import ReportFlagReason
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile

MANY_CHANGES_WINDOW = timedelta(minutes=5)
MANY_CHANGES_COUNT = 3
PHONED_WINDOW = timedelta(minutes=60)


def flags_for_report(
    new: CapacityReport,
    recent: Sequence[CapacityReport],
    profile: ServiceProfile,
) -> list[ReportFlagReason]:
    raise NotImplementedError
