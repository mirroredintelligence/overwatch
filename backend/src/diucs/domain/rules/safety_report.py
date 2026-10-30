"""The safety concern and the problem report (U41): the categories, the text limit and the
reference.

A safety concern goes to the clinical safety officer. Its free text goes to the protected store, and
the graph holds the category, the reference (SC- and a sequence, "SC-0192") and a handle. The
categories are [ASSUMED] until the clinical safety officer agrees them (fhir-data-model.md).
A problem report is the Help screen's report: a category, optional text and whether the session was
shared. Pure: no I/O.
"""

from enum import StrEnum
from typing import Final

from diucs.domain.errors import ValidationFailed

SAFETY_CONCERN_CODE: Final = "safety-concern"
PROBLEM_REPORT_CODE: Final = "problem-report"
REPORT_CODES: Final = frozenset({SAFETY_CONCERN_CODE, PROBLEM_REPORT_CODE})
MAX_TEXT_LENGTH: Final = 280
REFERENCE_PREFIX: Final = "SC-"


class SafetyConcernCategory(StrEnum):
    WRONG_SERVICE_SHOWN = "wrong-service-shown"
    OUT_OF_DATE_CRITERIA = "out-of-date-criteria"
    WRONG_STATUS_ON_BOARD = "wrong-status-on-board"
    MESSAGE_WRONG_PLACE = "message-went-to-wrong-place"
    SOMETHING_ELSE = "something-else"


class ProblemCategory(StrEnum):
    SCREEN_SLOW = "screen-slow"
    BUTTON_DOES_NOT_WORK = "button-does-not-work"
    FIGURE_LOOKS_WRONG = "figure-looks-wrong"
    SOMETHING_ELSE = "something-else"


def checked_concern_text(text: object) -> str:
    """The concern's text: required, not blank, and at most 280 characters. A refusal never echoes
    the text."""
    if not isinstance(text, str) or not text.strip():
        raise ValidationFailed("text", "is required")
    if len(text) > MAX_TEXT_LENGTH:
        raise ValidationFailed("text", f"must be at most {MAX_TEXT_LENGTH} characters")
    return text


def checked_problem_text(text: object | None) -> str | None:
    """A problem report's text is optional: none, or empty, is no text. Any text is at most 280."""
    if text is None or text == "":
        return None
    if not isinstance(text, str):
        raise ValidationFailed("text", "must be text")
    if len(text) > MAX_TEXT_LENGTH:
        raise ValidationFailed("text", f"must be at most {MAX_TEXT_LENGTH} characters")
    return text


def safety_reference(sequence: int) -> str:
    """The reference of the nth concern: SC- and the sequence, at least four digits ("SC-0192")."""
    if type(sequence) is not int or sequence < 1:
        raise ValidationFailed("sequence", "must be a positive whole number")
    return f"{REFERENCE_PREFIX}{sequence:04d}"


def concern_notice(reference: str) -> tuple[str, str]:
    """The officer's notice (K3): the reference only, never the concern's text."""
    return (f"New safety concern {reference}", "Open DIUCS to read it. No details are sent here.")
