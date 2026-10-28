"""Process start markers (F10b, DEC-135). A container is labelled with its owner's pid and start
time, so a pid that the operating system has handed to another process cannot keep a leaked
container alive. No Docker needed."""

import os
import subprocess
import sys

from tests.support.proc import parse_start_marker, process_start_marker


def _stat_line(comm: str, state: str = "S", starttime: int = 987654) -> str:
    # pid (comm) state ppid pgrp session tty tpgid flags minflt cminflt majflt cmajflt utime stime
    # cutime cstime priority nice threads itrealvalue starttime ...  (starttime is field 22)
    after_comm = [state, "1", "1", "1", "0", "-1", "4194560"] + ["0"] * 11 + [str(starttime), "0"]
    assert len(after_comm) == 20
    return f"4321 ({comm}) " + " ".join(after_comm) + "\n"


def test_the_marker_is_the_start_time_field_of_proc_stat() -> None:
    assert parse_start_marker(_stat_line("python")) == "987654"


def test_a_command_name_with_spaces_and_brackets_does_not_shift_the_fields() -> None:
    assert parse_start_marker(_stat_line("my (odd) name", starttime=555)) == "555"


def test_a_zombie_is_gone() -> None:
    assert parse_start_marker(_stat_line("python", state="Z")) is None


def test_a_dead_process_is_gone() -> None:
    assert parse_start_marker(_stat_line("python", state="X")) is None


def test_text_that_is_not_a_stat_line_gives_no_marker() -> None:
    assert parse_start_marker("") is None
    assert parse_start_marker("no brackets here") is None
    assert parse_start_marker("1 (short) S 1 2") is None


def test_the_marker_of_this_process_is_stable() -> None:
    first = process_start_marker(os.getpid())
    assert first is not None
    assert first.isdigit()
    assert process_start_marker(os.getpid()) == first


def test_a_process_that_has_exited_has_no_marker() -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()  # reaped, so its /proc entry is gone

    assert process_start_marker(child.pid) is None


def test_a_running_child_has_a_marker() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        marker = process_start_marker(child.pid)
        assert marker is not None
        assert marker.isdigit()
    finally:
        child.kill()
        child.wait()
