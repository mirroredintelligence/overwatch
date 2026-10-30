"""The network registry port (TEN-051, DEC-541): its methods, and the records it hands out."""

import dataclasses
import typing

import pytest

from diucs.application.ports.outbound.network import (
    ActiveGrant,
    NetworkRecordInvalid,
    NetworkRegistry,
    RegisteredNetwork,
)
from tests.support.network_samples import SETTINGS, make_grant, make_member, make_network

READS = {
    "get_network",
    "memberships",
    "memberships_of",
    "active_membership",
    "get_grant",
    "grants",
    "grants_of",
    "active_grants_for",
    "get_listing",
    "listings",
    "listings_of",
}
WRITES = {
    "create_network",
    "save_network",
    "create_membership",
    "save_membership",
    "create_grant",
    "save_grant",
    "create_listing",
    "save_listing",
}


def test_the_port_is_these_eleven_reads_and_eight_writes() -> None:
    assert typing.get_protocol_members(NetworkRegistry) == READS | WRITES


def test_the_records_the_port_hands_out_are_frozen() -> None:
    registered = RegisteredNetwork(make_network(), SETTINGS)
    active = ActiveGrant(registered, make_grant(), make_member())
    for record, field in ((registered, "network"), (active, "grant")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(record, field, None)
    assert [f.name for f in dataclasses.fields(ActiveGrant)] == ["network", "grant", "membership"]
    assert [f.name for f in dataclasses.fields(RegisteredNetwork)] == ["network", "settings"]


def test_a_record_fault_is_a_runtime_error_with_the_message_it_was_given() -> None:
    assert issubclass(NetworkRecordInvalid, RuntimeError)
    assert str(NetworkRecordInvalid("a network record in the registry is not valid")) == (
        "a network record in the registry is not valid"
    )
