"""What the REST edge decides about a verified token and the tenant record it names (TEN-018).

The tenant comes from the signed claim. The record is the platform's own, so a suspend takes effect
before the token expires (H-T23): the token carries the tenant's `epoch` and is refused when the
record has moved on. Pure: the rule takes the record, the claim and the request's method.
Every refusal is the one verdict, so the edge answers every cause the same way.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.domain.codes import Role
from diucs.domain.model.tenant import SuspendMode, SuspendReason, Tenant, TenantStatus
from diucs.domain.rules.edge_access import EdgeVerdict, edge_verdict
from tests.support.tenant_samples import make_tenant

TENANT_ID = "example-icb"
SUSPENDED_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def active(epoch: int = 1) -> Tenant:
    return make_tenant(TenantStatus.ACTIVE, epoch=epoch)


def suspended(mode: SuspendMode, epoch: int = 2) -> Tenant:
    return make_tenant(
        TenantStatus.SUSPENDED,
        epoch=epoch,
        suspend_mode=mode,
        suspend_reason=SuspendReason.SECURITY_INCIDENT,
        suspended_at=SUSPENDED_AT,
    )


def verdict(
    tenant: Any,
    *,
    epoch: Any = 1,
    role: Any = Role.ADVISOR,
    method: Any = "GET",
    claimed: Any = TENANT_ID,
) -> EdgeVerdict:
    return edge_verdict(tenant, claimed_tenant=claimed, token_epoch=epoch, role=role, method=method)


def test_an_active_tenant_with_a_current_token_is_allowed() -> None:
    assert verdict(active()) is EdgeVerdict.ALLOWED


@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
def test_an_active_tenant_allows_every_method(method: str) -> None:
    assert verdict(active(), method=method) is EdgeVerdict.ALLOWED


@pytest.mark.parametrize("role", [role for role in Role if role is not Role.PLATFORM_OPERATOR])
def test_an_active_tenant_allows_every_tenant_role(role: Role) -> None:
    assert verdict(active(), role=role) is EdgeVerdict.ALLOWED


def test_no_record_is_refused() -> None:
    assert verdict(None) is EdgeVerdict.REFUSED


def test_the_operator_role_has_no_data_access_at_this_edge() -> None:
    assert verdict(active(), role=Role.PLATFORM_OPERATOR) is EdgeVerdict.REFUSED


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_the_operator_role_is_refused_whatever_the_method(method: str) -> None:
    assert verdict(active(), role=Role.PLATFORM_OPERATOR, method=method) is EdgeVerdict.REFUSED


def test_a_record_for_another_tenant_than_the_claim_is_refused() -> None:
    # A directory that returned the wrong record (a cache keyed wrongly) must never let a token in.
    assert verdict(active(), claimed="tenant-b") is EdgeVerdict.REFUSED


@pytest.mark.parametrize(
    "status",
    [
        TenantStatus.PROVISIONING,
        TenantStatus.OFFBOARDING,
        TenantStatus.OFFBOARDED,
        TenantStatus.PURGED,
    ],
)
def test_a_tenant_that_is_not_active_or_suspended_is_refused(status: TenantStatus) -> None:
    assert verdict(make_tenant(status)) is EdgeVerdict.REFUSED


# ---------------------------------------------------------------- the epoch (H-T23)


def test_a_token_from_before_the_epoch_moved_is_refused() -> None:
    assert verdict(active(epoch=3), epoch=2) is EdgeVerdict.REFUSED


def test_a_token_one_epoch_behind_is_refused() -> None:
    assert verdict(active(epoch=2), epoch=1) is EdgeVerdict.REFUSED


def test_a_token_ahead_of_the_record_says_the_record_may_be_behind() -> None:
    # The record may be a cached copy that has not seen a resume yet: the edge reads it again once.
    assert verdict(active(epoch=1), epoch=2) is EdgeVerdict.RECORD_BEHIND


def test_a_token_far_ahead_of_the_record_is_the_same_verdict() -> None:
    assert verdict(active(epoch=1), epoch=900) is EdgeVerdict.RECORD_BEHIND


@pytest.mark.parametrize("epoch", [0, -1, 1.0, "1", None, True, False])
def test_an_epoch_that_is_not_a_positive_whole_number_is_refused(epoch: Any) -> None:
    assert verdict(active(), epoch=epoch) is EdgeVerdict.REFUSED


def test_an_epoch_that_is_a_bool_is_refused_even_when_it_equals_the_record() -> None:
    assert verdict(active(epoch=1), epoch=True) is EdgeVerdict.REFUSED


# ---------------------------------------------------------------- suspended tenants


def test_a_blocked_suspension_refuses_everyone_and_every_method() -> None:
    record = suspended(SuspendMode.BLOCKED)

    for role in (Role.TENANT_ADMIN, Role.ADVISOR, Role.LEAD, Role.WALL):
        for method in ("GET", "HEAD", "POST"):
            assert verdict(record, epoch=2, role=role, method=method) is EdgeVerdict.REFUSED


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_a_read_only_suspension_lets_the_tenant_admin_read(method: str) -> None:
    record = suspended(SuspendMode.READ_ONLY)

    assert verdict(record, epoch=2, role=Role.TENANT_ADMIN, method=method) is EdgeVerdict.ALLOWED


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "get", ""])
def test_a_read_only_suspension_refuses_a_write_even_from_the_tenant_admin(method: str) -> None:
    record = suspended(SuspendMode.READ_ONLY)

    assert verdict(record, epoch=2, role=Role.TENANT_ADMIN, method=method) is EdgeVerdict.REFUSED


@pytest.mark.parametrize("role", [role for role in Role if role is not Role.TENANT_ADMIN])
def test_a_read_only_suspension_refuses_every_other_role(role: Role) -> None:
    record = suspended(SuspendMode.READ_ONLY)

    assert verdict(record, epoch=2, role=role, method="GET") is EdgeVerdict.REFUSED


def test_a_token_from_before_the_suspend_is_refused_even_for_a_read_only_read() -> None:
    # The suspend raised the epoch: the admin signs in again to get a token for the new epoch.
    record = suspended(SuspendMode.READ_ONLY, epoch=2)

    assert verdict(record, epoch=1, role=Role.TENANT_ADMIN) is EdgeVerdict.REFUSED


def test_a_suspended_record_with_a_token_ahead_of_it_may_be_a_stale_copy() -> None:
    record = suspended(SuspendMode.READ_ONLY, epoch=2)

    assert verdict(record, epoch=3, role=Role.TENANT_ADMIN) is EdgeVerdict.RECORD_BEHIND


# ---------------------------------------------------------------- fail closed on odd input


@pytest.mark.parametrize("tenant", ["example-icb", 7, object(), {"id": TENANT_ID}])
def test_a_record_that_is_not_a_tenant_is_refused(tenant: Any) -> None:
    assert verdict(tenant) is EdgeVerdict.REFUSED


@pytest.mark.parametrize("role", ["advisor", None, 7])
def test_a_role_that_is_not_a_role_member_is_refused(role: Any) -> None:
    assert verdict(active(), role=role) is EdgeVerdict.REFUSED


@pytest.mark.parametrize("method", [None, 7, b"GET"])
def test_a_method_that_is_not_text_is_refused(method: Any) -> None:
    assert verdict(active(), method=method) is EdgeVerdict.REFUSED


def test_a_lookalike_record_with_a_text_status_is_refused() -> None:
    # Lesson L3: `"active"` equals TenantStatus.ACTIVE, and must not stand in for it.
    class Lookalike:
        id = TENANT_ID
        epoch = 1
        status = "active"
        suspend_mode = None

    assert verdict(Lookalike()) is EdgeVerdict.REFUSED


def test_the_verdicts_are_three_distinct_values() -> None:
    assert len({EdgeVerdict.ALLOWED, EdgeVerdict.REFUSED, EdgeVerdict.RECORD_BEHIND}) == 3
