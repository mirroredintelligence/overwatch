"""The domain keeps its own copy of the tenant id rule; this test keeps it equal to the kernel's.

The domain cannot import `diucs.application.tenancy` (DEC-011), so `check_tenant_id` has its own
compiled pattern. This test may import both layers. A divergence fails here, and the fix is a
decision plus aligning the domain with the kernel (TEN-001's validator is the standard).

One deliberate difference: the id `platform` is reserved by the domain (the scope value of
platform-level nodes) and the kernel accepts it, because the kernel only knows the pattern and the
`net-` prefix. The domain layer is the one that refuses `platform`.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.application.tenancy import (
    NETWORK_PREFIX,
    TENANT_ID_PATTERN,
    ScopeId,
    ScopeInvalid,
    is_valid_tenant_id,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant import (
    RESERVED_TENANT_IDS,
    RESERVED_TENANT_PREFIX,
    check_tenant_id,
)
from diucs.domain.model.tenant import TENANT_ID_PATTERN as DOMAIN_PATTERN

CORPUS = [
    "",
    "a",
    "ab",
    "a1",
    "a" * 30,
    "a" * 31,
    "a" * 32,
    "0",
    "00",
    "-a",
    "a-",
    "a--",
    "A",
    "Ab",
    "aB",
    "_a",
    "a_",
    "a b",
    " ab",
    "ab ",
    "ab\n",
    "a:b",
    "a/b",
    "a.b",
    "a*",
    "dorset-icb",
    "example-icb",
    "net-",
    "net-a",
    "net-abc",
    "net-abc-def",
    "ne",
    "net",
    "nets",
    "platform",
    "platform-2",
    "default",
    "\u00e9\u00e9",
    "\u0661\u0662",
    "a\u0300",
]


def _domain_accepts(text: str) -> bool:
    try:
        check_tenant_id(text)
    except ValidationFailed:
        return False
    return True


def _kernel_accepts(text: str) -> bool:
    try:
        ScopeId.tenant(text)
    except ScopeInvalid:
        return False
    return is_valid_tenant_id(text)


def test_the_two_patterns_and_the_reserved_prefix_are_the_same_text() -> None:
    assert DOMAIN_PATTERN.pattern == TENANT_ID_PATTERN
    assert RESERVED_TENANT_PREFIX == NETWORK_PREFIX


def test_the_kernel_validator_and_the_scope_id_agree() -> None:
    for text in CORPUS:
        assert is_valid_tenant_id(text) == _kernel_accepts(text), repr(text)


@pytest.mark.parametrize("text", CORPUS, ids=repr)
def test_the_domain_and_the_kernel_agree_on_the_corpus(text: str) -> None:
    assert _domain_accepts(text) == (_kernel_accepts(text) and text not in RESERVED_TENANT_IDS)


@settings(max_examples=1000, deadline=None)
@given(
    st.one_of(
        st.text(),
        st.from_regex(TENANT_ID_PATTERN, fullmatch=True),
        st.from_regex(r"net-[a-z0-9-]{0,30}", fullmatch=True),
        st.text("ab09-_N:/ \n", max_size=34),
    )
)
def test_property_the_domain_and_the_kernel_agree_on_generated_ids(text: str) -> None:
    assert _domain_accepts(text) == (_kernel_accepts(text) and text not in RESERVED_TENANT_IDS)


def test_the_reserved_id_platform_is_accepted_by_the_kernel_and_refused_by_the_domain() -> None:
    assert ScopeId.tenant("platform").value == "platform"
    assert is_valid_tenant_id("platform")
    with pytest.raises(ValidationFailed):
        check_tenant_id("platform")
