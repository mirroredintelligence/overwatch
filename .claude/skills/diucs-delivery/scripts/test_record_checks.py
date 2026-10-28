"""Tests for record_checks.py (DEC-141): exit codes are recorded as they happened, tables are exact."""

import record_checks as rc


def fake_runner(codes: dict[str, int]):
    def run(command: str, cwd: str) -> tuple[int, str]:
        return codes.get(command, 0), f"output of {command}\nlast line of {command}\n"

    return run


def test_exit_codes_are_recorded_as_they_happened() -> None:
    commands = [("lint", "ruff check ."), ("types", "mypy src")]

    results = rc.run_commands(commands, "backend", fake_runner({"mypy src": 1}))

    assert [(r.label, r.exit_code) for r in results] == [("lint", 0), ("types", 1)]
    assert results[1].summary == "last line of mypy src"


def test_the_table_names_the_commit_and_the_tree_state() -> None:
    results = [rc.Result("lint", "ruff check .", 0, "All checks passed!")]

    table = rc.render_table(results, "abc1234", True, "2026-10-28 18:00 UTC")

    assert "on `abc1234` (dirty working tree)" in table
    assert "| lint | `ruff check .` | 0 | All checks passed! |" in table


def test_a_pipe_in_the_last_line_cannot_break_the_table() -> None:
    results = [rc.Result("t", "cmd", 0, "a | b")]

    assert "a / b" in rc.render_table(results, "x", False, "now")


def test_a_missing_section_is_appended() -> None:
    assert rc.replace_section("# Title\n\ntext\n", "Checks", "body\n") == "# Title\n\ntext\n\n## Checks\nbody\n"


def test_a_section_in_the_middle_is_replaced_and_its_neighbours_are_kept() -> None:
    text = "# T\n\n## Checks\nold\n\n## Next\nkeep\n"

    out = rc.replace_section(text, "Checks", "new\n")

    assert out == "# T\n\n## Checks\nnew\n\n## Next\nkeep\n"


def test_the_last_section_is_replaced() -> None:
    assert rc.replace_section("# T\n\n## Checks\nold\n", "Checks", "new\n") == "# T\n\n## Checks\nnew\n"


def test_the_script_exits_non_zero_when_any_check_failed(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(rc, "run_shell", fake_runner({"uv run ruff check .": 1}))
    monkeypatch.setattr(rc, "git", lambda args, cwd: "")

    status = rc.main(["--cwd", str(tmp_path)])

    out = capsys.readouterr().out
    assert status == 1
    assert "| lint | `uv run ruff check .` | 1 | last line of uv run ruff check . |" in out
    assert "| types | `uv run mypy src` | 0 |" in out


def test_the_script_exits_zero_when_every_check_passed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(rc, "run_shell", fake_runner({}))
    monkeypatch.setattr(rc, "git", lambda args, cwd: "")

    assert rc.main(["--cwd", str(tmp_path)]) == 0
