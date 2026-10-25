"""Message catalogue ids (D15). The meaning of each id is in docs/spec/domain-rules.md section 9.

Ids are stored as `Communication.topic`, so their values never change once a message is sent.
"""

from enum import StrEnum


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
