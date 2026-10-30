"""The operator's provisioning script, wired (TEN-028, DEC-503): the command line, the tenant each
command is bound to, the actor it runs as and what it prints.

No Neo4j and no container: the use cases are recording fakes, so a test shows which one a command
calls, with what, under which binding, and that nothing it prints is a secret.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from diucs.application.tenancy import current_scope_or_none
from diucs.bootstrap import provisioning as module
from diucs.bootstrap.provisioning import (
    COMMANDS,
    AuditHeads,
    operator_actor,
    parse_args,
    run_command,
)
from diucs.domain.codes import Role
from diucs.domain.model.tenant import OrganisationType
from tests.support.provisioning_fakes import TENANT, provisioning_tenant

MOBILE = "07700 900123"
EXPIRES = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


class _Recorder:
    """A use case that records its command and the scope bound while it ran."""

    def __init__(self, result: Any = None) -> None:
        self.commands: list[Any] = []
        self.scopes: list[Any] = []
        self._result = result

    async def execute(self, command: Any) -> Any:
        self.commands.append(command)
        self.scopes.append(current_scope_or_none())
        return self._result


def _fakes() -> Any:
    return SimpleNamespace(
        create=_Recorder(SimpleNamespace(tenant_id=TENANT, created=True)),
        number=_Recorder("sms-447700900123"),
        tested=_Recorder(),
        host=_Recorder(),
        references=_Recorder(("dsa_ref",)),
        directory=_Recorder(),
        invite=_Recorder(SimpleNamespace(expires_at=EXPIRES, communication_id="comm-1")),
        activate=_Recorder(SimpleNamespace(tenant_id=TENANT, epoch=1)),
        container=SimpleNamespace(tenants=_Tenants()),
    )


class _Tenants:
    async def get(self, tenant_id: str) -> Any:
        return provisioning_tenant(tenant_id) if tenant_id == TENANT else None


def _args(*argv: str) -> Any:
    return parse_args(["--operator", "operator-1", *argv])


# -- the command line ----------------------------------------------------------------------------


def test_the_operator_is_required_and_the_command_is_one_of_the_nine() -> None:
    with pytest.raises(SystemExit):
        parse_args(["create", TENANT])
    with pytest.raises(SystemExit):
        parse_args(["--operator", "o", "delete", TENANT])
    assert set(COMMANDS) == {
        "create",
        "host",
        "number",
        "number-tested",
        "references",
        "verify-directory",
        "invite",
        "activate",
        "status",
    }


def test_create_takes_the_names_and_the_type_and_refuses_a_type_it_does_not_know() -> None:
    args = _args(
        "create", TENANT, "--display-name", "New", "--legal-name", "New Ltd", "--type", "icb"
    )
    assert (args.command, args.tenant_id, args.type, args.country) == (
        "create",
        TENANT,
        "icb",
        "GB",
    )
    with pytest.raises(SystemExit):
        _args("create", TENANT, "--display-name", "N", "--legal-name", "N", "--type", "bank")


# -- one command, one tenant, one actor -----------------------------------------------------------


def test_the_operator_actor_is_the_platform_operator_of_one_tenant_with_no_standing_elsewhere() -> (
    None
):
    actor = operator_actor(TENANT, "operator-1")
    assert actor.role is Role.PLATFORM_OPERATOR and actor.tenant_id == TENANT
    assert actor.practitioner_id == "operator-1" and actor.device_id is None
    assert actor.service_ids == frozenset() and actor.channel == "script"


async def test_a_command_runs_bound_to_the_tenant_it_names_and_to_nothing_after() -> None:
    fakes = _fakes()
    lines = await run_command(
        fakes,
        _args("create", TENANT, "--display-name", "N", "--legal-name", "N Ltd", "--type", "icb"),
    )

    [command] = fakes.create.commands
    assert fakes.create.scopes[0].value == TENANT
    assert command.tenant_id == TENANT and command.actor.tenant_id == TENANT
    assert command.organisation_type is OrganisationType.ICB
    assert current_scope_or_none() is None  # the binding ends with the command
    assert lines == [f"tenant {TENANT}: created in provisioning"]


@pytest.mark.parametrize(
    ("argv", "use_case", "expected"),
    [
        (("host", TENANT, "new.example.org"), "host", "host set"),
        (
            ("number", TENANT, "+447700900123", "AC" + "1" * 32, "--label", "Sample"),
            "number",
            "number recorded as channel sms-447700900123",
        ),
        (("number-tested", TENANT, "+447700900123"), "tested", "number marked as tested"),
        (("references", TENANT, "--dsa", "D-1"), "references", "recorded dsa_ref"),
        (
            ("verify-directory", TENANT, "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"),
            "directory",
            "directory verified",
        ),
        (("activate", TENANT), "activate", "active, epoch 1"),
    ],
)
async def test_each_command_calls_its_use_case_for_the_named_tenant_and_prints_fixed_words(
    argv: tuple[str, ...], use_case: str, expected: str
) -> None:
    fakes = _fakes()

    lines = await run_command(fakes, _args(*argv))

    recorder = getattr(fakes, use_case)
    assert len(recorder.commands) == 1
    assert recorder.scopes[0].value == TENANT
    assert recorder.commands[0].actor.role is Role.PLATFORM_OPERATOR
    assert lines == [f"tenant {TENANT}: {expected}"]


async def test_the_invitation_prints_when_it_expires_and_never_the_number_or_a_link() -> None:
    fakes = _fakes()

    lines = await run_command(fakes, _args("invite", TENANT, MOBILE))

    assert fakes.invite.commands[0].mobile == MOBILE
    assert lines == [f"tenant {TENANT}: invitation queued, valid until {EXPIRES.isoformat()}"]
    for line in lines:
        assert "07700" not in line and "https://" not in line and "/i/" not in line


async def test_a_number_command_prints_no_number_and_no_account() -> None:
    fakes = _fakes()
    lines = await run_command(
        fakes, _args("number", TENANT, "+447700900123", "AC" + "1" * 32, "--label", "Sample")
    )
    assert "+4477" not in " ".join(lines) and "AC1111" not in " ".join(lines)


async def test_status_of_a_tenant_that_does_not_exist_says_so() -> None:
    lines = await run_command(_fakes(), _args("status", "nobody-here"))
    assert lines == ["tenant nobody-here: not found"]


async def test_status_of_a_provisioning_tenant_lists_what_is_missing_in_fixed_words() -> None:
    fakes = _fakes()
    assessed: list[Any] = []

    async def assess(actor: Any) -> Any:
        assessed.append(actor)
        return SimpleNamespace(blockers=("Host set", "Area districts set"))

    fakes.activate.assess = assess

    lines = await run_command(fakes, _args("status", TENANT))

    assert lines == [
        f"tenant {TENANT}: provisioning, epoch 1",
        "  missing: Host set",
        "  missing: Area districts set",
    ]
    assert assessed[0].role is Role.PLATFORM_OPERATOR


async def test_the_audit_head_provisioner_asks_for_the_bound_scopes_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[Any] = []

    async def fake(driver: Any) -> None:
        asked.append(driver)

    monkeypatch.setattr(module, "ensure_audit_head", fake)
    connection = SimpleNamespace(driver="the-driver")
    await AuditHeads(connection).ensure_audit_head()  # type: ignore[arg-type]
    assert asked == ["the-driver"]


def test_every_command_has_a_branch_in_the_runner() -> None:
    """A command that parses but has no branch would fall through to the ValueError."""
    import inspect

    source = inspect.getsource(run_command)
    for command in COMMANDS:
        assert f'case "{command}"' in source, command
