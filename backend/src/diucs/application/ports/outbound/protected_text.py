"""Outbound port: the protected text store (P20, U40, U41).

Free text from safety concerns, problem reports and clinical notes is written here and never into
the readable graph. A caller keeps the handle, never the text. Adapter: Neo4jProtectedTextStore
(graph_store/protected_text_store.py).
"""

from typing import Protocol


class ProtectedTextStore(Protocol):
    async def put(self, kind: str, about_id: str, text: str) -> str:
        """Store the text and return its handle. `kind` is safety-concern, problem-report or
        clinical-note. Text longer than 280 characters raises ValidationFailed."""
        ...

    async def get(self, handle: str) -> str | None:
        """The text of this handle in the bound tenant, or None."""
        ...
