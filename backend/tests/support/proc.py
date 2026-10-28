"""Process start markers, so a recycled pid cannot pass for the process that owned a container
(F10b, DEC-135).

The marker is field 22 of /proc/<pid>/stat: the process start time in clock ticks since boot. A
pid that the operating system has handed to a new process has a different marker. A zombie, a dead
process and a pid with no /proc entry count as gone; a /proc entry that cannot be read is unknown
(ProcessUnreadable), never gone. Platforms without /proc (macOS, Windows) give no marker for this
very process, so the harness labels no owner and the reaper falls back to the age rule.
"""

import os


class ProcessUnreadable(Exception):
    """The process table could not tell whether a pid is running: not the same as gone."""


_START_TIME_INDEX = 22 - 3  # fields after the closing bracket start at field 3 (the state)
_GONE_STATES = {"Z", "X"}


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
    if len(fields) <= _START_TIME_INDEX or not fields[_START_TIME_INDEX].isdigit():
        raise ProcessUnreadable("not a /proc stat line")
    return fields[_START_TIME_INDEX]


def process_start_marker(pid: int) -> str | None:
    """The start marker of a running process. None means gone: no /proc entry (or the process
    vanished while it was read), or a zombie. Anything else that goes wrong (permission denied
    under hidepid, no file descriptors left, a garbled line) raises ProcessUnreadable, because
    "cannot tell" must not be read as "gone": the caller deletes on "gone"."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except FileNotFoundError, ProcessLookupError:
        return None
    except OSError as error:
        raise ProcessUnreadable(f"/proc/{pid}/stat could not be read: {error}") from error
    return parse_start_marker(text)


def pid_namespace() -> str:
    """Red-run stub (DEC-010): the identity of this process's pid namespace."""
    return ""


def boot_id() -> str:
    """Red-run stub (DEC-010): the identity of this boot of the machine."""
    return ""
