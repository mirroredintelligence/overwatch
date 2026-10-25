"""Privacy guard for message text (D17, hazard H-09).

No text, email or push may carry a patient name, a full postcode, an NHS number or free text
(docs/spec/domain-rules.md section 9). This module finds the shapes it can recognise. The
build-time sweep in tests/unit/domain/messages/test_no_patient_data_in_templates.py runs it over
every template, every channel and every sample. DEC-047 records the choices made here and what
the guard does not cover.
"""

import re
from typing import Final

FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "name",
        "patient_name",
        "nhs_number",
        "postcode",
        "address",
        "dob",
        "date_of_birth",
        "free_text",
    }
)

# Full UK postcode, with any run of whitespace (or none) between the halves (DEC-028, DEC-047).
# "DT4" alone does not match.
_POSTCODE: Final = re.compile(r"\b[A-Z]{1,2}[0-9][A-Z0-9]?\s*[0-9][A-Z]{2}\b", re.IGNORECASE)

# NHS-number shape: ten digits, contiguous or grouped 3-3-4 with a space or hyphen at each join,
# and not part of a longer digit run. Eleven-digit phone numbers and 4-digit references never match.
_NHS_NUMBER: Final = re.compile(
    r"(?<![0-9])(?:[0-9]{10}|[0-9]{3}[ -][0-9]{3}[ -][0-9]{4})(?![0-9])"
)

# Personal title, in any case, then a capitalised word. Mrs Smith, Dr. Jones, MRS Smith.
_TITLED_NAME: Final = re.compile(r"\b(?i:mr|mrs|ms|miss|dr)\.?\s[A-Z][a-z]+")

_PATTERNS: Final = (_POSTCODE, _NHS_NUMBER, _TITLED_NAME)


def find_patient_data(text: str) -> list[str]:
    """Return each fragment of text that has a patient-data shape, in the order it appears."""
    found = [
        (match.start(), match.group(0)) for pattern in _PATTERNS for match in pattern.finditer(text)
    ]
    return [fragment for _, fragment in sorted(found)]
