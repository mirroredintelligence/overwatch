"""Local terminology (I12): the ODS pilot sample, the CodeSystem display and the export sync.

No Docker and no network. The committed CodeSystem files are checked against a fresh export, so a
change to diucs.domain.codes that is not exported fails here.
"""

from pathlib import Path

import pytest

from diucs.adapters.outbound.terminology.local_terminology import LocalTerminology
from diucs.domain.codes import code_system_url
from scripts.export_codesystems import export

BACKEND = Path(__file__).resolve().parents[5]
TERMINOLOGY = BACKEND / "terminology"
PATHWAYS_DX = BACKEND / "data" / "pathways_dx_sample.json"


@pytest.fixture
def terminology() -> LocalTerminology:
    return LocalTerminology(TERMINOLOGY, PATHWAYS_DX)


async def test_the_pathways_dx_search_reads_the_sample_file(terminology: LocalTerminology) -> None:
    found = await terminology.search_pathways_dx("not a real code", 20)

    assert len(found) == 10
    assert all(code.startswith("DxSAMPLE") for code, _ in found)


async def test_an_ods_lookup_returns_the_sample_record(terminology: LocalTerminology) -> None:
    record = await terminology.ods_lookup("RDY")

    assert record is not None
    assert record.code == "RDY"
    assert record.active is True
    assert record.postcode is not None


async def test_an_unknown_ods_code_is_none(terminology: LocalTerminology) -> None:
    assert await terminology.ods_lookup("XXX") is None


async def test_an_inactive_ods_record_is_returned_as_stored_for_the_caller_to_check(
    terminology: LocalTerminology,
) -> None:
    record = await terminology.ods_lookup("RDZ")

    assert record is not None
    assert record.active is False


async def test_a_display_comes_from_the_local_codesystem_file(
    terminology: LocalTerminology,
) -> None:
    assert await terminology.display(code_system_url("status"), "limited") == "Limited"


async def test_an_unknown_code_or_system_has_no_display(terminology: LocalTerminology) -> None:
    assert await terminology.display(code_system_url("status"), "no-such-code") is None
    assert await terminology.display("https://example.test/CodeSystem/none", "limited") is None


def test_the_committed_codesystem_files_match_a_fresh_export(tmp_path: Path) -> None:
    fresh = export(tmp_path)
    committed = sorted((TERMINOLOGY / "codesystems").glob("*.json"))

    assert sorted(path.name for path in fresh) == [path.name for path in committed]
    for path in committed:
        assert (tmp_path / path.name).read_bytes() == path.read_bytes(), path.name
