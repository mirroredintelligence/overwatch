"""TEN-013: the stored hash of a pairing code is keyed by the tenant (U10, DEC-160; D26 tokens).

A pairing code is six digits, so two tenants draw the same codes as often as not. The stored hash
of a code therefore carries the tenant, and a code held by one tenant neither blocks nor matches
another tenant's code. The statements that store and read the hashes are tenant-scoped in
test_link_token_queries.py; these tests pin the keying they are given. Values are synthetic.
"""

from diucs.application.tenancy import ScopeId, ScopeKind
from diucs.application.use_cases.pair_wall_screen import _keyed
from diucs.domain.rules.tokens import hash_token

SECRET = b"link-secret-for-tests-only-0000000000"
CODE = "482913"


def _tenant(value: str) -> ScopeId:
    return ScopeId(value, ScopeKind.TENANT)


def test_the_same_code_in_two_tenants_is_stored_under_two_hashes() -> None:
    assert _keyed(SECRET, _tenant("tenant-a"), CODE) != _keyed(SECRET, _tenant("tenant-b"), CODE)


def test_the_same_code_in_one_tenant_is_stored_under_one_hash() -> None:
    """The hash is what a later read looks up, so it must be the same every time."""
    assert _keyed(SECRET, _tenant("tenant-a"), CODE) == _keyed(SECRET, _tenant("tenant-a"), CODE)


def test_the_stored_hash_of_a_code_is_not_the_bare_hash_of_the_code() -> None:
    """Without the tenant, a code would hash the same in every tenant, and a hash lookup could not
    tell whose code it found."""
    assert _keyed(SECRET, _tenant("tenant-a"), CODE) != hash_token(CODE, SECRET)
