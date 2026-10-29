"""Pure tests of the cache port (P09, TEN-019): the one builder of every cache name, the lock value,
the scope errors, and the rule that only the port builds a name (DEC-130 item 6, DEC-132 items 1
and 4, audit C section 4). No Redis, no fake: the names are the contract the adapters share."""

import ast
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.application.ports.outbound.cache import (
    BOARD_UPDATES_CHANNEL,
    CacheScopeMismatch,
    Lock,
    names_for,
    scope_segment,
    scoped_names,
)
from diucs.application.tenancy import (
    NETWORK_ID_PATTERN,
    TENANT_ID_PATTERN,
    ScopeId,
    TenantNotBound,
    bind_scope,
    bind_tenant,
    is_valid_tenant_id,
)
from diucs.domain.errors import DomainError, ValidationFailed

SRC = Path(__file__).resolve().parents[5] / "src" / "diucs"
PORT_MODULE = SRC / "application" / "ports" / "outbound" / "cache.py"
ADAPTER_MODULES = (
    SRC / "adapters" / "testing" / "memory_cache.py",
    SRC / "adapters" / "outbound" / "cache_redis" / "redis_cache.py",
)
CACHE_METHODS = frozenset(
    {
        "get",
        "set",
        "set_if_absent",
        "delete",
        "publish",
        "subscribe",
        "acquire_lock",
        "release_lock",
    }
)
NAME_PREFIXES = ("cache:", "lock:", "fence:", "chan:")

ACME = ScopeId.tenant("acme-icb")
NW1 = ScopeId.network("net-nw1")
TENANT_IDS = st.from_regex(TENANT_ID_PATTERN, fullmatch=True).filter(is_valid_tenant_id)
NETWORK_IDS = st.from_regex(NETWORK_ID_PATTERN, fullmatch=True)
# Any text without a control character: the replay key's alphabet and more.
NAMES = st.text(
    alphabet=st.characters(
        min_codepoint=0x20,
        max_codepoint=0x10FFFF,
        blacklist_categories=("Cs",),
        blacklist_characters=("\x7f",),
    ),
    min_size=1,
    max_size=60,
)
FAMILY_OF = {"key": "cache", "lock": "lock", "fence": "fence", "channel": "chan"}


def test_the_live_update_channel_is_board_updates() -> None:
    assert BOARD_UPDATES_CHANNEL == "board.updates"


# The names of one tenant (rule 1 and rule 2).


def test_a_tenant_names_its_keys_locks_fences_and_channels_under_its_own_segment() -> None:
    names = names_for(ACME)
    assert names.key("board:v1") == "acme-icb:cache:board:v1"
    assert names.channel(BOARD_UPDATES_CHANNEL) == "acme-icb:chan:board.updates"
    assert names.lock("relay") == "acme-icb:lock:relay"
    assert names.fence("relay") == "acme-icb:fence:relay"


def test_a_network_scope_is_segmented_with_a_leading_underscore() -> None:
    names = names_for(NW1)
    assert names.segment == "_net-nw1"
    assert names.key("board:v1") == "_net-nw1:cache:board:v1"
    assert names.channel(BOARD_UPDATES_CHANNEL) == "_net-nw1:chan:board.updates"


@given(tenant=TENANT_IDS, network=NETWORK_IDS)
def test_a_tenant_segment_and_a_network_segment_are_never_equal(tenant: str, network: str) -> None:
    tenant_segment = scope_segment(ScopeId.tenant(tenant))
    network_segment = scope_segment(ScopeId.network(network))
    assert tenant_segment != network_segment
    assert not tenant_segment.startswith("_")
    assert network_segment.startswith("_")


@given(tenant=TENANT_IDS, name=NAMES, family=st.sampled_from(sorted(FAMILY_OF)))
def test_a_name_parses_back_into_its_segment_family_and_name(
    tenant: str, name: str, family: str
) -> None:
    built = getattr(names_for(ScopeId.tenant(tenant)), family)(name)
    segment, family_part, rest = built.split(":", 2)
    assert (segment, family_part, rest) == (tenant, FAMILY_OF[family], name)


@given(first=st.tuples(TENANT_IDS, NAMES), second=st.tuples(TENANT_IDS, NAMES))
def test_two_different_scope_and_name_pairs_never_give_the_same_key(
    first: tuple[str, str], second: tuple[str, str]
) -> None:
    key_one = names_for(ScopeId.tenant(first[0])).key(first[1])
    key_two = names_for(ScopeId.tenant(second[0])).key(second[1])
    if first != second:
        assert key_one != key_two


