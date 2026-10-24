import pytest

from diucs.domain.errors import (
    Conflict,
    DomainError,
    InvalidTransition,
    NotAllowed,
    NotFound,
    ValidationFailed,
)


def test_validation_failed_keeps_field_and_message() -> None:
    error = ValidationFailed("usual_range", "low must not exceed high")
    assert isinstance(error, DomainError)
    assert error.field == "usual_range"
    assert error.message == "low must not exceed high"
    assert str(error) == "usual_range: low must not exceed high"


@pytest.mark.parametrize("error_type", [InvalidTransition, NotFound, Conflict, NotAllowed])
def test_error_subclasses_are_domain_errors(error_type: type[DomainError]) -> None:
    assert issubclass(error_type, DomainError)
