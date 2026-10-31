"""The serving process's sources of a tenant's link host, wording and prompt (B1 task 3 and 4,
KI-96, KI-162, KI-387, KI-490, KI-492, KI-502, KI-505): `prompt-due` has a handler that sends the
prompt, the production container gets its link base and wording from the tenant directory and
configuration, and a plain-string link base is refused in a serving process. Synthetic values."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.tenancy import ScopeId, bind_scope, bind_tenant
from diucs.application.tenant_settings import DirectoryLinkBase, resolve_link_base
from diucs.application.tenant_wording import ConfiguredWording
from diucs.application.use_cases.send_prompts import SendPromptCommand, prompt_key
from diucs.application.work import SCHEDULED, ScheduledWork, WorkKind
from diucs.bootstrap import container as container_module
from diucs.bootstrap.container import SCHEDULER_CHANNEL, build, prompt_due_handler
from diucs.bootstrap.settings import Settings

DUE = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
TENANT = "tenant-serve-a"


@dataclass
class _Recorder:
    commands: list[SendPromptCommand]

    async def execute(self, command: SendPromptCommand) -> object:
        self.commands.append(command)
        return object()


def _work(service: str = "ucr-west", due: datetime = DUE) -> ScheduledWork:
    return ScheduledWork(
        id="work-1",
        kind=WorkKind.PROMPT_DUE,
        due_at=due,
        about_id=service,
        sequence_number=None,
        status=SCHEDULED,
    )


async def test_the_prompt_due_handler_sends_the_prompt_of_the_work_under_its_key() -> None:
    recorder = _Recorder([])
    handler = prompt_due_handler(cast(Any, recorder))

    with bind_tenant(TENANT):
        await handler(_work())

    [command] = recorder.commands
    assert command.idempotency_key == prompt_key("ucr-west", DUE)
    assert command.service_id == "ucr-west"
    assert command.due_at == DUE


async def test_the_handler_acts_as_the_scheduler_of_the_bound_tenant_only() -> None:
    recorder = _Recorder([])
    handler = prompt_due_handler(cast(Any, recorder))

    with bind_tenant(TENANT):
        await handler(_work())

    [command] = recorder.commands
    assert command.actor.tenant_id == TENANT
    assert command.actor.channel == SCHEDULER_CHANNEL
    assert command.actor.practitioner_id is None


async def test_the_same_work_runs_under_the_same_key_so_a_redelivery_is_a_replay() -> None:
    recorder = _Recorder([])
    handler = prompt_due_handler(cast(Any, recorder))

    with bind_tenant(TENANT):
        await handler(_work())
        await handler(_work())

    first, second = recorder.commands
    assert first.idempotency_key == second.idempotency_key


async def test_another_due_time_or_service_is_another_key() -> None:
    recorder = _Recorder([])
    handler = prompt_due_handler(cast(Any, recorder))

    with bind_tenant(TENANT):
        await handler(_work())
        await handler(_work(due=DUE.replace(hour=13)))
        await handler(_work(service="ucr-east"))

    keys = {command.idempotency_key for command in recorder.commands}
    assert len(keys) == 3


async def test_the_handler_needs_a_bound_tenant() -> None:
    recorder = _Recorder([])
    handler = prompt_due_handler(cast(Any, recorder))

    with pytest.raises(Exception, match="tenant"):
        await handler(_work())

    assert recorder.commands == []


async def test_the_handler_does_not_send_for_a_network_scope() -> None:
    recorder = _Recorder([])
    handler = prompt_due_handler(cast(Any, recorder))

    with bind_scope(ScopeId.network("net-west")), pytest.raises(Exception, match="tenant"):
        await handler(_work())

    assert recorder.commands == []


class _Directory:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def host_of(self, tenant_id: str) -> str | None:
        return {"tenant-serve-a": "alpha.example.org"}.get(tenant_id)


async def test_the_production_container_takes_the_link_base_from_the_tenant_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(container_module, "Neo4jTenantDirectory", _Directory)
    container = build(Settings())
    try:
        found = await resolve_link_base(container.link_base_url_for, ScopeId.tenant(TENANT))
    finally:
        await container.shutdown()

    assert found == "https://alpha.example.org/l"


async def test_the_production_container_has_no_link_base_for_a_tenant_with_no_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diucs.application.ports.outbound.tenants import TenantRecordInvalid

    monkeypatch.setattr(container_module, "Neo4jTenantDirectory", _Directory)
    container = build(Settings())
    try:
        with pytest.raises(TenantRecordInvalid):
            await resolve_link_base(container.link_base_url_for, ScopeId.tenant("tenant-serve-b"))
    finally:
        await container.shutdown()


async def test_the_production_container_reads_the_wording_from_the_tenant_configuration() -> None:
    container = build(Settings())
    try:
        assert isinstance(container.wording_for, ConfiguredWording)
    finally:
        await container.shutdown()


def test_the_serving_dispatch_table_refuses_a_plain_string_link_base() -> None:
    with pytest.raises(TypeError, match="every tenant"):
        container_module._scheduled_work(
            cast(Any, None),
            FixedClock(DUE),
            SequentialIds(),
            FixedSecretStore({}),
            "https://one-base.example",
            cast(Any, None),
            cast(Any, None),
            serving=True,
        )


def test_the_directory_link_base_is_what_the_production_dispatch_table_gets() -> None:
    source = DirectoryLinkBase(cast(Any, _Directory()))
    table = container_module._scheduled_work(
        cast(Any, None),
        FixedClock(DUE),
        SequentialIds(),
        FixedSecretStore({}),
        source,
        cast(Any, None),
        cast(Any, None),
        serving=True,
    )

    assert WorkKind.PROMPT_DUE in table.kinds
