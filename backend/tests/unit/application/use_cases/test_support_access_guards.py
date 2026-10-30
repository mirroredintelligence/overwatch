"""The guard of OpenSessionForSupport (O06): a role other than support is refused before any unit of
work opens, so no lookup and no write happens for it. The factory here fails the test if it is used,
which is not a store: it proves that the refusal comes first."""

from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.use_cases.support_access import OpenSessionCommand, OpenSessionForSupport
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed
from tests.support.actors import ACTOR_TENANT

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


class _UnitOfWorkMustNotOpen:
    def __call__(self) -> Any:
        raise AssertionError("a refused open must not open a unit of work")


def _actor(role: Role) -> Actor:
    return Actor(
        role=role,
        practitioner_id="p-support-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.SUPPORT])
async def test_a_role_other_than_support_is_refused_before_any_lookup(role: Role) -> None:
    use_case = OpenSessionForSupport(
        _UnitOfWorkMustNotOpen(),
        FixedClock(NOW),
        SequentialIds(),
        FixedSecretStore({"support-code": b"s" * 32}),
    )

    with pytest.raises(NotAllowed):
        await use_case.execute(OpenSessionCommand(actor=_actor(role), code="ABCD-EFGH"))
