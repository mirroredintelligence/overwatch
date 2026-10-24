"""Domain errors. Red-stage stub: behaviour is added in the implementation commit."""


class DomainError(Exception):
    pass


class InvalidTransition(Exception):
    pass


class ValidationFailed(Exception):
    pass


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class NotAllowed(Exception):
    pass
