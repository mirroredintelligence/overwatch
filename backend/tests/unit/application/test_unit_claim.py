"""The unit-of-work claim and the scope snapshot (TEN-002, DEC-132 item 4): a unit of work binds
exactly one scope, so a second unit cannot open while one is open in the same context.

The claim is a context variable (`_UNIT`), so it follows the same rules as the scope binding
(lesson L151): a task started from a context that holds a claim copies it and is refused, sibling
tasks started from a context that holds none each get their own.
"""

import asyncio

import pytest

from diucs.application.tenancy import (
    UNIT_OF_WORK_OPEN_MESSAGE,
    ScopeId,
    TenancyError,
    TenantNotBound,
    UnitOfWorkAlreadyOpen,
    bind_scope,
    bind_tenant,
    claim_unit,
    release_unit,
    scope_for_new_unit,
)


def test_the_message_is_the_fixed_text() -> None:
    assert UNIT_OF_WORK_OPEN_MESSAGE == (
        "a unit of work is already open in this context; "
        "open the next one after this one has finished"
    )
    assert issubclass(UnitOfWorkAlreadyOpen, TenancyError)
    assert str(UnitOfWorkAlreadyOpen()) == UNIT_OF_WORK_OPEN_MESSAGE


async def test_a_second_claim_in_one_context_is_refused_with_the_fixed_message() -> None:
    first, second = object(), object()
    claim_unit(first)
    try:
        with pytest.raises(UnitOfWorkAlreadyOpen) as raised:
            claim_unit(second)
        assert str(raised.value) == UNIT_OF_WORK_OPEN_MESSAGE
        # The refused claim did not take the place: the first owner still holds it.
        release_unit(second)
        with pytest.raises(UnitOfWorkAlreadyOpen):
            claim_unit(object())
    finally:
        release_unit(first)


async def test_a_claim_succeeds_again_after_the_owner_released_it() -> None:
    first, second = object(), object()
    claim_unit(first)
    release_unit(first)
    claim_unit(second)
    release_unit(second)
    claim_unit(first)
    release_unit(first)


async def test_a_release_by_another_owner_changes_nothing() -> None:
    owner, stranger = object(), object()
    claim_unit(owner)
    try:
        release_unit(stranger)
        with pytest.raises(UnitOfWorkAlreadyOpen):
            claim_unit(object())
    finally:
        release_unit(owner)
    claim_unit(stranger)
    release_unit(stranger)


async def test_a_second_release_is_a_no_op_and_does_not_free_a_later_claim() -> None:
    first, second = object(), object()
    claim_unit(first)
    release_unit(first)
    claim_unit(second)
    try:
        release_unit(first)
        with pytest.raises(UnitOfWorkAlreadyOpen):
            claim_unit(object())
    finally:
        release_unit(second)


async def test_a_release_with_nothing_claimed_is_a_no_op() -> None:
    release_unit(object())
    claim = object()
    claim_unit(claim)
    release_unit(claim)


async def test_sibling_tasks_started_from_a_context_with_no_claim_each_claim() -> None:
    async def one() -> bool:
        owner = object()
        claim_unit(owner)
        try:
            await asyncio.sleep(0)
            return True
        finally:
            release_unit(owner)

    assert await asyncio.gather(one(), one(), one()) == [True, True, True]


async def test_a_child_task_started_while_the_parent_holds_a_claim_is_refused() -> None:
    async def child() -> None:
        claim_unit(object())

    parent = object()
    claim_unit(parent)
    try:
        with pytest.raises(UnitOfWorkAlreadyOpen):
            await asyncio.create_task(child())
    finally:
        release_unit(parent)


async def test_a_claim_made_in_a_child_task_is_not_held_by_the_parent_afterwards() -> None:
    async def child() -> None:
        claim_unit(object())

    await asyncio.create_task(child())
    claim = object()
    claim_unit(claim)
    release_unit(claim)


# The scope a new unit snapshots


def test_a_new_unit_snapshots_the_bound_scope() -> None:
    with bind_tenant("a1"):
        assert scope_for_new_unit() == ScopeId.tenant("a1")
    with bind_scope(ScopeId.network("net-pilot")):
        assert scope_for_new_unit() == ScopeId.network("net-pilot")


def test_a_new_unit_with_nothing_bound_is_refused() -> None:
    with pytest.raises(TenantNotBound):
        scope_for_new_unit()


def test_the_snapshot_does_not_follow_a_later_rebinding() -> None:
    with bind_tenant("a1"):
        snapshot = scope_for_new_unit()
        with bind_tenant("b1"):
            assert scope_for_new_unit() == ScopeId.tenant("b1")
        assert snapshot == ScopeId.tenant("a1")
