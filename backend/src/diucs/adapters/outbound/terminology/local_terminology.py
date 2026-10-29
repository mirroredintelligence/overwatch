"""Local terminology (I12): the ODS pilot sample and the local CodeSystem display names.

For the pilot, ODS lookups read `terminology/ods_sample.json` (code, name, active, role, postcode;
role becomes the record's org_type). A code not in it is None. An inactive record is returned as
stored: the caller checks `active`. The live ODS service is an open decision (ods_http.py).

Display names come from the FHIR CodeSystem files in `terminology/codesystems/`, generated from
diucs.domain.codes by backend/scripts/export_codesystems.py and committed. A system or code not in
them has no display. Errors name the field or the file and never a value (DEC-047).
"""

import json
from pathlib import Path
from typing import Any, Final

from diucs.adapters.outbound.terminology.pathways_dx_file import PathwaysDxFile
from diucs.application.ports.outbound.terminology import OdsRecord
from diucs.domain.errors import ValidationFailed

ODS_FILE: Final = "ods_sample.json"
CODESYSTEMS_DIR: Final = "codesystems"


def _ods_key(code: str) -> str:
    return code.strip().upper()


def _load_ods(path: Path) -> dict[str, OdsRecord]:
    with open(path, encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise ValidationFailed("ods", "the ODS sample must be a list of records")
    records: dict[str, OdsRecord] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValidationFailed("ods", f"record {index} is not an object")
        code = row.get("code")
        name = row.get("name")
        active = row.get("active")
        role = row.get("role")
        postcode = row.get("postcode")
        if type(code) is not str or not code.strip():
            raise ValidationFailed("code", f"record {index} has no code")
        if type(name) is not str or type(role) is not str or type(active) is not bool:
            raise ValidationFailed("ods", f"record {index} has a field of the wrong type")
        if postcode is not None and type(postcode) is not str:
            raise ValidationFailed("postcode", f"record {index} has a postcode of the wrong type")
        key = _ods_key(code)
        if key in records:
            raise ValidationFailed("code", f"record {index} repeats an earlier code")
        records[key] = OdsRecord(
            code=key, name=name, active=active, org_type=role, postcode=postcode
        )
    return records


def _load_displays(directory: Path) -> dict[tuple[str, str], str]:
    displays: dict[tuple[str, str], str] = {}
    for path in sorted(directory.glob("*.json")):
        with open(path, encoding="utf-8") as handle:
            document: Any = json.load(handle)
        if not isinstance(document, dict) or document.get("resourceType") != "CodeSystem":
            raise ValidationFailed("codesystem", f"{path.name} is not a CodeSystem")
        url = document.get("url")
        concepts = document.get("concept")
        if type(url) is not str or not isinstance(concepts, list):
            raise ValidationFailed("codesystem", f"{path.name} has no url or concept list")
        for concept in concepts:
            code = concept.get("code") if isinstance(concept, dict) else None
            display = concept.get("display") if isinstance(concept, dict) else None
            if type(code) is not str or type(display) is not str:
                raise ValidationFailed(
                    "concept", f"{path.name} has a concept without code or display"
                )
            if (url, code) in displays:
                raise ValidationFailed("concept", f"{path.name} repeats a code")
            displays[(url, code)] = display
    return displays


class LocalTerminology:
    """The Terminology port over the local files. Each file is read once, in the constructor.

    The Pathways Dx search (R16) reads its own file through PathwaysDxFile, the one loader for that
    file, so the score picker's list is a configuration change to `pathways_dx_file`."""

    def __init__(self, base_dir: Path | str, pathways_dx_file: Path | str) -> None:
        base = Path(base_dir)
        self._ods = _load_ods(base / ODS_FILE)
        self._displays = _load_displays(base / CODESYSTEMS_DIR)
        self._pathways_dx = PathwaysDxFile(pathways_dx_file)

    async def ods_lookup(self, code: str) -> OdsRecord | None:
        key = _ods_key(code)
        return self._ods.get(key) if key else None

    async def display(self, system: str, code: str) -> str | None:
        return self._displays.get((system, code))

    async def search_pathways_dx(self, text: str, limit: int = 20) -> list[tuple[str, str]]:
        return await self._pathways_dx.search_pathways_dx(text, limit)
