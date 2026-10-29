"""The migration runner on a recording driver (TEN-005, rules 2 and 6).

The driver here is a scripted stand-in: it shows what the runner handed to the driver (sessions,
write transactions, statements, parameters) and lets a test make a step fail or a loop report a
number of changed rows. It is not a store. The real server is exercised in
tests/integration/graph_store/test_tenant_migrations.py.
"""

import asyncio
import math
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.adapters.outbound.graph_store import migrations as runner
from diucs.adapters.outbound.graph_store.migration_types import (
    MAX_LOOP_ITERATIONS,
    Migration,
    MigrationFailed,
)

_APPLIED = "MATCH (m:Migration) RETURN m.id AS id"
_SECRET = "MATCH (secret:Zzcypher) RETURN secret"
_VALUE = "zz-parameter-value"

Handler = Callable[[dict[str, Any]], list[dict[str, Any]]]


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def data(self) -> list[dict[str, Any]]:
        return self._rows


class _Tx:
    def __init__(self, world: _World, kind: str) -> None:
        self._world = world
        self._kind = kind
        self.statements: list[str] = []

    async def run(
        self, statement: str, parameters: dict[str, Any] | None = None, **kw: Any
    ) -> _Result:
        params = dict(parameters or {}, **kw)
        self.statements.append(statement)
        return _Result(self._world.handle(self._kind, statement, params))


class _Session:
    def __init__(self, world: _World) -> None:
        self._world = world

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def execute_read[T](self, work: Callable[[_Tx], Awaitable[T]]) -> T:
        return await work(_Tx(self._world, "read"))

    async def execute_write[T](self, work: Callable[..., Awaitable[T]], *args: Any) -> T:
        tx = _Tx(self._world, "write")
        self._world.transactions.append(tx)
        return await work(tx, *args)


