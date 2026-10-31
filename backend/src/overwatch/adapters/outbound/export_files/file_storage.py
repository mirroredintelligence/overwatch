"""The export storage on the local file system (TEN-074, DEC-969).

`FileExportStorage` writes a tenant's export package under one directory the operator names:
`<root>/<tenant id>/<package id>/<file name>`, a file at a time, atomically (written beside the
target and renamed, so a package never holds half a file), and answers with the SHA-256 of what it
wrote. The names it will write are checked: a tenant id that is a valid tenant id, a package id of
lower-case letters, digits and hyphens, and a file path of plain segments (no `..`, no absolute
path, no empty segment), so a name cannot leave its package. The operator hands the directory to
the tenant by whatever route the agreement names; an object-store adapter is a later swap behind
the same port.

It reads no tenant's data.
"""

import hashlib
import os
import re
from pathlib import Path
from typing import Final

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant import check_tenant_id
from diucs.domain.rules.tenant_export import MANIFEST_FILE

_PACKAGE: Final = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")
_SEGMENT: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}")


def _checked_path(tenant_id: str, package_id: str, name: str) -> Path:
    check_tenant_id(tenant_id)
    if type(package_id) is not str or _PACKAGE.fullmatch(package_id) is None:
        raise ValidationFailed("package_id", "is not a valid package id")
    segments = name.split("/") if type(name) is str else []
    if not segments or any(_SEGMENT.fullmatch(s) is None or s in (".", "..") for s in segments):
        raise ValidationFailed("name", "is not a valid file name")
    return Path(tenant_id, package_id, *segments)


class FileExportStorage:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    async def put(self, tenant_id: str, package_id: str, name: str, content: bytes) -> str:
        target = self._root / _checked_path(tenant_id, package_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        with partial.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        partial.replace(target)
        return hashlib.sha256(content).hexdigest()

    async def has_package(self, tenant_id: str, manifest_hash: str) -> bool:
        check_tenant_id(tenant_id)
        base = self._root / tenant_id
        if not base.is_dir():
            return False
        for manifest in base.glob(f"*/{MANIFEST_FILE}"):
            if hashlib.sha256(manifest.read_bytes()).hexdigest() == manifest_hash:
                return True
        return False
