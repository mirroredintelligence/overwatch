"""Is a Pathways Dx code on the list (H-85, KI-247): the membership check behind the score write.

Membership is exact: the code as the list holds it, case included, with no trimming. The file
loader refuses a list holding a code the score could never record, so the list and the shape
cannot drift apart (KI-816). Sample values only.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from diucs.adapters.outbound.terminology.local_terminology import LocalTerminology
from diucs.adapters.outbound.terminology.pathways_dx_file import PathwaysDxFile
from diucs.adapters.testing.fixed_terminology import FixedTerminology
from diucs.domain.errors import ValidationFailed

BACKEND = Path(__file__).resolve().parents[5]
SAMPLE = BACKEND / "data" / "pathways_dx_sample.json"
NOTICE = "Sample codes only. These are not real NHS Pathways codes."


def _write(tmp_path: Path, codes: list[dict[str, Any]]) -> Path:
    path = tmp_path / "pathways.json"
    path.write_text(json.dumps({"notice": NOTICE, "codes": codes}), encoding="utf-8")
    return path


def _file(tmp_path: Path) -> PathwaysDxFile:
    return PathwaysDxFile(
        _write(
            tmp_path,
            [
                {"code": "Dx02", "display": "Sample disposition (not a real code)"},
                {"code": "DX99", "display": "Another sample (not a real code)"},
            ],
        )
    )


async def test_a_listed_code_is_listed(tmp_path: Path) -> None:
    assert await _file(tmp_path).pathways_dx_listed("Dx02") is True


@pytest.mark.parametrize("code", ["dx02", "DX02", " Dx02", "Dx02 ", "Dx02\n", "Dx0", "", "Dx", "ZZ99"])
async def test_a_code_not_exactly_on_the_list_is_not_listed(tmp_path: Path, code: str) -> None:
    assert await _file(tmp_path).pathways_dx_listed(code) is False


async def test_a_value_that_is_not_text_is_not_listed(tmp_path: Path) -> None:
    assert await _file(tmp_path).pathways_dx_listed(None) is False  # type: ignore[arg-type]
    assert await _file(tmp_path).pathways_dx_listed(2) is False  # type: ignore[arg-type]


@pytest.mark.parametrize("code", ["D", "Dx-02", "Dx 02", "Dx0123456789ab", "Dx02\n"])
def test_a_list_holding_a_code_the_score_could_never_record_is_refused_at_load(
    tmp_path: Path, code: str
) -> None:
    path = _write(tmp_path, [{"code": code, "display": "Sample (not a real code)"}])

    with pytest.raises(ValidationFailed) as refused:
        PathwaysDxFile(path)

    assert refused.value.field == "code"
    assert code.strip() not in refused.value.message


async def test_the_pilot_sample_list_is_recordable_and_listed() -> None:
    sample = PathwaysDxFile(SAMPLE)

    found = await sample.search_pathways_dx("sample")

    assert found
    for code, _ in found:
        assert await sample.pathways_dx_listed(code) is True


async def test_the_local_terminology_answers_from_the_same_file() -> None:
    terminology = LocalTerminology(BACKEND / "terminology", SAMPLE)

    assert await terminology.pathways_dx_listed("DxSAMPLE01") is True
    assert await terminology.pathways_dx_listed("DxSAMPLE99") is False


async def test_the_fixed_terminology_answers_from_its_table() -> None:
    terminology = FixedTerminology({}, {}, [("DxA1", "Sample (not a real code)")])

    assert await terminology.pathways_dx_listed("DxA1") is True
    assert await terminology.pathways_dx_listed("dxa1") is False
    assert await FixedTerminology({}, {}).pathways_dx_listed("DxA1") is False
