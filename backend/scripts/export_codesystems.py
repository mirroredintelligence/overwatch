"""Export the local FHIR CodeSystem resources from diucs.domain.codes (I12).

Run from backend/: `uv run python scripts/export_codesystems.py`. It writes one file per local
code system to terminology/codesystems/. The files are committed; a test fails when they differ
from a fresh export, so a change to the codes that is not exported is caught.
"""

import json
from pathlib import Path
from typing import Any

from diucs.domain.codes import CODE_SYSTEM_NAMES, code_system_url
from diucs.domain.codes import display as member_display

TERMINOLOGY_DIR = Path(__file__).resolve().parents[1] / "terminology" / "codesystems"


def export(out_dir: Path) -> list[Path]:
    """Write every local CodeSystem into out_dir and return the paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for enum_cls, name in CODE_SYSTEM_NAMES.items():
        members = sorted(enum_cls, key=lambda member: member.value)
        concepts: list[dict[str, str]] = [
            {"code": member.value, "display": member_display(member)} for member in members
        ]
        document: dict[str, Any] = {
            "resourceType": "CodeSystem",
            "id": name,
            "url": code_system_url(name),
            "name": name,
            "status": "active",
            "content": "complete",
            "count": len(concepts),
            "concept": concepts,
        }
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for path in export(TERMINOLOGY_DIR):
        print(path.name)
