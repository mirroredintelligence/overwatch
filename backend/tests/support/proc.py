"""Process start markers, so a recycled pid cannot pass for the process that owned a container
(F10b). Stub: no behaviour yet (DEC-010)."""


def parse_start_marker(stat_line: str) -> str | None:
    return None


def process_start_marker(pid: int) -> str | None:
    return None
