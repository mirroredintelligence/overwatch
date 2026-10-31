"""SMS segment counting (D15): GSM-7 and UCS-2 segment rules for outbound text.

GSM-7 (3GPP TS 23.038): 160 characters in one segment, 153 per segment when concatenated.
Extension characters take two characters each. Any character outside GSM-7 switches the whole
message to UCS-2: 70 UTF-16 code units in one segment, 67 per segment when concatenated.
DEC-034 records the choices made here (form feed is an extension character; empty text is one
segment).
"""

import math
from typing import Final

GSM_SINGLE_SEGMENT: Final = 160
GSM_CONCATENATED_SEGMENT: Final = 153
UCS2_SINGLE_SEGMENT: Final = 70
UCS2_CONCATENATED_SEGMENT: Final = 67

_GSM_EXTENSION: Final = frozenset("\f^{}\\[~]|€")
_GSM_NON_ASCII: Final = frozenset("£¥èéùìòÇØøÅåΔΦΓΛΩΠΨΣΘΞÆæßÉ¡¿ÄÖÑÜ§äöñüà¤")
_ASCII_PRINTABLE: Final = frozenset(chr(code) for code in range(0x20, 0x7F))
_GSM_BASIC: Final = (_ASCII_PRINTABLE - _GSM_EXTENSION) | _GSM_NON_ASCII | frozenset("\n\r")


def _is_gsm7(text: str) -> bool:
    return all(char in _GSM_BASIC or char in _GSM_EXTENSION for char in text)


def sms_segments(text: str) -> int:
    if _is_gsm7(text):
        units = sum(2 if char in _GSM_EXTENSION else 1 for char in text)
        single, concatenated = GSM_SINGLE_SEGMENT, GSM_CONCATENATED_SEGMENT
    else:
        units = len(text.encode("utf-16-be")) // 2
        single, concatenated = UCS2_SINGLE_SEGMENT, UCS2_CONCATENATED_SEGMENT
    if units <= single:
        return 1
    return math.ceil(units / concatenated)