class _World:
    """The driver. `handlers` answer a statement by its text; `record_error` fails the next
    record write that many times."""

    def __init__(self, applied: set[str] | None = None) -> None:
        self.applied: set[str] = set(applied or ())
        self.handlers: dict[str, Handler] = {}
        self.sessions = 0
        self.transactions: list[_Tx] = []
        self.runs: list[tuple[str, dict[str, Any]]] = []
        self.record_errors = 0

    def session(self, **_: Any) -> _Session:
        self.sessions += 1
        return _Session(self)

    def handle(self, kind: str, statement: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if statement == _APPLIED:
            return [{"id": migration_id} for migration_id in sorted(self.applied)]
        self.runs.append((statement, params))
        if statement.startswith("MERGE (m:Migration"):
            if self.record_errors:
                self.record_errors -= 1
                raise RuntimeError(_SECRET)
            self.applied.add(params["id"])
            return []
        handler = self.handlers.get(statement)
        return handler(params) if handler is not None else []

    def statements(self) -> list[str]:
        return [statement for statement, _ in self.runs]


def _statements(world: _World) -> list[str]:
    return [s for s in world.statements() if not s.startswith("MERGE (m:Migration")]


async def test_a_statement_only_migration_runs_each_statement_in_its_own_write_transaction() -> (
    None
):
    world = _World()
    plan = [Migration("0090_a", ("S1", "S2")), Migration("0091_b", ("S3",))]

    applied = await runner.apply_migrations(world, plan)  # type: ignore[arg-type]

    assert applied == ["0090_a", "0091_b"]
    assert world.statements()[0:2] == ["S1", "S2"]
    assert world.statements()[2].startswith("MERGE (m:Migration")
    assert world.statements()[3] == "S3"
    # Every write transaction ran exactly one statement: the statement, or the record.
    assert [len(tx.statements) for tx in world.transactions] == [1] * 5
    assert world.applied == {"0090_a", "0091_b"}


async def test_the_record_is_written_last_and_in_its_own_transaction() -> None:
    world = _World()

    await runner.apply_migrations(world, [Migration("0090_a", ("S1",), loops=("L1",))])  # type: ignore[arg-type]

    last = world.transactions[-1]
    assert [s.startswith("MERGE (m:Migration") for s in last.statements] == [True]
    assert world.runs[-1][1]["id"] == "0090_a"


async def test_migrations_already_recorded_are_skipped_and_the_new_ones_are_returned_in_order() -> (
    None
):
    world = _World(applied={"0090_a"})
    plan = [
        Migration("0090_a", ("S1",)),
        Migration("0091_b", ("S2",)),
        Migration("0092_c", ("S3",)),
    ]

    applied = await runner.apply_migrations(world, plan)  # type: ignore[arg-type]

    assert applied == ["0091_b", "0092_c"]
    assert "S1" not in world.statements()
    assert await runner.apply_migrations(world, plan) == []  # type: ignore[arg-type]


async def test_a_schema_statement_receives_the_parameters_of_its_migration() -> None:
    world = _World()
    plan = [Migration("0090_a", ("S1",), params={"x": 1})]

    await runner.apply_migrations(world, plan)  # type: ignore[arg-type]

    assert world.runs[0] == ("S1", {"x": 1})


# Loop steps


def _stamper(total: int) -> tuple[Handler, list[int]]:
    """A loop that changes at most `$batch` of `total` rows per call, as the stamp does."""
    remaining = [total]
    calls: list[int] = []

    def handle(params: dict[str, Any]) -> list[dict[str, Any]]:
        take = min(params["batch"], remaining[0])
        remaining[0] -= take
        calls.append(take)
        return [{"changed": take}]

    return handle, calls


async def test_a_loop_repeats_with_the_batch_and_the_parameters_until_nothing_changes() -> None:
    world = _World()
    handler, calls = _stamper(7)
    world.handlers["LOOP"] = handler
    plan = [Migration("0090_a", loops=("LOOP",), params={"defaultTenant": "t"}, batch=3)]

    await runner.apply_migrations(world, plan)  # type: ignore[arg-type]

    assert calls == [3, 3, 1, 0]
    loop_runs = [params for statement, params in world.runs if statement == "LOOP"]
    assert len(loop_runs) == math.ceil(7 / 3) + 1
    assert all(p == {"defaultTenant": "t", "batch": 3} for p in loop_runs)


async def test_every_repetition_of_a_loop_is_its_own_session_and_transaction() -> None:
    world = _World()
    handler, _ = _stamper(7)
    world.handlers["LOOP"] = handler
    plan = [Migration("0090_a", loops=("LOOP",), batch=3)]

    await runner.apply_migrations(world, plan)  # type: ignore[arg-type]

    repetitions = math.ceil(7 / 3) + 1
    # One session reads the applied ids, one per repetition, one for the record.
    assert world.sessions == 1 + repetitions + 1
    assert [len(tx.statements) for tx in world.transactions] == [1] * (repetitions + 1)


def _run_loop(total: int, batch: int) -> tuple[list[int], int]:
    world = _World()
    handler, calls = _stamper(total)
    world.handlers["LOOP"] = handler
    asyncio.run(runner.apply_migrations(world, [Migration("0090_a", loops=("LOOP",), batch=batch)]))  # type: ignore[arg-type]
    return calls, sum(1 for s in world.statements() if s == "LOOP")


@settings(max_examples=60, deadline=None)
@given(total=st.integers(min_value=0, max_value=60), batch=st.integers(min_value=1, max_value=20))
def test_a_loop_changes_every_row_in_ceil_n_over_batch_plus_one_repetitions(
    total: int, batch: int
) -> None:
    calls, repetitions = _run_loop(total, batch)
    assert sum(calls) == total
    assert repetitions == math.ceil(total / batch) + 1
    assert calls[-1] == 0
    assert all(0 < c <= batch for c in calls[:-1])


async def test_the_statements_of_a_migration_run_before_its_loops() -> None:
    world = _World()
    handler, _ = _stamper(1)
    world.handlers["LOOP"] = handler

    await runner.apply_migrations(world, [Migration("0090_a", ("S1",), ("LOOP",))])  # type: ignore[arg-type]

    assert _statements(world)[0] == "S1"
    assert _statements(world)[1] == "LOOP"


# Failure


async def test_a_failing_statement_stops_the_migration_and_names_the_step_and_the_class() -> None:
    world = _World()

    def boom(_: dict[str, Any]) -> list[dict[str, Any]]:
        raise RuntimeError(f"{_SECRET} {_VALUE}")

    world.handlers["S2"] = boom
    plan = [Migration("0090_a", ("S1", "S2", "S3")), Migration("0091_b", ("S4",))]

    with pytest.raises(MigrationFailed) as caught:
        await runner.apply_migrations(world, plan)  # type: ignore[arg-type]

    message = str(caught.value)
    assert message == "migration 0090_a failed at statement 2: RuntimeError"
    assert _SECRET not in message and _VALUE not in message and "S2" not in message
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert _statements(world) == ["S1", "S2"]  # earlier ran, later and the next migration did not
    assert world.applied == set()


@pytest.mark.parametrize(
    "answer",
    [
        [],
        [{}],
        [{"changed": "3"}],
        [{"changed": True}],
        [{"changed": 1.0}],
        [{"changed": None}],
        [{"changed": 1}, {"changed": 1}],
    ],
)
async def test_a_loop_that_does_not_report_one_integer_changed_fails(
    answer: list[dict[str, Any]],
) -> None:
    world = _World()
    world.handlers["LOOP"] = lambda _: answer
    plan = [Migration("0090_a", ("S1",), ("LOOP",)), Migration("0091_b", ("S2",))]

    with pytest.raises(MigrationFailed) as caught:
        await runner.apply_migrations(world, plan)  # type: ignore[arg-type]

    message = str(caught.value)
    assert message.startswith("migration 0090_a failed at loop 1: ")
    assert "LOOP" not in message
    assert world.applied == set()
    assert "S2" not in world.statements()


async def test_a_loop_that_never_reaches_zero_stops_at_the_cap_and_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "MAX_LOOP_ITERATIONS", 5)
    world = _World()
    world.handlers["LOOP"] = lambda _: [{"changed": 1}]

    with pytest.raises(MigrationFailed, match=r"migration 0090_a failed at loop 1: "):
        await runner.apply_migrations(world, [Migration("0090_a", loops=("LOOP",))])  # type: ignore[arg-type]

    assert world.statements().count("LOOP") == 5
    assert world.applied == set()


