"""The reaper decides by owner, not by age alone (F10b, DEC-135; amends DEC-108).

A container is labelled with the pid and the start time of the process that started it. The sweep
at session start removes a labelled container whose owner is gone, at any age, and never removes one
whose owner is alive. Unlabelled containers from the old harness keep the age rule. Nothing outside
the diucs-test-neo4j-* names is ever touched. No Docker needed: the Docker runner, the clock and the
process table are fakes.
"""

import errno
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from tests.support import proc as proc_module
from tests.support.neo4j import (
    OTHER_HOST_MAX_AGE,
    REAPER_MAX_AGE,
    reap_stale_test_containers,
)
from tests.support.proc import ProcessUnreadable, boot_id, pid_namespace, process_start_marker

NOW = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
# The pid namespace and boot identity of "this process" in these fake tests (B4).
NS = "pid:[4026531836]"
BOOT = "11111111-2222-3333-4444-555555555555"
MAX_AGE = timedelta(minutes=90)
HOST = "build-host"
RECENT = "2026-10-28T11:55:00.000000000Z"  # five minutes old
OLD = "2026-10-28T06:00:00.000000000Z"  # six hours old
ANCIENT = "2026-10-27T06:00:00.000000000Z"  # thirty hours old


class Container:
    def __init__(
        self,
        name: str,
        created: str = RECENT,
        *,
        test_label: str = "true",
        pid: str = "",
        start: str = "",
        host: str = "",
        ns: str = "",
        boot: str = "",
    ) -> None:
        self.name = name
        self.created = created
        self.fields = [test_label, pid, start, host, ns, boot]


class FakeDocker:
    """Answers ps, inspect and rm, and records every call. inspect prints one line per container:
    /name|created|test label|owner pid|owner start|owner host, as the reaper's format asks."""

    def __init__(self, containers: list[Container]) -> None:
        self.containers = containers
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        out = ""
        if args[:2] == ("ps", "-a"):
            out = "\n".join(c.name for c in self.containers)
        elif args[0] == "inspect":
            asked = set(args[3:])
            out = "\n".join(
                "|".join([f"/{c.name}", c.created, *c.fields])
                for c in self.containers
                if c.name in asked
            )
        return subprocess.CompletedProcess(
            args=["docker", *args], returncode=0, stdout=out, stderr=""
        )

    def removed(self) -> list[str]:
        return [call[3] for call in self.calls if call[:3] == ("rm", "-f", "-v")]

    def inspect_format(self) -> str:
        (call,) = [c for c in self.calls if c[0] == "inspect"]
        return call[2]


def _sweep(
    containers: list[Container],
    table: dict[int, str],
    *,
    host: str = HOST,
    namespace: str = NS,
    boot: str = BOOT,
) -> tuple[list[str], FakeDocker]:
    docker = FakeDocker(containers)
    removed = reap_stale_test_containers(
        MAX_AGE,
        run=docker,
        now=lambda: NOW,
        process_start=lambda pid: table.get(pid),
        host=host,
        here_namespace=namespace,
        here_boot=boot,
    )
    return removed, docker


def _owned(
    name: str,
    pid: int,
    start: str,
    created: str = RECENT,
    host: str = HOST,
    ns: str = NS,
    boot: str = BOOT,
) -> Container:
    return Container(name, created, pid=str(pid), start=start, host=host, ns=ns, boot=boot)


def test_the_inspect_format_reads_the_three_owner_labels() -> None:
    _, docker = _sweep([Container("diucs-test-neo4j-a")], {})

    fmt = docker.inspect_format()
    assert 'index .Config.Labels "diucs-test-owner-pid"' in fmt
    assert 'index .Config.Labels "diucs-test-owner-start"' in fmt
    assert 'index .Config.Labels "diucs-test-owner-host"' in fmt
    assert 'index .Config.Labels "diucs-test"' in fmt


def test_a_container_whose_owner_has_gone_is_removed_even_though_it_is_five_minutes_old() -> None:
    removed, docker = _sweep([_owned("diucs-test-neo4j-dead", 4001, "777")], table={})

    assert removed == ["diucs-test-neo4j-dead"]
    assert docker.removed() == ["diucs-test-neo4j-dead"]


