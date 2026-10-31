"""The Pathways Dx codes from a JSON file (R16).

The file is read once when it is built, and searched by the domain rule. It is a JSON object.
`notice` is text that says what the codes are (the pilot's file says they are not real). `codes`
is a list of {"code", "display"} objects. A file of any other shape is refused with
ValidationFailed when it is loaded, so a bad file stops the process at start-up. The refusal names
the field and never a value (DEC-047). The licensed NHS Pathways list is a configuration change:
point `pathways_dx_file` at it.
"""

import json
from pathlib import Path
from typing import Any, Final

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.scores import PATHWAYS_DX_PATTERN
from diucs.domain.rules.code_search import search_codes

NOTICE_KEY: Final = "notice"
CODES_KEY: Final = "codes"


def load_pathways_dx(path: Path) -> tuple[tuple[str, str], ...]:
    with open(path, encoding="utf-8") as handle:
        document: Any = json.load(handle)
    if not isinstance(document, dict):
        raise ValidationFailed("pathways_dx", "the file must be a JSON object")
    notice = document.get(NOTICE_KEY)
    if type(notice) is not str or not notice.strip():
        raise ValidationFailed("pathways_dx", "the file must say in notice what its codes are")
    codes = document.get(CODES_KEY)
    if not isinstance(codes, list):
        raise ValidationFailed("pathways_dx", "codes must be a list")
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in codes:
        code = item.get("code") if isinstance(item, dict) else None
        display = item.get("display") if isinstance(item, dict) else None
        if type(code) is not str or not code.strip():
            raise ValidationFailed("code", "each entry needs a text code")
        if type(display) is not str or not display.strip():
            raise ValidationFailed("display", "each entry needs a text display")
        if PATHWAYS_DX_PATTERN.fullmatch(code) is None:
            # A score of this code could never be recorded: the list and the shape must agree.
            raise ValidationFailed("code", "a listed code is not of the Pathways Dx code shape")
        if code in seen:
            raise ValidationFailed("code", "a code is listed more than once")
        seen.add(code)
        entries.append((code, display))
    return tuple(entries)


class PathwaysDxFile:
    """The search half of the Terminology port over the Pathways Dx file. Loaded once, here."""

    def __init__(self, path: Path | str) -> None:
        self._entries = load_pathways_dx(Path(path))
        self._codes = frozenset(code for code, _ in self._entries)

    async def search_pathways_dx(self, text: str, limit: int = 20) -> list[tuple[str, str]]:
        return search_codes(self._entries, text, limit)

    async def pathways_dx_listed(self, code: str) -> bool:
        return type(code) is str and code in self._codes
