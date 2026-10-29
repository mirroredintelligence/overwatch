"""Clinical advice records (P18): a request for advice, and the advice given on it (U40).

The queue rules (take, return_if_idle, give_advice, queue_order) are in diucs.domain.rules.
clinical_queue (D23). Free-text notes never enter this record: only a handle to the protected text
store (P20) is kept. Red stub: validation is added with the implementation (DEC-010).
"""

from dataclasses import dataclass
from datetime import datetime

from diucs.domain.rules.clinical_queue import ClinicalRequest


@dataclass(frozen=True, slots=True)
class ClinicalAdvice:
    choice: str
    reason: str | None
    note_handle: str | None
    clinician_id: str
    at: datetime


@dataclass(frozen=True, slots=True)
class ClinicalRequestRecord:
    request: ClinicalRequest
    requester_id: str
    why: str
    snapshot_ref: str | None
    advice: ClinicalAdvice | None = None
