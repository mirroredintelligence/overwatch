"""What a Y or a link confirm is judged against: the prompt that named the figure (H-31, H-32).

The text reply (`HandleInboundText`) and the link reply (`link_access`) both judge the same two
hazards, and each had its own copy of the second (KI-159). They share this module, so the two paths
cannot drift:

- H-31: a Y confirms the figure on record, so it must not make an old figure current. The figure
  must be no older than `CONFIRMABLE_FIGURE_AGE` at the moment the prompt named it
  (`figure_is_out_of_date`).
- H-32: a Y answers the figure the prompt named, so it is refused when a number was written for the
  service since the prompt was sent, whatever effective time that number was given
  (`number_after_prompt`): the test is the record order (`recorded_since_prompt`), not the
  effective time, because a lead may record a figure for an earlier time (DEC-140).

Decisions: DEC-148 items 2, 17 and 20.
"""

from datetime import UTC, datetime, timedelta
from typing import Final

from diucs.application.ports.outbound.unit_of_work import UnitOfWork
from diucs.domain.codes import ReportType
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.rules.freshness import STALE_WARNING_AFTER

CONFIRMABLE_FIGURE_AGE: Final = STALE_WARNING_AFTER
"""A Y confirms a figure only if it was no older than this when the prompt named it (DEC-148)."""


def _instant(name: str, value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValidationFailed(name, "must be a timezone-aware datetime")
    return value.astimezone(UTC)


def figure_is_out_of_date(
    figure_as_of: datetime,
    prompt_sent_at: datetime,
    window: timedelta = CONFIRMABLE_FIGURE_AGE,
) -> bool:
    """True when the figure was older than the window at the moment the prompt named it. The window
    is the service's own (`domain.rules.confirmable_age`, DEC-1100 Q4); with none given it is the
    tenant's default stale limit, two hours.

    Both are compared as UTC instants, so a London clock change cannot move the line (lesson L4).
    Exactly the window is still inside it, as D05's stale warning (strictly more than 2 hours). A
    figure reported after the prompt has a negative age and is never out of date.
    """
    as_of = _instant("as_of", figure_as_of)
    sent_at = _instant("sent_at", prompt_sent_at)
    return sent_at - as_of > window


def recorded_since_prompt(report: CapacityReport, prompt_sent_at: datetime) -> bool:
    """True when the store wrote the report at or after the whole second the prompt was sent in.

    This is the record order, not the effective time: a lead may record a figure that was true at
    an earlier time (DEC-140), so a report written after the prompt can carry an effective time
    before it, or exactly at it. The store stamps whole seconds (lesson L65), so the prompt's time
    is cut to the whole second too and a tie counts as since: a figure written in the same second
    as the prompt cannot be told from one written just after it, and the Y fails closed. A report
    with no write time cannot be shown to predate the prompt and counts as since. Both are UTC
    instants, so a London clock change cannot move the line (lesson L4).
    """
    sent = _instant("sent_at", prompt_sent_at).replace(microsecond=0)
    if report.written_at is None:
        return True
    return _instant("written_at", report.written_at) >= sent


async def number_after_prompt(
    uow: UnitOfWork,
    service_id: str,
    latest: CapacityReport | None,
    prompt_sent_at: datetime,
) -> bool:
    """True when a number was written for the service since the prompt was sent. A Y is an answer
    to the figure the prompt named; a number that came in since is a figure the reporter was never
    shown, whatever effective time it was given (a lead may record a figure for an earlier time,
    DEC-140): the test is the record order (`recorded_since_prompt`), not the effective time. The
    reports looked at are the latest one and those effective from the prompt on; a number written
    since with an earlier effective time than the latest report does not change which figure is
    current, so the figure the prompt named still is. A confirmation repeats a figure and does not
    count, so the second of two Ys to one prompt is still a Y to that figure (hazard H-32, DEC-148
    items 17 and 20)."""
    since = await uow.capacity.reports_since(service_id, prompt_sent_at)
    candidates = since if latest is None else [*since, latest]
    return any(
        report.report_type is ReportType.NUMBER and recorded_since_prompt(report, prompt_sent_at)
        for report in candidates
    )


async def answered_since_prompt(
    uow: UnitOfWork,
    service_id: str,
    latest: CapacityReport | None,
    prompt_sent_at: datetime,
) -> bool:
    """True when any report, a number or a confirmation, was written for the service since the
    prompt was sent: the service has answered it (KI-30). The record order again, so a figure a lead
    recorded after the prompt for an earlier time still counts."""
    since = await uow.capacity.reports_since(service_id, prompt_sent_at)
    candidates = since if latest is None else [*since, latest]
    return any(recorded_since_prompt(report, prompt_sent_at) for report in candidates)
