"""Test bearer tokens for FHIR route tests (R02, DEC-094).

The secret is synthetic and used only by tests. issue_test_token mints a token the FHIR API accepts
when the app's secret store holds TEST_BFF_SECRET under BFF_SECRET_NAME.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

from diucs.domain.codes import Role
from diucs.domain.rules.bff_token import BffClaims, encode_bff_token

TEST_BFF_SECRET: Final = b"synthetic-bff-secret-for-route-tests-only-0123456789"
TEST_TOKEN_EXPIRES_AT: Final = datetime(2026, 10, 24, 13, 12, tzinfo=UTC)


def issue_test_token(
    role: Role,
    services: Sequence[str],
    sub: str,
    *,
    device: str | None = None,
    expires_at: datetime = TEST_TOKEN_EXPIRES_AT,
) -> str:
    claims = BffClaims(
        sub=sub,
        role=role,
        services=frozenset(services),
        expires_at=expires_at,
        device=device,
    )
    return encode_bff_token(claims, TEST_BFF_SECRET)
