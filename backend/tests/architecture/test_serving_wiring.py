"""Architecture test for the serving wiring of the tenant zone (KI-415, B2 task 1).

`ReportCapacity` and `ConfirmCapacity` write the times of the echo in the tenant's own zone, read
from the tenant directory, but a use case built with no zone source falls back to London for every
tenant. So every place that builds one for the serving process (the routes, the link pages, the
worker) must name its zone source. The scan reads the real source under backend/src/diucs with
`ast`; it is also run on small strings, so a scanner that stops seeing what it should fails here.
"""

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "diucs"
ZONED = frozenset({"ReportCapacity", "ConfirmCapacity"})
# The use cases themselves and the tests' rigs may build one with the London default.
POSITION_OF_ZONES = 4  # (uow_factory, clock, ids, idempotency, zones)


def unzoned_constructions(source: str) -> list[int]:
    """The line numbers of every `ReportCapacity(...)` or `ConfirmCapacity(...)` call that names no
    zone source: no `zones=` keyword and no fifth positional argument."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name not in ZONED:
            continue
        named = any(keyword.arg == "zones" for keyword in node.keywords)
        if not named and len(node.args) <= POSITION_OF_ZONES:
            lines.append(node.lineno)
    return lines


def test_the_scanner_sees_an_unzoned_construction() -> None:
    assert unzoned_constructions("ReportCapacity(a, b, c, d)\nConfirmCapacity(a, b, c, d)") == [1, 2]


def test_the_scanner_accepts_a_zone_by_keyword_or_by_position() -> None:
    source = "ReportCapacity(a, b, c, d, zones=z)\nConfirmCapacity(a, b, c, d, z)"

    assert unzoned_constructions(source) == []


def test_the_scanner_ignores_other_calls() -> None:
    assert unzoned_constructions("Other(a, b, c, d)\nx.ReportCapacity(a)") == []


@pytest.mark.parametrize(
    "folder", ["adapters/inbound", "bootstrap"], ids=lambda folder: folder.replace("/", ".")
)
def test_every_serving_construction_names_its_zone_source(folder: str) -> None:
    found: dict[str, list[int]] = {}
    for path in sorted((PACKAGE_ROOT / folder).rglob("*.py")):
        lines = unzoned_constructions(path.read_text(encoding="utf-8"))
        if lines:
            found[str(path.relative_to(PACKAGE_ROOT))] = lines

    assert found == {}, f"built with the London default: {found}"
