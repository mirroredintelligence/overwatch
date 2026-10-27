"""The unit of work's repository registry (P06). No database: the unit is never entered here."""

import pytest

from diucs.adapters.outbound.graph_store.unit_of_work import DEFAULT_FACTORIES, Neo4jUnitOfWork

# Every attribute of the UnitOfWork port, from docs/spec/contracts.md, plus the three P16 stores
# that DEC-071 item 9 and lesson L86 ask P06 to register.
REQUIRED_NAMES = {
    "services",
    "capacity",
    "bookings",
    "cases",
    "people",
    "criteria",
    "registrations",
    "scope",
    "flags",
    "communications",
    "link_tokens",
    "scheduled_work",
    "audit",
    "outbox",
    "contacts",
    "pins",
    "devices",
    "idempotency",
    "processed",
}


def test_an_attribute_with_no_factory_raises_a_clear_attribute_error() -> None:
    uow = Neo4jUnitOfWork(driver=object(), factories={}, clock=None)  # type: ignore[arg-type]

    with pytest.raises(
        AttributeError, match="unit of work has no 'services' repository registered"
    ):
        _ = uow.services


def test_the_default_factories_register_every_repository_of_the_port() -> None:
    assert set(DEFAULT_FACTORIES) == REQUIRED_NAMES
