"""Privacy guard for message text (D17, hazard H-09).

No text, email or push may carry a patient name, a full postcode, an NHS number or free text
(docs/spec/domain-rules.md section 9). This module finds the shapes it can recognise. The
build-time sweep in tests/unit/domain/messages/test_no_patient_data_in_templates.py runs it over
every template, every channel and every sample. DEC-047 records the choices made here and what
the guard does not cover.
"""

import re
from typing import Final

# The names that belonged to the first deployment (TEN-022). Used on raw template text only.
DEPLOYMENT_TERMS: Final[tuple[str, ...]] = (
    "Dorset",
    "SPOA",
    "SystmOne",
    "EMIS",
    "Bournemouth",
    "Poole",
    "Christchurch",
    "Weymouth",
    "Dorchester",
)

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
        # TEN-022: a text or email carries no tenant id, slug, subaccount sid or number.
        "tenant",
        "tenant_id",
        "tenant_slug",
        "account_sid",
        "sender_number",
        "from_number",
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


_DEPLOYMENT_TERM: Final = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in DEPLOYMENT_TERMS) + r")\b", re.IGNORECASE
)


def find_deployment_terms(text: str) -> list[str]:
    """Each whole-word, case-insensitive deployment term in text, in the order it appears."""
    return [match.group(0) for match in _DEPLOYMENT_TERM.finditer(text)]


def find_patient_data(text: str) -> list[str]:
    """Return each fragment of text that has a patient-data shape, in the order it appears."""
    found = [
        (match.start(), match.group(0)) for pattern in _PATTERNS for match in pattern.finditer(text)
    ]
    return [fragment for _, fragment in sorted(found)]


# ---------------------------------------------------------------- keys and values (TEN-052)


def normalise_key(name: str) -> str:
    raise NotImplementedError


FORBIDDEN_KEY_FORMS: Final[frozenset[str]] = frozenset()


def find_forbidden_keys(mapping: object) -> list[str]:
    raise NotImplementedError


def scan_value(value: object) -> list[str]:
    raise NotImplementedError
