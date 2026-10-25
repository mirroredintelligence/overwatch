"""Privacy guard for message text (D17). Red stub: replaced by the implementation commit."""

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


def find_patient_data(text: str) -> list[str]:
    raise NotImplementedError("D17: find_patient_data is not implemented yet")