def test_a_container_whose_owner_is_alive_is_kept_however_old_it_is() -> None:
    containers = [
        _owned("diucs-test-neo4j-alive", 4002, "888", created=ANCIENT),
        _owned("diucs-test-neo4j-alive-too", 4002, "888", created=OLD),
    ]

    removed, docker = _sweep(containers, table={4002: "888"})

    assert removed == []
    assert docker.removed() == []


def test_a_recycled_pid_does_not_keep_a_leaked_container_alive() -> None:
    # pid 4003 exists, but it is another process that started later: the start times differ
    removed, _ = _sweep([_owned("diucs-test-neo4j-reused", 4003, "100")], table={4003: "999999"})

    assert removed == ["diucs-test-neo4j-reused"]


def test_one_sweep_removes_the_dead_and_keeps_the_living() -> None:
    containers = [
        _owned("diucs-test-neo4j-dead1", 11, "1"),
        _owned("diucs-test-neo4j-live", 12, "2", created=ANCIENT),
        _owned("diucs-test-neo4j-dead2", 13, "3", created=OLD),
    ]

    removed, docker = _sweep(containers, table={12: "2"})

    assert sorted(removed) == ["diucs-test-neo4j-dead1", "diucs-test-neo4j-dead2"]
    assert sorted(docker.removed()) == sorted(removed)


def test_an_unlabelled_legacy_container_keeps_the_age_rule() -> None:
    containers = [
        Container("diucs-test-neo4j-legacy-old", OLD),
        Container("diucs-test-neo4j-legacy-new", RECENT),
    ]

    removed, _ = _sweep(containers, table={})

    assert removed == ["diucs-test-neo4j-legacy-old"]


def test_an_owner_label_that_is_not_a_number_falls_back_to_the_age_rule() -> None:
    containers = [
        Container("diucs-test-neo4j-garbled-new", RECENT, pid="abc", start="1", host=HOST),
        Container("diucs-test-neo4j-garbled-old", OLD, pid="abc", start="1", host=HOST),
    ]

    removed, _ = _sweep(containers, table={})

    assert removed == ["diucs-test-neo4j-garbled-old"]


@pytest.mark.parametrize("start", ["abc", " 12345", "12x", "²", "٥"])
def test_a_live_owner_whose_start_label_is_not_a_number_is_kept_young(start: str) -> None:
    # pid 4004 is alive here with start "5", but the label is garbled, so the label cannot be
    # compared with it. The owner is unknown, not gone (DEC-135 item 3): the age rule decides.
    # "²" and "٥" are digits to str.isdigit() but not ASCII digits, so they must not count.
    containers = [
        _owned("diucs-test-neo4j-startgarbled-new", 4004, start, created=RECENT),
        _owned("diucs-test-neo4j-startgarbled-old", 4004, start, created=OLD),
    ]

    removed, _ = _sweep(containers, table={4004: "5"})

    assert removed == ["diucs-test-neo4j-startgarbled-old"]


@pytest.mark.parametrize("pid", ["²", "٥"])
def test_a_non_ascii_digit_pid_label_falls_back_to_the_ninety_minute_rule(pid: str) -> None:
    # "²" and "٥" are digits to str.isdigit() but not ASCII digits: the pid label is not a number,
    # so the container keeps the 90-minute rule (DEC-135 item 3), not the six-hour rule.
    containers = [
        Container(
            "diucs-test-neo4j-pidgarbled-new",
            RECENT,
            pid=pid,
            start="5",
            host=HOST,
            ns=NS,
            boot=BOOT,
        ),
        Container(
            "diucs-test-neo4j-pidgarbled-old", OLD, pid=pid, start="5", host=HOST, ns=NS, boot=BOOT
        ),
    ]

    removed, _ = _sweep(containers, table={})

    assert removed == ["diucs-test-neo4j-pidgarbled-old"]


def test_a_created_value_with_non_ascii_digits_is_not_parsed_so_the_container_is_kept() -> None:
    # Arabic-Indic digits: \d would match them, [0-9] does not. An unparsed Created value means the
    # age cannot be judged, so the container is kept (the safe direction). Pins existing behaviour.
    containers = [Container("diucs-test-neo4j-createdgarbled", "٢٠٢٦-10-28T06:00:00.000000000Z")]

    removed, _ = _sweep(containers, table={})

    assert removed == []


