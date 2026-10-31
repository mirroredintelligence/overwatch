"""The operator's offboarding, export and purge script, wired (TEN-077, TEN-074, DEC-960 to
DEC-971): the command line, the tenant each command is bound to, the actors it runs as and what it
prints. The use cases are recording fakes, so a test shows which one a command calls, with what,
under which binding, and that a purge needs the second operator and the typed id on the line."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from diucs.application.tenancy import current_scope_or_none
from diucs.bootstrap.lifecycle_operations import COMMANDS, parse_args, run_command
from diucs.domain.codes import Role

TENANT = "org-leaving"


class _Recorder:
    def __init__(self, result: Any = None) -> None:
        self.commands: list[Any] = []
        self.scopes: list[Any] = []
        self._result = result

    async def execute(self, command: Any) -> Any:
        self.commands.append(command)
        self.scopes.append(current_scope_or_none())
        return self._result


def test_the_operator_is_required_and_the_command_is_one_of_the_five() -> None:
    for bad in (
        [],
        ["offboard", TENANT],
        ["--operator", "x", "offboard", TENANT],  # the typed id is required
        ["--operator", "x", "unknown", TENANT],
    ):
        with pytest.raises(SystemExit):
            parse_args(bad)
    assert set(COMMANDS) == {
        "network-create",
        "offboard",
        "export",
        "complete-offboarding",
        "purge",
    }


def test_a_purge_cannot_be_asked_for_without_the_second_operator_and_the_typed_id() -> None:
    base = ["--operator", "one", "purge", TENANT]
    for missing in (
        base + ["--type-id", TENANT],
        base + ["--second", "two"],
        base,
    ):
        with pytest.raises(SystemExit):
            parse_args(missing)
    args = parse_args(base + ["--second", "two", "--type-id", TENANT, "--dry-run"])
    assert args.dry_run is True and args.second == "two"
    assert not any(a for a in vars(args) if a in ("yes", "force"))


async def test_offboard_runs_as_the_operator_of_the_tenant_it_names_and_prints_fixed_words() -> (
    None
):
    ends = datetime(2026, 11, 29, 9, 0, tzinfo=UTC)
    started = SimpleNamespace(
        tenant_id=TENANT, memberships_ended=2, notice_ends_at=ends, resumed=False
    )
    use_case = _Recorder(started)
    lifecycle = SimpleNamespace(offboard=use_case, container=SimpleNamespace())
    args = parse_args(["--operator", "op-one", "offboard", TENANT, "--confirm", TENANT])
    lines = await run_command(lifecycle, args)  # type: ignore[arg-type]
    assert lines == [
        f"tenant {TENANT}: offboarding until 2026-11-29T09:00:00+00:00, 2 memberships ended"
    ]
    [command] = use_case.commands
    assert command.confirm_tenant_id == TENANT
    assert command.actor.role is Role.PLATFORM_OPERATOR and command.actor.tenant_id == TENANT
    assert command.actor.practitioner_id == "op-one"
    assert use_case.scopes[0] is not None and use_case.scopes[0].value == TENANT
    assert current_scope_or_none() is None  # not bound after


async def test_network_create_passes_the_arguments_and_names_no_agreement_content() -> None:
    use_case = _Recorder(SimpleNamespace(network_id="net-sample", created=True))
    lifecycle = SimpleNamespace(network_create=use_case, container=SimpleNamespace())
    args = parse_args(
        [
            "--operator",
            "op-one",
            "network-create",
            TENANT,
            "net-sample",
            "--name",
            "Sample network",
            "--agreement-reference",
            "DSA-2026-1",
            "--agreement-version",
            "1",
            "--system-name",
            "Sample capacity board",
            "--pathway-name",
            "Sample pathway",
        ]
    )
    lines = await run_command(lifecycle, args)  # type: ignore[arg-type]
    assert lines == ["network net-sample: created, owned by the tenant"]
    [command] = use_case.commands
    assert (command.network_id, command.agreement_reference, command.agreement_version) == (
        "net-sample",
        "DSA-2026-1",
        1,
    )
    assert command.actor.tenant_id == TENANT


async def test_a_purge_dry_run_prints_counts_by_label_set_and_says_nothing_was_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _Purge:
        def __init__(self, *args: Any) -> None:
            captured["args"] = args

        async def execute(self, command: Any) -> Any:
            captured["command"] = command
            return SimpleNamespace(
                dry_run=True,
                counts={"HealthcareService+Resource": 5},
                nodes_deleted=0,
                cache_names_removed=0,
                resumed=False,
            )

    class _Cache:
        @classmethod
        def from_url(cls, url: str) -> _Cache:
            return cls()

        async def aclose(self) -> None:
            return None

    from diucs.bootstrap import lifecycle_operations as module

    monkeypatch.setattr(module, "PurgeTenant", _Purge)
    monkeypatch.setattr(module, "RedisCache", _Cache)
    container = SimpleNamespace(
        tenants=object(),
        tenant_registry=object(),
        clock=object(),
        uow_factory=object(),
        platform_audit=object(),
    )
    lifecycle = SimpleNamespace(container=container, data=object())
    args = parse_args(
        [
            "--operator",
            "one",
            "purge",
            TENANT,
            "--second",
            "two",
            "--type-id",
            TENANT,
            "--dry-run",
        ]
    )
    lines = await module.run_command(lifecycle, args)  # type: ignore[arg-type]
    assert lines == [
        f"tenant {TENANT}: dry run, nothing deleted",
        "  HealthcareService+Resource: 5",
    ]
    command = captured["command"]
    assert command.dry_run and command.typed_slug == TENANT
    assert command.actor.practitioner_id == "one" and command.second_actor.practitioner_id == "two"
