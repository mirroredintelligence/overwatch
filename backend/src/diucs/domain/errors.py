"""Domain errors. Every error the domain or use cases raise on purpose subclasses DomainError."""

from datetime import datetime


class DomainError(Exception):
    """Base class for expected, reportable failures of a rule or a request."""


class InvalidTransition(DomainError):
    """A state change that the state machine does not allow."""


class ValidationFailed(DomainError):
    """An input broke a rule. Carries the field name and a plain message, never patient data."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


class NotFound(DomainError):
    """The thing asked for does not exist."""


class Conflict(DomainError):
    """The request clashes with the current state of the record."""


class StaleVersion(DomainError):
    """The record is at another version than the caller read: a change made since they read it
    would be lost by this write (412 at the edge, H-192)."""


class NotAllowed(DomainError):
    """The actor may not do this."""


class ConfirmLimitReached(DomainError):
    """A third confirmation in a row: the figure must be given again as a number."""


class LatestReportChanged(Conflict):
    """A confirmation asked to confirm one report, and the latest report of the service is another.
    The figure the caller judged is not the figure that would be confirmed, so nothing is written
    (DEC-148 item 18). Carries the value and effective time of the report that is now the latest, so
    the caller can tell the reporter which figure is on record."""

    def __init__(self, message: str, latest_value: int, latest_at: datetime) -> None:
        super().__init__(message)
        self.latest_value = latest_value
        self.latest_at = latest_at


class NothingToConfirm(DomainError):
    """The service has no report on record, so there is no figure to confirm."""


class EffectiveNotAfterLatest(ValidationFailed):
    """A number given with an effective time that is not later than the latest figure of its
    service. Stored, it would be hidden behind that figure (or tie with it), so it is refused
    (DEC-140, DEC-1100 Q8). `latest_at` is the latest figure's time, so the edge can tell the
    reporter which figure is on record; the message names it in the tenant's local time."""

    def __init__(self, message: str, latest_at: datetime) -> None:
        super().__init__("effective_at", message)
        self.latest_at = latest_at


class EffectiveBeforeConfirmation(EffectiveNotAfterLatest):
    """The latest figure is a confirmation: the figure the board shows after it is that
    confirmation's, and a number not later than it would never reach the board (DEC-140). Kept as
    its own class for the callers that tell a confirmation from a number."""