def test_a_container_owned_from_another_host_is_judged_by_age_not_by_this_hosts_processes() -> None:
    # pid 4004 means nothing here: it may be alive in another pid namespace. Never reap it young.
    containers = [
        _owned("diucs-test-neo4j-elsewhere-new", 4004, "5", created=RECENT, host="other-host"),
        _owned("diucs-test-neo4j-elsewhere-ancient", 4004, "5", created=ANCIENT, host="other-host"),
    ]

    removed, _ = _sweep(containers, table={})

    assert removed == ["diucs-test-neo4j-elsewhere-ancient"]


def test_a_name_outside_the_throwaway_prefix_is_never_removed_whatever_its_labels_say() -> None:
    containers = [
        _owned("diucs-local-neo4j-1", 4005, "9", created=ANCIENT),
        _owned("diucs-local-redis-1", 4005, "9", created=ANCIENT),
        _owned("other-app", 4005, "9", created=ANCIENT),
        _owned("xdiucs-test-neo4j-1", 4005, "9", created=ANCIENT),
    ]

    removed, docker = _sweep(containers, table={})

    assert removed == []
    assert docker.removed() == []


def test_a_container_without_the_test_label_is_never_removed_even_with_a_dead_owner() -> None:
    container = Container("diucs-test-neo4j-nolabel", ANCIENT, test_label="", pid="4006", start="1")

    removed, _ = _sweep([container], table={})

    assert removed == []


def test_the_sweep_only_lists_inspects_and_removes_with_volumes() -> None:
    containers = [
        _owned("diucs-test-neo4j-dead", 4007, "1"),
        _owned("diucs-local-neo4j-1", 4007, "1"),
    ]

    _, docker = _sweep(containers, table={})

    assert {call[0] for call in docker.calls} <= {"ps", "inspect", "rm"}
    for call in docker.calls:
        if call[0] == "rm":
            assert call == ("rm", "-f", "-v", "diucs-test-neo4j-dead")


