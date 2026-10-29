"""Shift lead routes over HTTP (R08, U15, U16). Stub: written in the implement step."""

from typing import Final

SETUP_PATH: Final = "/HealthcareService/$setup"
CHANGE_NUMBER_PATH: Final = "/PractitionerRole/{role_id}/$change-number"


def number_ending(mobile: str) -> str:
    raise NotImplementedError
