"""Postcode normalisation and district (D19). Pure string handling: no I/O, no logging.

A normalised postcode or district is personal data in combination with a case, so no function
here puts the input value into a log line or an error message.
"""

from diucs.domain.errors import ValidationFailed


def normalise_postcode(text: str) -> str | None:
    """Return the canonical full postcode, or None if the text is not a full postcode."""
    raise NotImplementedError


def postcode_district(postcode: str) -> str:
    """Return the outward code of a normalised full postcode."""
    raise NotImplementedError


def normalise_district(text: str) -> str | None:
    """Return the canonical district (outward code only), or None if it is not one."""
    raise NotImplementedError


__all__ = ["ValidationFailed", "normalise_district", "normalise_postcode", "postcode_district"]