def test_the_cap_is_ten_thousand_repetitions() -> None:
    assert MAX_LOOP_ITERATIONS == 10_000


async def test_a_failing_loop_names_its_position_among_the_loops() -> None:
    world = _World()
    handler, _ = _stamper(0)
    world.handlers["LOOP1"] = handler

    def boom(_: dict[str, Any]) -> list[dict[str, Any]]:
        raise ValueError(_SECRET)

    world.handlers["LOOP2"] = boom

    with pytest.raises(MigrationFailed) as caught:
        await runner.apply_migrations(world, [Migration("0090_a", loops=("LOOP1", "LOOP2"))])  # type: ignore[arg-type]

    assert str(caught.value) == "migration 0090_a failed at loop 2: ValueError"


async def test_a_crash_before_the_record_is_unrecorded_and_a_rerun_finishes_it() -> None:
    world = _World()
    world.record_errors = 1
    plan = [Migration("0090_a", ("S1",), ("LOOP",))]
    handler, _ = _stamper(0)
    world.handlers["LOOP"] = handler

    with pytest.raises(MigrationFailed) as caught:
        await runner.apply_migrations(world, plan)  # type: ignore[arg-type]

    assert str(caught.value) == "migration 0090_a failed at record: RuntimeError"
    assert _SECRET not in str(caught.value)
    assert world.applied == set()
    assert _statements(world) == ["S1", "LOOP"]

    assert await runner.apply_migrations(world, plan) == ["0090_a"]  # type: ignore[arg-type]
    assert _statements(world) == ["S1", "LOOP", "S1", "LOOP"]  # repeated, idempotent
    assert world.applied == {"0090_a"}


# The default list


async def test_without_a_second_argument_the_runner_uses_the_module_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "MIGRATIONS", [Migration("0090_a", ("S1",))])
    world = _World()

    assert await runner.apply_migrations(world) == ["0090_a"]  # type: ignore[arg-type]
    assert _statements(world) == ["S1"]


async def test_with_a_list_the_runner_uses_that_list_and_not_the_module_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "MIGRATIONS", [Migration("0090_a", ("S1",))])
    world = _World()

    assert await runner.apply_migrations(world, [Migration("0091_b", ("S2",))]) == ["0091_b"]  # type: ignore[arg-type]
    assert _statements(world) == ["S2"]
