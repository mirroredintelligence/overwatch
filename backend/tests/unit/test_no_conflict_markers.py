"""A merge that leaves conflict markers in a tracked text file must fail locally."""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SUFFIXES = {".md", ".py", ".ts", ".tsx", ".json", ".yml", ".yaml", ".toml", ".sh", ".cypher"}
MARKER = re.compile(r"^(<{7}( |$)|>{7}( |$))", re.MULTILINE)


def _tracked_text_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, check=True, capture_output=True
    ).stdout.decode()
    return [
        REPO_ROOT / name
        for name in listed.split("\0")
        if name and Path(name).suffix in SUFFIXES and (REPO_ROOT / name).is_file()
    ]


def test_no_tracked_text_file_holds_a_merge_conflict_marker() -> None:
    held = [
        str(path.relative_to(REPO_ROOT))
        for path in _tracked_text_files()
        if MARKER.search(path.read_text(encoding="utf-8", errors="replace"))
    ]
    assert held == []


def test_the_marker_pattern_matches_a_conflict_and_not_a_table_or_a_rule() -> None:
    assert MARKER.search("a\n<<<<<<< HEAD\nb\n")
    assert MARKER.search("a\n>>>>>>> main\n")
    assert not MARKER.search("| a | b |\n=======\n")
    assert not MARKER.search("x << y\n")
