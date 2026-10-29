"""Message catalogue ids (D15). The meaning of each id is in docs/spec/domain-rules.md section 9.

Ids are stored as `Communication.topic`, so their values never change once a message is sent.

The wording a tenant supplies (TEN-022) is named here: which fields are tenant text, and which ids
take which. A use case loads a tenant's words for those ids with `tenant_text_fields_for`.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Final


class MessageId(StrEnum):
    # Capacity (D15)
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"
    C4 = "C4"
    C5 = "C5"
    C6 = "C6"
    C7 = "C7"
    C8 = "C8"
    C9 = "C9"
    C10 = "C10"
    C11 = "C11"
    C12 = "C12"
    # Bookings (D16)
    B1 = "B1"
    B2 = "B2"
    B3 = "B3"
    B4 = "B4"
    B5 = "B5"
    B6 = "B6"
    B7 = "B7"
    # Invitations (D16)
    I1 = "I1"
    I2 = "I2"
    I3 = "I3"
    # Codes and alerts (D16)
    K1 = "K1"
    K2 = "K2"
    K3 = "K3"
    K4 = "K4"


# The three wording fields a tenant supplies (TEN-022). Each is checked by check_tenant_text.
TENANT_TEXT_FIELD_NAMES: Final = frozenset(
    {"system_name", "referral_system_name", "coordination_team_name"}
)

# Which tenant wording field each id takes. The platform name ("DIUCS") and the sender identity
# are not here: they are not tenant words in the body (TEN-022).
TENANT_TEXT_FIELDS: Final[Mapping[MessageId, frozenset[str]]] = {
    MessageId.I2: frozenset({"system_name"}),
    MessageId.B1: frozenset({"referral_system_name"}),
    MessageId.B2: frozenset({"referral_system_name"}),
    MessageId.K4: frozenset({"coordination_team_name"}),
}


def tenant_text_fields_for(message_id: MessageId) -> frozenset[str]:
    """The tenant wording fields a message takes; empty for every id that prints no tenant words."""
    return TENANT_TEXT_FIELDS.get(MessageId(message_id), frozenset())
