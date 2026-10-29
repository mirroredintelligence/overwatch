"""Privacy guard for message text (D17, hazard H-09).

No text, email or push may carry a patient name, a full postcode, an NHS number or free text
(docs/spec/domain-rules.md section 9). This module finds the shapes it can recognise. The
build-time sweep in tests/unit/domain/messages/test_no_patient_data_in_templates.py runs it over
every template, every channel and every sample. DEC-047 records the choices made here and what
the guard does not cover.
"""

import re
from collections.abc import Mapping
from typing import Final

from diucs.domain.errors import ValidationFailed

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
#
# A projection leaves a tenant as rows and bodies, so the guard reads keys as well as text: every
# string through `find_patient_data`, and every key through the forbidden forms below. The forms
# are compared after `normalise_key`, so `patient_name`, `patientName` and `Patient-Name` agree.

_KEY_SEPARATORS: Final = re.compile(r"[_\-\s]")
MAX_SCAN_DEPTH: Final = 16


def normalise_key(name: str) -> str:
    """Lower case, with underscores, hyphens and white space removed."""
    if type(name) is not str:
        raise ValidationFailed("key", "must be text")
    return _KEY_SEPARATORS.sub("", name).lower()


FORBIDDEN_KEY_FORMS: Final[frozenset[str]] = frozenset(
    {normalise_key(name) for name in FORBIDDEN_FIELDS}
    | {
        "phone",
        "phonehash",
        "mobile",
        "email",
        "emailhash",
        "emaildomain",
        "pin",
        "pinhash",
        "token",
        "tokenhash",
        "deviceid",
        "devicetoken",
        "practitionerid",
        "performerroleid",
        "reportername",
        "comment",
        "reason",
        "changereason",
        "note",
        "notes",
        "text",
        "body",
        "message",
    }
)


def _is_forbidden_key(key: object) -> bool:
    return type(key) is not str or normalise_key(key) in FORBIDDEN_KEY_FORMS


def _walk_keys(value: object, depth: int, found: list[str]) -> None:
    if depth > MAX_SCAN_DEPTH:
        raise ValidationFailed("value", "is nested too deeply")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_forbidden_key(key):
                found.append(key if type(key) is str else str(key))
            _walk_keys(item, depth + 1, found)
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            _walk_keys(item, depth + 1, found)


def find_forbidden_keys(mapping: object) -> list[str]:
    """The offending keys, as written, of a mapping and of every mapping nested in it (inside
    lists and tuples too). A key that is not text cannot be read, so it counts as offending."""
    found: list[str] = []
    _walk_keys(mapping, 0, found)
    return found


def _walk_values(value: object, depth: int, found: list[str]) -> None:
    if depth > MAX_SCAN_DEPTH:
        raise ValidationFailed("value", "is nested too deeply")
    if isinstance(value, str):
        found.extend(find_patient_data(value))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            text = key if type(key) is str else str(key)
            found.extend(find_patient_data(text))
            if _is_forbidden_key(key):
                found.append(text)
            _walk_values(item, depth + 1, found)
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            _walk_values(item, depth + 1, found)


def scan_value(value: object) -> list[str]:
    """What looks like patient data or a forbidden key anywhere in a value: every string through
    `find_patient_data`, and every key of every mapping, in lists, tuples and sets too. A value
    nested deeper than `MAX_SCAN_DEPTH`, which includes a value that contains itself, is refused."""
    found: list[str] = []
    _walk_values(value, 0, found)
    return found
