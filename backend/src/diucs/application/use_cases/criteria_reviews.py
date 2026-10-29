"""The daily criteria review job (U31). Stub: the behaviour is written in the implement step."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

REVIEW_RUN_AT: Final = None
CONSUMER: Final = "criteria-reviews"


def next_run_due(now: datetime) -> datetime:
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class RunCriteriaReviewsCommand:
    work_id: str


@dataclass(frozen=True, slots=True)
class CriteriaReviewsResult:
    reminders_sent: int
    flags_set: int


class RunCriteriaReviews:
    def __init__(self, uow_factory: object, ids: object, clock: object, sealer: object) -> None:
        raise NotImplementedError

    async def execute(self, command: RunCriteriaReviewsCommand) -> CriteriaReviewsResult:
        raise NotImplementedError


async def ensure_daily_schedule(uow_factory: object, ids: object, clock: object) -> bool:
    raise NotImplementedError
