"""Process start markers, so a recycled pid cannot pass for the process that owned a container
(F10b, DEC-135).

The marker is field 22 of /proc/<pid>/stat: the process start time in clock ticks since boot. A
pid that the operating system has handed to a new process has a different marker. A zombie, and a
pid with no /proc entry that the kernel also says does not exist, count as gone. Anything else that
cannot be seen is unknown (ProcessUnreadable), never gone. Platforms without /proc (macOS, Windows)
give no marker for this very process, so the harness labels no owner and the reaper falls back to
the age rule.
"""

import os


class ProcessUnreadable(Exception):
    """The process table could not tell whether a pid is running: not the same as gone."""


_START_TIME_INDEX = 22 - 3  # fields after the closing bracket start at field 3 (the state)
_GONE_STATES = {"Z", "X"}


def ascii_digits(text: str) -> bool:
    # str.isdigit() also accepts "²" and "٥"; /proc and the container labels only ever hold
    # ASCII digits (DEC-135 item 3).
    return text.isascii() and text.isdigit()


def parse_start_marker(stat_line: str) -> str | None:
    """The start-time field of one /proc/<pid>/stat line, or None if the process is a zombie or
    dead. Text that is not a stat line raises ProcessUnreadable: a garbled line says nothing about
    the process, so it must never be read as "gone". The command name sits in brackets and may
    itself hold spaces and brackets, so the fields are counted from the last closing bracket."""
    close = stat_line.rfind(")")
    fields = stat_line[close + 1 :].split() if close != -1 else []
    if not fields:
        raise ProcessUnreadable("not a /proc stat line")
    if fields[0] in _GONE_STATES:
        return None
    if len(fields) <= _START_TIME_INDEX or not ascii_digits(fields[_START_TIME_INDEX]):
        raise ProcessUnreadable("not a /proc stat line")
    return fields[_START_TIME_INDEX]


def process_start_marker(pid: int) -> str | None:
    """The start marker of a process this one can see. None means gone, and only in two cases: a
    zombie, or no /proc entry and kill(pid, 0) says there is no such process (a really dead pid).
    Everything else raises ProcessUnreadable, because "cannot tell" must never be read as "gone":
    a stat file that is hidden (hidepid=2 answers ENOENT for another user's live process) with a
    pid that still exists, a permission error, no file descriptors left, or a garbled line. The
    caller deletes on "gone", so it must be exact."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except FileNotFoundError:
        return _confirm_gone(pid)
    except OSError as error:
        raise ProcessUnreadable(f"/proc/{pid}/stat could not be read: {error}") from error
    return parse_start_marker(text)


def _confirm_gone(pid: int) -> None:
    """A pid with no visible /proc entry is gone only if the kernel also says there is no such
    process. kill(pid, 0) sends nothing: ProcessLookupError means no such pid, while success or
    PermissionError means the process exists (in this pid namespace, for another user), so the
    owner may be alive and the answer is unknown."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except OSError as error:
        raise ProcessUnreadable(f"pid {pid} exists but its stat is not visible: {error}") from error
    raise ProcessUnreadable(f"pid {pid} exists but its stat is not visible")


def pid_namespace() -> str:
    """The identity of this process's pid namespace, for example "pid:[4026531836]". Two processes
    with the same identity share one pid table. "" when it cannot be read."""
    try:
        return os.readlink("/proc/self/ns/pid")
    except OSError:
        return ""


def boot_id() -> str:
    """The identity of this boot of the machine. Pids and start times can repeat across boots, so
    an owner from another boot is never looked up in this one. "" when it cannot be read."""
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as handle:
            return handle.read().strip()
    except OSError:
        return ""
