"""The Pathways Dx file adapter (R16): read once, searched through the domain rule.

The sample file is the one the pilot ships. Its codes are not real, and every display says so.
Sample values only.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from diucs.adapters.outbound.terminology.pathways_dx_file import PathwaysDxFile
from diucs.domain.errors import ValidationFailed

SAMPLE = Path(__file__).resolve().parents[5] / "data" / "pathways_dx_sample.json"
NOTICE = "Sample codes only. These are not real NHS Pathways codes."


def _write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "pathways.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _document(codes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"notice": NOTICE, "codes": codes}


async def test_a_part_of_the_display_finds_the_entry_ignoring_case(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _document(
            [
                {"code": "DxSAMPLE02", "display": "Breathing check (not a real code)"},
                {"code": "DxSAMPLE10", "display": "Chest pain (not a real code)"},
            ]
        ),
    )

    found = await PathwaysDxFile(path).search_pathways_dx("CHEST")

    assert found == [("DxSAMPLE10", "Chest pain (not a real code)")]


async def test_the_file_is_read_once_when_the_adapter_is_built(tmp_path: Path) -> None:
    path = _write(tmp_path, _document([{"code": "DxSAMPLE01", "display": "Sample disposition 1"}]))
    terminology = PathwaysDxFile(path)
    path.unlink()

    assert await terminology.search_pathways_dx("sample") == [
        ("DxSAMPLE01", "Sample disposition 1")
    ]


async def test_a_search_returns_at_most_twenty_in_code_order(tmp_path: Path) -> None:
    codes = [
        {"code": f"DxT{n:02d}", "display": f"Test disposition {n}"} for n in reversed(range(25))
    ]
    path = _write(tmp_path, _document(codes))

    found = await PathwaysDxFile(path).search_pathways_dx("test")

    assert [code for code, _ in found] == [f"DxT{n:02d}" for n in range(20)]


async def test_the_sample_file_states_that_its_codes_are_not_real() -> None:
    document = json.loads(SAMPLE.read_text(encoding="utf-8"))

    assert "not real" in document["notice"].lower()


async def test_every_sample_entry_is_marked_as_not_real() -> None:
    found = await PathwaysDxFile(SAMPLE).search_pathways_dx("not a real code", limit=50)

    assert len(found) == 10
    assert all(code.startswith("DxSAMPLE") for code, _ in found)


@pytest.mark.parametrize(
    "document",
    [
        [{"code": "DxSAMPLE01", "display": "Sample disposition 1"}],
        {"codes": [{"code": "DxSAMPLE01", "display": "Sample disposition 1"}]},
        _document([{"code": "DxSAMPLE01"}]),
        _document([{"code": 1, "display": "Sample disposition 1"}]),
        _document(
            [{"code": "DxSAMPLE01", "display": "one"}, {"code": "DxSAMPLE01", "display": "two"}]
        ),
    ],
    ids=["a-list", "no-notice", "no-display", "code-not-text", "repeated-code"],
)
def test_a_file_of_the_wrong_shape_is_refused(tmp_path: Path, document: Any) -> None:
    path = _write(tmp_path, document)

    with pytest.raises(ValidationFailed):
        PathwaysDxFile(path)


def test_a_refusal_does_not_name_the_code_it_found_wrong(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _document(
            [{"code": "DxSAMPLE07", "display": "one"}, {"code": "DxSAMPLE07", "display": "two"}]
        ),
    )

    with pytest.raises(ValidationFailed) as error:
        PathwaysDxFile(path)

    assert "DxSAMPLE07" not in str(error.value)
