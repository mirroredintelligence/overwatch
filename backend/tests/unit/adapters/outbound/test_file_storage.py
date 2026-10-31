"""The export storage on files (TEN-074): a package is written whole and hashed, a name cannot
leave its package, and a manifest is found by its hash for its own tenant only."""

import hashlib
from pathlib import Path

import pytest

from diucs.adapters.outbound.export_files.file_storage import FileExportStorage
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.tenant_export import MANIFEST_FILE

pytestmark = pytest.mark.asyncio


async def test_a_file_is_written_whole_under_its_tenant_and_package_and_hashed(
    tmp_path: Path,
) -> None:
    storage = FileExportStorage(tmp_path)
    digest = await storage.put("org-a", "export-1", "people/Practitioner.jsonl", b"{}\n")
    assert digest == hashlib.sha256(b"{}\n").hexdigest()
    assert (tmp_path / "org-a/export-1/people/Practitioner.jsonl").read_bytes() == b"{}\n"
    assert not list(tmp_path.rglob("*.part"))  # no half-written file is left


@pytest.mark.parametrize(
    ("tenant", "package", "name"),
    [
        ("org-a", "export-1", "../escape.jsonl"),
        ("org-a", "export-1", "/etc/passwd"),
        ("org-a", "export-1", "a//b.jsonl"),
        ("org-a", "export-1", ""),
        ("org-a", "../x", "f.jsonl"),
        ("org-a", "Export-1", "f.jsonl"),
        ("../other", "export-1", "f.jsonl"),
        ("net-sample", "export-1", "f.jsonl"),
    ],
)
async def test_a_name_that_could_leave_its_package_is_refused_and_nothing_is_written(
    tmp_path: Path, tenant: str, package: str, name: str
) -> None:
    with pytest.raises(ValidationFailed):
        await FileExportStorage(tmp_path).put(tenant, package, name, b"x")
    assert list(tmp_path.rglob("*")) == []


async def test_a_manifest_is_found_by_its_hash_for_its_own_tenant_only(tmp_path: Path) -> None:
    storage = FileExportStorage(tmp_path)
    manifest = b'{"files":[]}'
    await storage.put("org-a", "export-1", MANIFEST_FILE, manifest)
    wanted = hashlib.sha256(manifest).hexdigest()
    assert await storage.has_package("org-a", wanted)
    assert not await storage.has_package("org-b", wanted)
    assert not await storage.has_package("org-a", "0" * 64)
    assert not await storage.has_package("org-c", wanted)  # no directory at all
