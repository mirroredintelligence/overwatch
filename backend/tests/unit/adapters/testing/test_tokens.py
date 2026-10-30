"""The test bearer-token helper carries the tenant claim and the epoch (TEN-018).

The default tenant is the harness's run tenant when the harness has set one, so a route test that
seeds its data under the run tenant needs no tenant argument; with none set it is the sample tenant.
"""

from datetime import UTC, datetime

import pytest

from diucs.adapters.testing.tokens import (
    SAMPLE_TENANT,
    TEST_BFF_SECRET,
    TEST_TENANT_ENV,
    default_token_tenant,
    issue_test_token,
)
from diucs.domain.codes import Role
from diucs.domain.rules.bff_token import decode_bff_token

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)


def test_a_token_names_the_tenant_it_is_given() -> None:
    token = issue_test_token(Role.LEAD, ["svc-1"], "prac-1", tenant="tenant-b", epoch=4)

    claims = decode_bff_token(token, TEST_BFF_SECRET, NOW)
    assert (claims.tenant, claims.epoch) == ("tenant-b", 4)


def test_the_epoch_defaults_to_the_first() -> None:
    claims = decode_bff_token(issue_test_token(Role.LEAD, [], "prac-1"), TEST_BFF_SECRET, NOW)

    assert claims.epoch == 1


def test_the_default_tenant_is_the_runs_when_the_harness_set_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TEST_TENANT_ENV, "tt-run-tenant")

    claims = decode_bff_token(issue_test_token(Role.LEAD, [], "prac-1"), TEST_BFF_SECRET, NOW)

    assert claims.tenant == "tt-run-tenant"
    assert default_token_tenant() == "tt-run-tenant"


def test_the_default_tenant_is_the_sample_when_none_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TEST_TENANT_ENV, raising=False)

    assert default_token_tenant() == SAMPLE_TENANT
    claims = decode_bff_token(issue_test_token(Role.LEAD, [], "prac-1"), TEST_BFF_SECRET, NOW)
    assert claims.tenant == SAMPLE_TENANT


def test_an_explicit_tenant_beats_the_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TEST_TENANT_ENV, "tt-run-tenant")

    claims = decode_bff_token(
        issue_test_token(Role.LEAD, [], "prac-1", tenant="tenant-b"), TEST_BFF_SECRET, NOW
    )

    assert claims.tenant == "tenant-b"


def test_a_device_still_rides_along() -> None:
    token = issue_test_token(Role.REPORTER, [], "prac-1", device="phone-1", tenant="tenant-a")

    assert decode_bff_token(token, TEST_BFF_SECRET, NOW).device == "phone-1"
