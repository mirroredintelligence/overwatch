"""The cache's platform namespace (TEN-040): names that belong to no tenant, for the limiter of the
unauthenticated routes. The segment is fixed, no tenant name can fall in it, and building a platform
name needs no bound scope."""

import pytest

from diucs.application.ports.outbound.cache import (
    PLATFORM_SEGMENT,
    names_for,
    platform_names,
    scope_segment,
)
from diucs.application.tenancy import ScopeId, bind_tenant, current_scope_or_none
from diucs.domain.errors import ValidationFailed


def test_the_platform_segment_is_one_underscore() -> None:
    assert PLATFORM_SEGMENT == "_"


def test_a_platform_name_is_built_with_no_scope_bound() -> None:
    assert current_scope_or_none() is None
    assert platform_names().key("rl:public") == "_:cache:rl:public"


def test_a_platform_name_ignores_the_bound_tenant() -> None:
    with bind_tenant("acme-icb"):
        assert platform_names().key("rl:public") == "_:cache:rl:public"


def test_no_tenant_or_network_scope_has_the_platform_segment() -> None:
    assert scope_segment(ScopeId.tenant("acme-icb")) != PLATFORM_SEGMENT
    assert scope_segment(ScopeId.network("net-nw1")) != PLATFORM_SEGMENT
    assert names_for(ScopeId.tenant("acme-icb")).key("x") != platform_names().key("x")


@pytest.mark.parametrize("bad", ["", "a\nb", "x" * 513])
def test_a_platform_name_is_checked_like_any_name(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        platform_names().key(bad)
