import asyncio
from pathlib import Path

import pytest

import diucs

pytest_plugins = ["pytester"]


def test_package_version() -> None:
    assert diucs.__version__ == "0.1.0"


async def test_async_test_runs_without_decorator() -> None:
    result = await asyncio.sleep(0, result="done")
    assert result == "done"


def test_integration_directory_gets_marker(pytester: pytest.Pytester) -> None:
    conftest_source = (Path(__file__).parents[1] / "conftest.py").read_text(encoding="utf-8")
    pytester.makeini(
        "[pytest]\nasyncio_mode = auto\nasyncio_default_fixture_loop_scope = function\n"
        "markers =\n    integration: needs docker\n"
    )
    pytester.mkdir("tests")
    pytester.mkdir("tests/integration")
    pytester.mkdir("tests/unit")
    (pytester.path / "tests" / "conftest.py").write_text(conftest_source, encoding="utf-8")
    pytester.makepyfile(
        **{
            "tests/integration/test_probe_integration": (
                "def test_probe(request):\n"
                "    assert request.node.get_closest_marker('integration') is not None\n"
            ),
            "tests/unit/test_probe_unit": (
                "def test_probe(request):\n"
                "    assert request.node.get_closest_marker('integration') is None\n"
            ),
        }
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=2)


def test_integration_probe_runs_without_docker(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An unreachable Docker must not stop a run of tests that never use Neo4j.
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:1")
    conftest_source = (Path(__file__).parents[1] / "conftest.py").read_text(encoding="utf-8")
    pytester.makeini(
        "[pytest]\nasyncio_mode = auto\nasyncio_default_fixture_loop_scope = session\n"
        "markers =\n    integration: needs docker\n"
    )
    pytester.mkdir("tests")
    pytester.mkdir("tests/integration")
    (pytester.path / "tests" / "conftest.py").write_text(conftest_source, encoding="utf-8")
    pytester.makepyfile(
        **{"tests/integration/test_probe_integration": "def test_probe():\n    assert True\n"}
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)
