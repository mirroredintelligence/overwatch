"""The plain words of the needs: one table, used wherever a need is printed (DEC-062 item 2).

A need is stored as its `NeedCategory` code (`fall-no-injury`) and printed in plain words ("fall, no
injury"), never as the code. The booking messages B1 to B3, the booking pages, the clinical advice
notice and the case summary all take their words from `NEED_WORDS`, so one change is one edit and
the pages cannot drift from the messages (KI-650, H-489).

Several needs join in the order given: the last with " and ", the others with ", " ("wound care,
IV therapy and infection or isolation"). No need is left off (DEC-1150). [ASSUMED] wording: the
labels are the owner's of DEC-062; the clinical safety officer and information governance review
them with the rest of the printed wording (DEC-1100, Q2).

Pure: no I/O.
"""

import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final

from diucs.domain.codes import NeedCategory
from diucs.domain.errors import ValidationFailed

NEED_WORDS: Final[Mapping[NeedCategory, str]] = MappingProxyType(
    {
        NeedCategory.FALL_NO_INJURY: "fall, no injury",
        NeedCategory.FRAILTY: "frailty",
        NeedCategory.WOUND_CARE: "wound care",
        NeedCategory.IV_THERAPY: "IV therapy",
        NeedCategory.PALLIATIVE: "palliative care",
        NeedCategory.DEMENTIA: "dementia",
        NeedCategory.SUSPECTED_FRACTURE: "suspected fracture",
        NeedCategory.HEAD_INJURY_ANTICOAGULANTS: "head injury on anticoagulants",
        NeedCategory.INFECTION_ISOLATION: "infection or isolation",
    }
)
"""The plain words of each need category."""

_LABEL: Final = "|".join(
    re.escape(label) for label in sorted(NEED_WORDS.values(), key=len, reverse=True)
)
_JOINED: Final = re.compile(rf"(?:{_LABEL})(?:, (?:{_LABEL}))*(?: and (?:{_LABEL}))?")


def need_words(needs: Sequence[NeedCategory]) -> str:
    """The needs in plain words, in the order given. A case with no need is incomplete."""
    if not needs:
        raise ValidationFailed("needs", "an open case has at least one need")
    labels = [NEED_WORDS[need] for need in needs]
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def is_need_words(value: object) -> bool:
    """True when `value` is exactly what `need_words` can write: labels from the table, joined as
    above. Raw codes, free text and anything else are refused, so no patient data can ride in a need
    field."""
    return isinstance(value, str) and _JOINED.fullmatch(value) is not None
