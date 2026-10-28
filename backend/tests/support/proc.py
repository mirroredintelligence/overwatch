"""Process start markers, so a recycled pid cannot pass for the process that owned a container
(F10b, DEC-135).

The marker is field 22 of /proc/<pid>/stat: the process start time in clock ticks since boot. A
pid that the operating system has handed to a new process has a different marker. A zombie or dead
process counts as gone. Platforms without /proc (macOS, Windows) give no marker, so the harness
labels no owner and the reaper falls back to the age rule.
"""


class ProcessUnreadable(Exception):
    """The process table could not tell whether a pid is running: not the same as gone."""


_START_TIME_INDEX = 22 - 3  # fields after the closing bracket start at field 3 (the state)
_GONE_STATES = {"Z", "X"}


def parse_start_marker(stat_line: str) -> str | None:
    """The start-time field of one /proc/<pid>/stat line, or None if the process is a zombie or
    dead, or the text is not a stat line. The command name sits in brackets and may itself hold
    spaces and brackets, so the fields are counted from the last closing bracket."""
    close = stat_line.rfind(")")
    if close == -1:
        return None
    fields = stat_line[close + 1 :].split()
    if len(fields) <= _START_TIME_INDEX or fields[0] in _GONE_STATES:
        return None
    marker = fields[_START_TIME_INDEX]
    return marker if marker.isdigit() else None


def process_start_marker(pid: int) -> str | None:
    """The start marker of a running process, or None if it is gone or cannot be read."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as handle:
            return parse_start_marker(handle.read())
    except OSError:
        return None
