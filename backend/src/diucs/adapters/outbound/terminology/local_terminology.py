"""Local terminology: the ODS pilot sample and the local CodeSystem files (I12). STUB."""

from pathlib import Path

from diucs.application.ports.outbound.terminology import OdsRecord


class LocalTerminology:
    def __init__(self, base_dir: Path | str) -> None:
        raise NotImplementedError

    async def ods_lookup(self, code: str) -> OdsRecord | None:
        raise NotImplementedError

    async def display(self, system: str, code: str) -> str | None:
        raise NotImplementedError
