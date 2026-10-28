"""Domain errors. Every error the domain or use cases raise on purpose subclasses DomainError."""


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


class NotAllowed(DomainError):
    """The actor may not do this."""


class ConfirmLimitReached(DomainError):
    """A third confirmation in a row: the figure must be given again as a number."""


class NothingToConfirm(DomainError):
    """The service has no report on record, so there is no figure to confirm."""
