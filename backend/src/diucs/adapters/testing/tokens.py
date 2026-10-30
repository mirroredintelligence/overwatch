"""Test bearer tokens for FHIR route tests (R02, DEC-094, TEN-018).

The secret is synthetic and used only by tests. issue_test_token mints a token the FHIR API accepts
when the app's secret store holds TEST_BFF_SECRET under BFF_SECRET_NAME. A token names its tenant
and the tenant's epoch: by default the harness's run tenant (so a route test that seeds its data
under the run tenant needs no argument), else the sample tenant.
"""

import os
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

from diucs.domain.codes import Role
from diucs.domain.rules.bff_token import BffClaims, encode_bff_token

TEST_BFF_SECRET: Final = b"synthetic-bff-secret-for-route-tests-only-zyxwvutsrq"
# The default outlives every clock a route test moves to (the wave 5 tests run on 29 October and
# later). A fixed date a day after the route clock made every call of a moved clock a 401. A test
# of expiry passes its own expires_at (test_auth.py, test_edge_binding.py).
TEST_TOKEN_EXPIRES_AT: Final = datetime(2030, 12, 31, 23, 59, tzinfo=UTC)
# The environment variable the test harness sets to the run's tenant (tests/conftest.py).
TEST_TENANT_ENV: Final = "DIUCS_TEST_TENANT"
SAMPLE_TENANT: Final = "example-icb"


def default_token_tenant() -> str:
    """The run tenant when the harness set one, else the sample tenant."""
    return os.environ.get(TEST_TENANT_ENV) or SAMPLE_TENANT


def issue_test_token(
    role: Role,
    services: Sequence[str],
    sub: str,
    *,
    device: str | None = None,
    expires_at: datetime = TEST_TOKEN_EXPIRES_AT,
    tenant: str | None = None,
    epoch: int = 1,
    networks: Sequence[str] = (),
) -> str:
    claims = BffClaims(
        sub=sub,
        role=role,
        services=frozenset(services),
        expires_at=expires_at,
        tenant=tenant if tenant is not None else default_token_tenant(),
        epoch=epoch,
        device=device,
        networks=frozenset(networks),
    )
    return encode_bff_token(claims, TEST_BFF_SECRET)
