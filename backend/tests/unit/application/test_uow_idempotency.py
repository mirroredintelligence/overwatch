"""The one idempotency store that an inbound adapter builds on the application's own unit of work
(KI-35, KI-36, KI-149). It was written three times (link_access, routes_services, routes_board);
the copies could drift, and one had a `put` nothing called. There is one class now, and a scan
keeps it one.
"""

import ast
from pathlib import Path
from types import TracebackType
from typing import Any

from diucs.application.uow_idempotency import UnitOfWorkIdempotency

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "src" / "diucs"


class _Store:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    async def get(self, key: str) -> object | None:
        return self.values.get(key)

    async def put(self, key: str, result: object) -> None:
        self.values[key] = result


class _Uow:
    def __init__(self, store: _Store, log: list[str]) -> None:
        self.idempotency = store
        self._log = log

    async def __aenter__(self) -> _Uow:
        self._log.append("open")
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self._log.append("close")

    async def commit(self) -> None:
        self._log.append("commit")


def _factory(store: _Store, log: list[str]) -> Any:
    return lambda: _Uow(store, log)


async def test_get_reads_the_key_in_a_unit_of_work_of_its_own_and_commits_nothing() -> None:
    store, log = _Store(), []
    store.values["k"] = "kept"

    assert await UnitOfWorkIdempotency(_factory(store, log)).get("k") == "kept"
    assert await UnitOfWorkIdempotency(_factory(store, log)).get("other") is None
    assert "commit" not in log


async def test_put_writes_the_key_and_commits_it() -> None:
    store, log = _Store(), []

    await UnitOfWorkIdempotency(_factory(store, log)).put("k", "result")

    assert store.values == {"k": "result"}
    assert log == ["open", "commit", "close"]


def test_there_is_one_class_of_that_name_in_the_source() -> None:
    found: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef) and node.name.lstrip("_") == "UnitOfWorkIdempotency":
                found.append(str(path.relative_to(PACKAGE_ROOT)))

    assert found == ["application/uow_idempotency.py"]


def test_the_routes_and_the_link_pages_use_the_same_class() -> None:
    from diucs.adapters.inbound.fhir_rest import routes_board, routes_services
    from diucs.application.use_cases import link_access

    assert routes_services.UnitOfWorkIdempotency is UnitOfWorkIdempotency
    assert link_access.UnitOfWorkIdempotency is UnitOfWorkIdempotency
    assert routes_board.UnitOfWorkIdempotency is UnitOfWorkIdempotency