@pytest.mark.parametrize("hostile", ["x:cache:y", "../_net-nw1:cache:board:v1", "a:b:c:d"])
def test_a_name_with_colons_or_path_pieces_stays_under_its_own_segment(hostile: str) -> None:
    assert names_for(ACME).key(hostile) == f"acme-icb:cache:{hostile}"


# The bound scope (rule 2 and test 4).


def test_scoped_names_with_no_scope_bound_raises_the_fixed_message() -> None:
    with pytest.raises(TenantNotBound, match="no tenant is bound for this work"):
        scoped_names()


def test_scoped_names_uses_the_scope_bound_and_nothing_after_the_block() -> None:
    with bind_tenant("acme-icb"):
        assert scoped_names().segment == "acme-icb"
    with pytest.raises(TenantNotBound):
        scoped_names()


def test_scoped_names_follows_a_network_binding_too() -> None:
    with bind_scope(NW1):
        assert scoped_names().segment == "_net-nw1"


# Names are checked (rule 2 and test 5).


@pytest.mark.parametrize(
    "bad", ["", "a" * 513, "x\n", "x\x00", "x\x7f", "tab\there", None, b"x", 7]
)
def test_a_bad_name_is_refused_with_a_fixed_message_that_does_not_echo_it(bad: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        names_for(ACME).key(bad)
    text = str(refused.value)
    assert "CANARY" not in text
    if isinstance(bad, str) and bad:
        assert bad not in text


def test_a_name_of_512_characters_is_accepted() -> None:
    assert names_for(ACME).key("a" * 512) == "acme-icb:cache:" + "a" * 512


def test_a_name_may_hold_colons_dots_and_the_replay_alphabet() -> None:
    name = "sms-reply:4f~!@#$%^&*()"
    assert names_for(ACME).lock(name) == f"acme-icb:lock:{name}"


def test_a_refusal_names_the_field_only() -> None:
    with pytest.raises(ValidationFailed) as refused:
        names_for(ACME).key("CANARY\n")
    assert refused.value.field == "name"


# The lock value and its scope (rule 2 and test 6).


def test_a_lock_is_a_value_with_its_name_token_and_scope() -> None:
    assert Lock("relay", 1, "acme-icb") == Lock("relay", 1, "acme-icb")
    assert Lock("relay", 1, "acme-icb") != Lock("relay", 2, "acme-icb")
    assert Lock("relay", 1, "acme-icb") != Lock("relay", 1, "bridge-ccg")


def test_a_lock_cannot_be_changed_after_it_is_issued() -> None:
    lock = Lock("relay", 1, "acme-icb")
    with pytest.raises(AttributeError):
        lock.fencing_token = 2  # type: ignore[misc]


def test_a_cross_scope_release_is_a_scope_mismatch_with_a_fixed_message() -> None:
    error = CacheScopeMismatch()
    assert str(error) == "lock belongs to another scope"
    assert isinstance(error, DomainError)


# Architecture: one wrapper builds every name (test 38).


def _literal_prefix(node: ast.AST) -> str | None:
    """The text a literal starts with: a string constant, the first piece of an f-string, or the
    left side of a concatenation. None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        return _literal_prefix(node.values[0])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_prefix(node.left)
    return None


def _source_files() -> list[Path]:
    return [path for path in SRC.rglob("*.py") if "__pycache__" not in path.parts]


def test_no_module_but_the_port_starts_a_name_with_a_family() -> None:
    offenders: list[str] = []
    for path in _source_files():
        if path == PORT_MODULE:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            text = _literal_prefix(node)
            if text is not None and text.startswith(NAME_PREFIXES):
                offenders.append(f"{path.relative_to(SRC)}:{getattr(node, 'lineno', 0)}")
    assert offenders == []


def _first_statement(function: ast.AST) -> ast.stmt | None:
    body = list(getattr(function, "body", []))
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return body[0] if body else None


def _takes_its_names_first(function: ast.AST) -> bool:
    first = _first_statement(function)
    if not isinstance(first, ast.Assign) or not isinstance(first.value, ast.Call):
        return False
    target = first.value.func
    return isinstance(target, ast.Name) and target.id == "scoped_names"


@pytest.mark.parametrize("module", ADAPTER_MODULES, ids=lambda path: path.name)
def test_every_port_method_of_an_adapter_takes_its_names_first(module: Path) -> None:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    methods = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name in CACHE_METHODS
    ]
    assert {method.name for method in methods} >= CACHE_METHODS
    for method in methods:
        assert _takes_its_names_first(method), f"{module.name}: {method.name}"
