"""Recording stand-in for the export storage (TEN-074): keeps every file of every package in
memory, answers with the real SHA-256 of what it was given, and can be told to fail the next put,
so a test can show that an export that did not arrive whole is not acknowledged."""

import hashlib

from diucs.domain.rules.tenant_export import MANIFEST_FILE


class MemoryExportStorage:
    def __init__(self) -> None:
        self.files: dict[tuple[str, str, str], bytes] = {}
        self.fail_next = False

    async def put(self, tenant_id: str, package_id: str, name: str, content: bytes) -> str:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("the export storage is down")
        self.files[(tenant_id, package_id, name)] = bytes(content)
        return hashlib.sha256(content).hexdigest()

    async def has_package(self, tenant_id: str, manifest_hash: str) -> bool:
        return any(
            owner == tenant_id
            and name == MANIFEST_FILE
            and hashlib.sha256(content).hexdigest() == manifest_hash
            for (owner, _, name), content in self.files.items()
        )

    def names(self, tenant_id: str, package_id: str) -> list[str]:
        return sorted(n for (t, p, n) in self.files if t == tenant_id and p == package_id)
