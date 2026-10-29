"""Pathways Dx search over the sample file (R16). DEC-010 red stub."""

from pathlib import Path


class PathwaysDxFile:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    async def search_pathways_dx(self, text: str, limit: int = 20) -> list[tuple[str, str]]:
        return []