def test_a_refused_removal_is_logged_and_the_sweep_goes_on() -> None:
    class RefusingDocker(FakeDocker):
        def __call__(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
            result = super().__call__(*args, timeout=timeout)
            if args[0] == "rm" and args[3] == "diucs-test-neo4j-stuck":
                return subprocess.CompletedProcess(
                    args=result.args, returncode=1, stdout="", stderr="busy"
                )
            return result

    docker = RefusingDocker(
        [_owned("diucs-test-neo4j-stuck", 21, "1"), _owned("diucs-test-neo4j-fine", 22, "1")]
    )

    removed = reap_stale_test_containers(
        MAX_AGE,
        run=docker,
        now=lambda: NOW,
        process_start=lambda pid: None,
        host=HOST,
        here_namespace=NS,
        here_boot=BOOT,
    )

    assert removed == ["diucs-test-neo4j-fine"]


def test_the_real_process_table_keeps_this_process_container_and_drops_a_dead_ones() -> None:
    mine = process_start_marker(os.getpid())
    assert mine is not None
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    here_ns, here_boot = pid_namespace(), boot_id()
    containers = [
        _owned(
            "diucs-test-neo4j-mine",
            os.getpid(),
            mine,
            created=ANCIENT,
            host="this-host",
            ns=here_ns,
            boot=here_boot,
        ),
        _owned(
            "diucs-test-neo4j-gone",
            child.pid,
            "1",
            created=RECENT,
            host="this-host",
            ns=here_ns,
            boot=here_boot,
        ),
    ]
    docker = FakeDocker(containers)

    removed = reap_stale_test_containers(MAX_AGE, run=docker, now=lambda: NOW, host="this-host")

    assert removed == ["diucs-test-neo4j-gone"]


# ---- an owner that cannot be checked is unknown, never gone (verifier finding B1) --------------

UNREADABLE = [
    ProcessUnreadable("garbled"),
    PermissionError(errno.EACCES, "Permission denied"),
    OSError(errno.EMFILE, "Too many open files"),
    OSError("some other failure"),
    RuntimeError("anything at all"),
]


def _reap(
    containers: list[Container],
    process_start: Callable[[int], str | None],
    *,
    host: str = HOST,
) -> list[str]:
    return reap_stale_test_containers(
        MAX_AGE,
        run=FakeDocker(containers),
        now=lambda: NOW,
        process_start=process_start,
        host=host,
        here_namespace=NS,
        here_boot=BOOT,
    )


@pytest.mark.parametrize("error", UNREADABLE, ids=lambda error: type(error).__name__)
def test_an_owner_that_cannot_be_checked_keeps_a_young_container(error: BaseException) -> None:
    def cannot_tell(pid: int) -> str | None:
        raise error

    removed = _reap([_owned("diucs-test-neo4j-live", 4010, "5", created=RECENT)], cannot_tell)

    assert removed == []


@pytest.mark.parametrize("error", UNREADABLE, ids=lambda error: type(error).__name__)
def test_an_owner_that_cannot_be_checked_falls_back_to_the_age_rule(error: BaseException) -> None:
    def cannot_tell(pid: int) -> str | None:
        raise error

    removed = _reap([_owned("diucs-test-neo4j-old", 4011, "5", created=ANCIENT)], cannot_tell)

    assert removed == ["diucs-test-neo4j-old"]


def test_a_proc_that_refuses_to_be_read_does_not_cost_the_sweeping_process_its_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The verifier's case: this very process owns the container, and /proc/<pid>/stat raises
    # PermissionError (hidepid, or no descriptors left). The real process table is used.
    mine = process_start_marker(os.getpid())
    assert mine is not None
    container = _owned(
        "diucs-test-neo4j-mine",
        os.getpid(),
        mine,
        created=RECENT,
        host="h",
        ns=pid_namespace(),
        boot=boot_id(),
    )

    def refuse(path: object, *args: object, **kwargs: object) -> object:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(proc_module, "open", refuse, raising=False)
    docker = FakeDocker([container])

    removed = reap_stale_test_containers(MAX_AGE, run=docker, now=lambda: NOW, host="h")

    assert removed == []
    assert docker.removed() == []


def test_a_pid_with_no_proc_entry_still_means_gone() -> None:
    removed = _reap([_owned("diucs-test-neo4j-dead", 4012, "5")], lambda pid: None)

    assert removed == ["diucs-test-neo4j-dead"]


# ---- the age constants are pinned (verifier finding B2) ----------------------------------------


def test_another_hosts_container_is_kept_under_six_hours_and_removed_over() -> None:
    five_59 = (NOW - timedelta(hours=5, minutes=59)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    six_01 = (NOW - timedelta(hours=6, minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    containers = [
        _owned("diucs-test-neo4j-just-under", 4020, "5", created=five_59, host="other"),
        _owned("diucs-test-neo4j-just-over", 4021, "5", created=six_01, host="other"),
    ]

    assert _reap(containers, lambda pid: None) == ["diucs-test-neo4j-just-over"]


def test_the_other_host_age_is_six_hours() -> None:
    assert timedelta(hours=6) == OTHER_HOST_MAX_AGE


def test_the_default_age_for_a_container_with_no_owner_is_ninety_minutes() -> None:
    assert timedelta(minutes=90) == REAPER_MAX_AGE
    eighty_nine = (NOW - timedelta(minutes=89)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    ninety_one = (NOW - timedelta(minutes=91)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    docker = FakeDocker(
        [
            Container("diucs-test-neo4j-legacy-89", eighty_nine),
            Container("diucs-test-neo4j-legacy-91", ninety_one),
        ]
    )

    removed = reap_stale_test_containers(
        run=docker, now=lambda: NOW, process_start=lambda pid: None
    )

    assert removed == ["diucs-test-neo4j-legacy-91"]


def test_an_owner_that_cannot_be_checked_is_judged_by_a_six_hour_age() -> None:
    two_hours = (NOW - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    seven_hours = (NOW - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")

    def cannot_tell(pid: int) -> str | None:
        raise ProcessUnreadable("hidepid")

    containers = [
        _owned("diucs-test-neo4j-two-hours", 4030, "5", created=two_hours),
        _owned("diucs-test-neo4j-seven-hours", 4031, "5", created=seven_hours),
    ]

    assert _reap(containers, cannot_tell) == ["diucs-test-neo4j-seven-hours"]


# ---- B4: an owner that is not visible from here is unknown, never gone ------------------------


def test_an_owner_in_another_pid_namespace_is_kept_young_and_removed_after_six_hours() -> None:
    # Same host name, same pid and start time, but a different pid namespace: the pid means
    # nothing here, so the owner may be alive. Only the six-hour age may remove it.
    five_hours = (NOW - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    seven_hours = (NOW - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    containers = [
        _owned("diucs-test-neo4j-other-ns-young", 4050, "5", created=RECENT, ns="pid:[4026532001]"),
        _owned(
            "diucs-test-neo4j-other-ns-five", 4051, "5", created=five_hours, ns="pid:[4026532001]"
        ),
        _owned(
            "diucs-test-neo4j-other-ns-old", 4052, "5", created=seven_hours, ns="pid:[4026532001]"
        ),
    ]

    removed = _reap(containers, lambda pid: None)

    assert removed == ["diucs-test-neo4j-other-ns-old"]


def test_an_owner_from_another_boot_is_judged_by_the_six_hour_age() -> None:
    # A boot id is the same for every process of one boot. After a reboot a pid and a start time
    # can repeat, so a different boot is not this machine's process table.
    containers = [
        _owned("diucs-test-neo4j-other-boot-young", 4053, "5", created=RECENT, boot="other-boot"),
    ]

    assert _reap(containers, lambda pid: None) == []


def test_an_owner_label_with_no_host_is_not_treated_as_this_host() -> None:
    five_hours = (NOW - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    seven_hours = (NOW - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    containers = [
        _owned("diucs-test-neo4j-nohost-five", 4054, "5", created=five_hours, host=""),
        _owned("diucs-test-neo4j-nohost-old", 4055, "5", created=seven_hours, host=""),
    ]

    assert _reap(containers, lambda pid: None) == ["diucs-test-neo4j-nohost-old"]


def test_an_owner_whose_stat_is_hidden_but_which_is_alive_is_kept_young(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # hidepid=2 gives ENOENT for another user's live process. The real process table is used:
    # kill(pid, 0) succeeds for this live process, so the owner is not gone.
    real_open = open
    own_stat = f"/proc/{os.getpid()}/stat"

    def hidden(path: object, *args: object, **kwargs: object) -> object:
        if path == own_stat:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory")
        return real_open(path, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(proc_module, "open", hidden, raising=False)
    docker = FakeDocker([_owned("diucs-test-neo4j-hidden-owner", os.getpid(), "5", created=RECENT)])

    removed = reap_stale_test_containers(
        MAX_AGE, run=docker, now=lambda: NOW, host=HOST, here_namespace=NS, here_boot=BOOT
    )

    assert removed == []
    assert docker.removed() == []


def test_an_owner_that_is_really_dead_is_removed_at_any_age() -> None:
    # The real process table: the child has been reaped, so kill(pid, 0) says no such process.
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    docker = FakeDocker([_owned("diucs-test-neo4j-really-dead", child.pid, "5", created=RECENT)])

    removed = reap_stale_test_containers(
        MAX_AGE, run=docker, now=lambda: NOW, host=HOST, here_namespace=NS, here_boot=BOOT
    )

    assert removed == ["diucs-test-neo4j-really-dead"]


def test_an_empty_host_on_both_sides_is_still_not_comparable() -> None:
    # The owner's empty host equals this process's empty host, so only the emptiness check keeps
    # the owner from being compared and judged gone.
    seven_hours = (NOW - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    five_hours = (NOW - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    containers = [
        _owned("diucs-test-neo4j-both-empty-five", 4060, "5", created=five_hours, host=""),
        _owned("diucs-test-neo4j-both-empty-old", 4061, "5", created=seven_hours, host=""),
    ]
    docker = FakeDocker(containers)

    removed = reap_stale_test_containers(
        MAX_AGE,
        run=docker,
        now=lambda: NOW,
        process_start=lambda pid: None,
        host="",
        here_namespace=NS,
        here_boot=BOOT,
    )

    assert removed == ["diucs-test-neo4j-both-empty-old"]
