"""The export storage and the platform's purge record on the local file system (TEN-074, DEC-969,
DEC-970).

`FileExportStorage` writes a tenant's export package under one directory the operator names:
`<root>/<tenant id>/<package id>/<file name>`, a file at a time, atomically (written beside the
target and renamed, so a package never holds half a file), and answers with the SHA-256 of what it
wrote. The names it will write are checked: a tenant id that is a valid tenant id, a package id of
lower-case letters, digits and hyphens, and a file path of plain segments (no `..`, no absolute
path, no empty segment), so a name cannot leave its package. The operator hands the directory to
the tenant by whatever route the agreement names; an object-store adapter is a later swap behind
the same port.

`FilePlatformAudit` is the platform's own chain until it has a scope (DEC-529): an append-only JSON
lines file, one entry a line, flushed and synced before `append` returns, so the purge's tombstone
is on disk before anything is deleted. It is not a hash chain; the entry carries the head of the
tenant's chain it records. Neither adapter reads a tenant's data.
"""

import hashlib
import json
import os
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from diucs.application.ports.outbound.platform_audit import PlatformAuditEntry
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


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError("not serialisable")


class FilePlatformAudit:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    async def append(self, entry: PlatformAuditEntry) -> None:
        line = json.dumps(
            asdict(entry), sort_keys=True, separators=(",", ":"), default=_json_default
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
