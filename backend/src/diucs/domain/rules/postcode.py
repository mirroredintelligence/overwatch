"""Postcode normalisation and district (D19). Pure string handling: no I/O, no logging.

A normalised postcode or district is personal data in combination with a case, so no function
here puts the input value into a log line or an error message.

Only ASCII letters and digits are recognised. Whitespace of any kind (including the no-break
space that web pages paste) counts as a space. Anything else that upper-cases to ASCII, such as
'ß' becoming 'SS', is refused rather than converted.
"""

import re

from diucs.domain.errors import ValidationFailed

FULL_POSTCODE = re.compile(r"[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}")
DISTRICT = re.compile(r"[A-Z]{1,2}[0-9][A-Z0-9]?")
_WHITESPACE = re.compile(r"\s+")
INWARD_LENGTH = 3  # the inward code is always the last three characters


def _squash(text: str) -> str | None:
    """Remove every whitespace character and upper-case. None if anything non-ASCII remains."""
    compact = _WHITESPACE.sub("", text)
    if not compact.isascii():
        return None
    return compact.upper()


def normalise_postcode(text: str) -> str | None:
    """Return the canonical full postcode, or None if the text is not a full postcode."""
    compact = _squash(text)
    if compact is None:
        return None
    candidate = f"{compact[:-INWARD_LENGTH]} {compact[-INWARD_LENGTH:]}"
    return candidate if FULL_POSTCODE.fullmatch(candidate) else None


def postcode_district(postcode: str) -> str:
    """Return the outward code of a normalised full postcode.

    Raises ValidationFailed for anything that is not already in canonical form. The message
    deliberately does not repeat the value.
    """
    if FULL_POSTCODE.fullmatch(postcode) is None:
        raise ValidationFailed("postcode", "must be a normalised full postcode")
    return postcode.split(" ", 1)[0]


_PARTIAL_INWARD = re.compile(r"[0-9][A-Z]{0,2}")


def partial_district(text: str) -> str | None:
    """Return the district that a partial postcode ('DT4 8X') or a bare district ('DT4') names, or
    None. A full postcode is not read here: normalise it first. The inward part of a partial
    postcode is a digit and up to two letters, as far as the user has typed."""
    parts = text.split()
    if len(parts) == 1:
        return normalise_district(parts[0])
    if len(parts) == 2 and parts[1].isascii() and _PARTIAL_INWARD.fullmatch(parts[1].upper()):
        return normalise_district(parts[0])
    return None


def normalise_district(text: str) -> str | None:
    """Return the canonical district (outward code only), or None if it is not one.

    Only the ends are trimmed. A space inside the text is not removed, so 'DT4 8' is refused
    rather than read as the district 'DT48'.
    """
    trimmed = text.strip()
    if not trimmed.isascii():
        return None
    candidate = trimmed.upper()
    return candidate if DISTRICT.fullmatch(candidate) else None
