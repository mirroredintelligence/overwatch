"""Process start markers (F10b, DEC-135). A container is labelled with its owner's pid and start
time, so a pid that the operating system has handed to another process cannot keep a leaked
container alive. No Docker needed."""

import errno
import os
import re
import subprocess
import sys

import pytest

from tests.support import proc as proc_module
from tests.support.proc import (
    ProcessUnreadable,
    boot_id,
    parse_start_marker,
    pid_namespace,
    process_start_marker,
)


def _stat_line(comm: str, state: str = "S", starttime: int | str = 987654) -> str:
    # pid (comm) state ppid pgrp session tty tpgid flags minflt cminflt majflt cmajflt utime stime
    # cutime cstime priority nice threads itrealvalue starttime ...  (starttime is field 22)
    after_comm = [state, "1", "1", "1", "0", "-1", "4194560"] + ["0"] * 12 + [str(starttime), "0"]
    assert len(after_comm) == 21
    return f"4321 ({comm}) " + " ".join(after_comm) + "\n"


def test_the_marker_is_the_start_time_field_of_proc_stat() -> None:
    assert parse_start_marker(_stat_line("python")) == "987654"


def test_a_command_name_with_spaces_and_brackets_does_not_shift_the_fields() -> None:
    assert parse_start_marker(_stat_line("my (odd) name", starttime=555)) == "555"


def test_a_zombie_is_gone() -> None:
    assert parse_start_marker(_stat_line("python", state="Z")) is None


def test_a_dead_process_is_gone() -> None:
    assert parse_start_marker(_stat_line("python", state="X")) is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no brackets here",
        "1 (short) S 1 2",
        # many numeric fields but no command name in brackets: not a /proc stat line
        " ".join(str(n) for n in range(30)),
    ],
)
def test_text_that_is_not_a_stat_line_is_unreadable_not_gone(text: str) -> None:
    # A garbled line says nothing about the process. Reading it as "gone" would let the reaper
    # remove a live owner's container.
    with pytest.raises(ProcessUnreadable):
        parse_start_marker(text)


def test_a_start_time_field_that_is_not_a_number_is_unreadable_not_gone() -> None:
    with pytest.raises(ProcessUnreadable):
        parse_start_marker(_stat_line("python", starttime="abc"))


@pytest.mark.parametrize("starttime", ["²", "٥"])
def test_a_start_time_field_of_non_ascii_digits_is_unreadable_not_gone(starttime: str) -> None:
    # str.isdigit() accepts these; /proc only ever writes ASCII digits (DEC-135 item 3).
    with pytest.raises(ProcessUnreadable):
        parse_start_marker(_stat_line("python", starttime=starttime))


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


def _failing_open(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
    def fake_open(path: object, *args: object, **kwargs: object) -> object:
        raise error

    monkeypatch.setattr(proc_module, "open", fake_open, raising=False)


@pytest.mark.parametrize(
    "error",
    [
        PermissionError(errno.EACCES, "Permission denied"),  # hidepid, or another user's process
        OSError(errno.EMFILE, "Too many open files"),
        OSError(errno.EIO, "Input/output error"),
        OSError("some other failure"),
    ],
)
def test_a_proc_stat_that_cannot_be_read_is_unreadable_not_gone(
    monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    _failing_open(monkeypatch, error)

    with pytest.raises(ProcessUnreadable):
        process_start_marker(os.getpid())


def test_a_pid_with_no_proc_entry_is_gone_only_when_no_such_process_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # B4: "no /proc entry" alone is not "gone". The kernel must also say there is no such process.
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    _failing_open(monkeypatch, FileNotFoundError(errno.ENOENT, "No such file"))

    assert process_start_marker(child.pid) is None


def _hide_stat_but_keep_the_process(
    monkeypatch: pytest.MonkeyPatch, pid: int, kill_result: BaseException | None
) -> None:
    """Make /proc/<pid>/stat answer ENOENT, as hidepid=2 does for another user's live process, and
    control what kill(pid, 0) says. Other pids and paths behave as usual."""
    real_open = open
    real_kill = os.kill

    def fake_open(path: object, *args: object, **kwargs: object) -> object:
        if path == f"/proc/{pid}/stat":
            raise FileNotFoundError(errno.ENOENT, "No such file or directory")
        return real_open(path, *args, **kwargs)  # type: ignore[call-overload]

    def fake_kill(target: int, signal_number: int) -> None:
        if target == pid and kill_result is not None:
            raise kill_result
        real_kill(target, signal_number)

    monkeypatch.setattr(proc_module, "open", fake_open, raising=False)
    monkeypatch.setattr(proc_module.os, "kill", fake_kill)


def test_a_missing_stat_for_a_live_pid_is_unreadable_not_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # hidepid=2: the pid exists (kill(pid, 0) succeeds) but its stat file is not visible
    _hide_stat_but_keep_the_process(monkeypatch, os.getpid(), kill_result=None)

    with pytest.raises(ProcessUnreadable):
        process_start_marker(os.getpid())


def test_a_missing_stat_that_kill_refuses_with_eperm_is_unreadable_not_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hide_stat_but_keep_the_process(
        monkeypatch,
        os.getpid(),
        kill_result=PermissionError(errno.EPERM, "Operation not permitted"),
    )

    with pytest.raises(ProcessUnreadable):
        process_start_marker(os.getpid())


def test_a_missing_stat_for_a_really_dead_pid_is_gone() -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()

    assert process_start_marker(child.pid) is None


def test_this_process_has_a_pid_namespace_identity() -> None:
    namespace = pid_namespace()

    assert namespace.startswith("pid:[")
    assert namespace.endswith("]")


def test_an_unreadable_pid_namespace_is_empty_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(path: object) -> str:
        raise OSError(errno.EACCES, "denied")

    monkeypatch.setattr(proc_module.os, "readlink", refuse)

    assert pid_namespace() == ""


def test_this_boot_has_an_identity_that_is_a_uuid() -> None:
    identity = boot_id()

    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", identity)
