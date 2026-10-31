"""Network settings (TEN-051, DEC-541): what the network view needs that belongs to no member.

The name of the system the network board is called in wording (for example in a message or a
heading), the name of the pathway, and the time zone in which the network board reads the opening
hours it is shown. A projection carries no zone of its own (the allowlist has none, DEC-270), so the
network reads hours in the network's zone; a member's own board keeps reading them in the member's
tenant zone (TEN-026).

Pure and fail closed: a name is plain text of 1 to 60 characters that passes the privacy guard
(no postcode, NHS-number shape or titled name) and holds at most six digits (no phone number),
and the zone is on the tenant zone allow-list. A refusal names the field and never the value.
"""

import re
from dataclasses import dataclass
from typing import Final

from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.privacy_guard import find_patient_data
from diucs.domain.model.tenant import check_time_zone

NAME_MAX_LENGTH: Final = 60
# A name has no run of digits that could be a telephone number: the guard reads postcodes,
# NHS-number shapes and titled names, not a bare phone number, so the limit is here.
MAX_DIGITS: Final = 6
_NAME: Final = re.compile(r"[\w &'()./,:+·-]+")
NAME_MESSAGE: Final = "must be plain text of 1 to 60 characters"


def _name(value: object, field: str) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= NAME_MAX_LENGTH
        or _NAME.fullmatch(value) is None
        or find_patient_data(value)
        or sum(character.isdigit() for character in value) > MAX_DIGITS
    ):
        raise ValidationFailed(field, NAME_MESSAGE)
    return value


@dataclass(frozen=True, slots=True)
class NetworkSettings:
    system_name: str
    pathway_name: str
    time_zone: str

    def __post_init__(self) -> None:
        _name(self.system_name, "system_name")
        _name(self.pathway_name, "pathway_name")
        check_time_zone(self.time_zone)
