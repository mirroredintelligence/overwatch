"""Named Cypher queries and the registry of fixed statements (DEC-130 item 3, DEC-142).

Every statement is fixed text in the code, registered once with a name, its text and a scenario.
`run_query` takes only a registered `NamedQuery`: no string, no text built at the call. Only the id
ever reaches telemetry, never the Cypher text.

The check at registration is cheap and is not a proof. A tenant statement must carry a
`tenantId: $tenant` entry and a `Scenario`, always: there is no ratchet and no list of ids that
are excused (TEN-030 ended it, DEC-440). A global statement must be on the short
allowlist `GLOBAL_QUERY_IDS` and be pinned in `GLOBAL_STATEMENTS` by the SHA-256 of its exact text
(that pin is the guarantee, TEN-007 round 2); it must also not mention `$tenant`, must be read-only
and may name registry labels only (`GLOBAL_STATEMENT_LABELS`), as defence in depth. That
catches omissions only. The proof
that a statement cannot read or change another tenant's data is the generated two-tenant test that
runs each statement's scenario on a real Neo4j (TEN-004). The `Scenario` type and its validator
are in `scenario.py` (DEC-150).

A statement that needs a label or a relationship type is a `QueryTemplate`: one fixed text with
one `{insert}` place. `QueryRegistry.instance` expands it, once per insert, and only for an insert
that is a chain of label names (`:Resource:Organization`), so nothing but identifiers can be put
into the text.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from diucs.adapters.outbound.graph_store.scenario import Scenario
from diucs.adapters.outbound.graph_store.scope_labels import (
    NETWORK_ONLY_LABELS,
    REGISTRY_NODE_LABELS,
    SCOPE_GENERIC_LABELS,
)

_MODES = ("read", "write")
_SCOPES = ("tenant", "global", "platform")
Scope = Literal["tenant", "global", "platform"]

# `$tenant` and not `$tenantId`, `$tenants` or `$tenant_x`.
_TENANT_PARAMETER = re.compile(r"\$tenant\b")
# The predicate itself: a map entry `tenantId: $tenant`. `$tenant` in a result, a comparison or a
# comment is not one (a comment and the inside of a string are blanked before the look).
_TENANT_ENTRY = re.compile(r"\btenantId\s*:\s*\$tenant\b")

# The kinds of scope a statement runs in (TEN-037, DEC-132 item 4): a tenant, a network, or both for
# the statements that are scope-stamped and label-generic. A statement's kinds are one of these
# three exact values; `run_query` refuses a statement in a scope of another kind.
TENANT_KINDS: Final = frozenset({"tenant"})
NETWORK_KINDS: Final = frozenset({"network"})
BOTH_KINDS: Final = frozenset({"tenant", "network"})
_KIND_SETS: Final = (TENANT_KINDS, NETWORK_KINDS, BOTH_KINDS)

# `$sourceTenant`: the member a projection came from. Only a network-only statement may mention it.
_SOURCE_TENANT_PARAMETER = re.compile(r"\$sourceTenant\b")
_BRACKETS = re.compile(r"\[[^\[\]]*\]")
_BRACES = re.compile(r"\{[^{}]*\}")
_LABEL_NAME = re.compile(r":\s*(`[^`]*`|[A-Za-z_]\w*)")

PLACEHOLDER: Final = "{insert}"
# `:Label` or `:Label:Other` or `:HAS_X`: ASCII identifiers only. fullmatch, so no trailing text.
_INSERT = re.compile(r"(?::[A-Za-z_][A-Za-z0-9_]*)+")
# A plain statement id has no colon: `Q-RES-UPSERT-ROOT:Resource:Organization` is an instance of
# the template `Q-RES-UPSERT-ROOT`, and a template instance is judged by its template.
_INSTANCE_SEPARATOR: Final = ":"

# The short global allowlist (DEC-130 item 3): statements that run before any tenant is known or
# on data that is shared. Each has the reason it is here. Adding one is a deliberate change: the
# list and the text of every statement on it are pinned in test_global_allowlist.py, and a global
# statement must be read-only and may name registry labels only (GLOBAL_STATEMENT_LABELS), so being
# on this list does not let a statement reach a tenant's data. Later tasks add theirs (the
# link-token hash lookup, the network registry) in their own commit.
GLOBAL_QUERY_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Q-NEO4J-PING": "the health ping answers RETURN 1: no data, and no tenant is known yet",
        "Q-TENANT-GET": (
            "reads one Tenant registry node by id: registry data only, and the caller needs the "
            "record before a tenant is bound"
        ),
        "Q-TENANT-LIST-ACTIVE": (
            "lists the Tenant registry nodes that are active, for the workers that visit each "
            "tenant in turn"
        ),
        "Q-TENANT-ACTIVE-IDS": (
            "lists the ids of the active Tenant registry nodes, so the outbox relay can bind each "
            "tenant in turn without reading a whole record"
        ),
        "Q-TENANT-BY-NUMBER": (
            "finds the tenant of an active TenantNumber registry node by the number called and "
            "the Twilio account (DEC-131 item 2): the tenant is not known until this answers"
        ),
        "Q-TENANT-BY-ACCOUNT": (
            "finds the tenant of the active TenantNumber registry nodes of a Twilio account, for "
            "delivery receipts (DEC-131 item 2): matched by account alone"
        ),
        "Q-TENANT-ACTIVE-LINE": (
            "reads the active number of one active Tenant (the bound tenant, I10 outbound "
            "sender): registry data for that id only, and the caller is already bound to it"
        ),
        "Q-TENANT-BY-HOST": (
            "finds the Tenant registry node of a host name (DEC-134 item 3): the host of an "
            "unauthenticated request is the only thing that names its tenant"
        ),
        "Q-TENANT-BY-ENTRA": (
            "finds the Tenant registry node bound to an Entra directory id (DEC-134 item 14): "
            "sign-in maps a verified directory to exactly one tenant"
        ),
        "Q-INVARIANT-UNSTAMPED": (
            "counts, by label set, the nodes that carry no tenantId and are not registry nodes "
            "(TEN-031): Community cannot require the property, so this is the control; it scans "
            "the whole graph and returns label names and a count, never a value"
        ),
        "Q-INVARIANT-CROSS-SCOPE": (
            "counts, by relationship type, the relationships that join two scopes (TEN-031): it "
            "scans the whole graph and returns a type and a count, never a value"
        ),
        "Q-NETWORK-GET": (
            "reads one Network registry node by id (its settings included): registry data only, "
            "and the caller needs it before a network scope is bound"
        ),
        "Q-NETWORK-MEMBERSHIPS": (
            "lists every NetworkMembership registry row of one network, history included: "
            "registry data only, for network administration"
        ),
        "Q-NETWORK-MEMBERSHIPS-OF": (
            "lists every NetworkMembership registry row of one tenant in every network: registry "
            "data only, so a sign-in can learn which networks a tenant is in"
        ),
        "Q-NETWORK-MEMBERSHIP-ACTIVE": (
            "reads the active NetworkMembership registry row of one tenant in one network: the "
            "membership check of every network read, made before a network scope is bound"
        ),
        "Q-NETWORK-GRANT-GET": (
            "reads one Grant registry node by id: registry data only, for the grant use cases"
        ),
        "Q-NETWORK-GRANTS": (
            "lists the Grant registry nodes of one network: registry data only, for network "
            "administration"
        ),
        "Q-NETWORK-GRANTS-OF": (
            "lists the Grant registry nodes a tenant has given: registry data only, for the "
            "grantor's own administration"
        ),
        "Q-NETWORK-GRANT-ACTIVE-FOR": (
            "reads the approved Grant registry nodes of one grantor and scope with their active "
            "Network and NetworkMembership registry rows: the projector's gate, read before any "
            "scope is bound"
        ),
        "Q-NETWORK-LISTING-GET": (
            "reads one Listing registry node by id: registry data only, for the listing use cases"
        ),
        "Q-NETWORK-LISTINGS": (
            "lists the Listing registry nodes of one network: registry data only, for the owner's "
            "admission queue and the network directory"
        ),
        "Q-NETWORK-LISTINGS-OF": (
            "lists the Listing registry nodes of one member in one network: registry data only, "
            "for the member's own view of its listings"
        ),
        "Q-NETWORK-CREATE": (
            "creates one Network registry node; the registry is global and a unique key refuses a "
            "second network with the same id"
        ),
        "Q-NETWORK-SAVE": (
            "changes one Network registry node when it is in the status the caller expects: the "
            "only write on a registry node that matches by id and status"
        ),
        "Q-NETWORK-MEMBER-CREATE": (
            "creates one NetworkMembership registry node when the tenant has no invited or active "
            "row in the network, after taking the Network registry node's lock"
        ),
        "Q-NETWORK-MEMBER-SAVE": (
            "changes one NetworkMembership registry node when it is in the status the caller "
            "expects, matched by id, network and member"
        ),
        "Q-NETWORK-GRANT-CREATE": (
            "creates one Grant registry node; a unique key on network, grantor, scope and version "
            "refuses a second row"
        ),
        "Q-NETWORK-GRANT-SAVE": (
            "changes the approvals, window and end of one Grant registry node when it is in the "
            "status the caller expects, matched by id, network and grantor"
        ),
        "Q-NETWORK-LISTING-CREATE": (
            "creates one Listing registry node when the service has no live listing in the "
            "network, after taking the Network registry node's lock"
        ),
        "Q-NETWORK-LISTING-SAVE": (
            "changes the decision of one Listing registry node when it is in the status the "
            "caller expects, matched by id, network, source and service"
        ),
    }
)

# The two statements that count over the whole graph (TEN-031, the start-up and daily invariant
# check). A scan of every node names no label, so the label rule of `_check_global_text` cannot hold
# for them; what stands in its place, for these ids only, is that the text returns a label set or
# a relationship type and a count and nothing else, so no property value can leave the graph. The
# digest pin is still the guarantee. Adding an id here is as deliberate as adding one to the
# allowlist, and test_global_allowlist.py pins the set.
# The only global statements that may write (TEN-051): the guarded creates and compare-and-sets of
# the network registry. A global write is a `CREATE` or a `SET` on a network registry label
# (`NETWORK_REGISTRY_LABELS`) and nothing else: no delete, no procedure, no map or label assignment.
# It is on GLOBAL_QUERY_IDS and pinned by digest like every global statement. Adding an id here is
# as deliberate as adding one to the allowlist, and test_global_allowlist.py pins the set.
GLOBAL_WRITE_IDS: Final[frozenset[str]] = frozenset(
    {
        "Q-NETWORK-CREATE",
        "Q-NETWORK-SAVE",
        "Q-NETWORK-MEMBER-CREATE",
        "Q-NETWORK-MEMBER-SAVE",
        "Q-NETWORK-GRANT-CREATE",
        "Q-NETWORK-GRANT-SAVE",
        "Q-NETWORK-LISTING-CREATE",
        "Q-NETWORK-LISTING-SAVE",
    }
)
NETWORK_REGISTRY_LABELS: Final[frozenset[str]] = frozenset(
    {"Network", "NetworkMembership", "Grant", "Listing"}
)

GLOBAL_WHOLE_GRAPH_IDS: Final[frozenset[str]] = frozenset(
    {"Q-INVARIANT-UNSTAMPED", "Q-INVARIANT-CROSS-SCOPE"}
)

# The platform statements (TEN-028, DEC-503): the few statements that write the tenant registry.
# The registry nodes carry no tenant (DEC-132), so a tenant statement cannot write them, and a
# global statement is read-only (DEC-163 item 3). Creating a tenant, moving it through its
# lifecycle and recording its numbers, host and directory are the platform operator's work, so
# they have a scope of their own: `scope="platform"`, an id on this list with a reason, the
# SHA-256 pin of its exact text in PLATFORM_STATEMENTS, registry labels only, CREATE, MERGE and SET
# only (never a delete, a procedure call or a loop), no `$tenant`. They run only through
# `run_platform_query`, only from `graph_store/tenant_registry.py` (an architecture test), which
# only the composition root builds. Adding one is as deliberate as adding a global statement.
PLATFORM_QUERY_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Q-TENANT-REG-CREATE": (
            "creates one Tenant registry node, in provisioning, with a new id: the tenant exists "
            "nowhere else yet, so no tenant is bound"
        ),
        "Q-TENANT-REG-SAVE": (
            "writes the lifecycle fields of one Tenant registry node when its epoch and status "
            "are still the ones the operator read (compare and set): activation, suspension, "
            "resume and the references of a tenant"
        ),
        "Q-TENANT-REG-SET-HOST": (
            "sets the host of one Tenant registry node: unique across tenants by constraint"
        ),
        "Q-TENANT-REG-SET-DIRECTORY": (
            "sets the Entra directory id of one Tenant registry node: unique across tenants by "
            "constraint"
        ),
        "Q-TENANT-REG-PUT-NUMBER": (
            "records one TenantNumber registry node of a Tenant: the number is unique across "
            "tenants by constraint, so another tenant's number is refused, never moved"
        ),
        "Q-TENANT-REG-MARK-TESTED": (
            "records that a test text was delivered from one TenantNumber registry node"
        ),
        "Q-TENANT-REG-NUMBERS": (
            "reads the TenantNumber registry nodes of one Tenant, for its activation facts"
        ),
        "Q-TENANT-REG-LIST": (
            "lists every Tenant registry node whatever its status, for the platform operator's "
            "tenant list: registry data only, and the operator is the only caller"
        ),
        "Q-TENANT-REG-GET": (
            "reads one Tenant registry node with its host and directory, for the platform "
            "operator's tenant detail: registry data only"
        ),
        "Q-PLATFORM-AUDIT-LOCK": (
            "takes the head of the platform audit chain (the platform registry's own chain, "
            "created on first use) and reads where it stands, so appends queue on the head"
        ),
        "Q-PLATFORM-AUDIT-APPEND": (
            "adds one link to the platform audit chain when the head is still at the sequence "
            "the caller read, and moves the head: the platform registry's append-only record of "
            "what the platform's own people did"
        ),
        "Q-PLATFORM-AUDIT-ENTRIES": (
            "reads the links of the platform audit chain after a sequence, oldest first: platform "
            "registry data, for the operator's access log and for the chain's own check"
        ),
        "Q-PLATFORM-AUDIT-HEAD": (
            "reads where the platform audit chain stands: platform registry data only"
        ),
        "Q-SUPPORT-TICKET-ADD": (
            "creates one SupportAccessTicket platform registry node: a support person's request "
            "for access to one tenant, kept in the platform registry so both sides read one record"
        ),
        "Q-SUPPORT-TICKET-OF-TENANT": (
            "reads one SupportAccessTicket platform registry node by id when it names the tenant "
            "the caller gives (the bound tenant of the administrator who asks)"
        ),
        "Q-SUPPORT-TICKET-OF-PRINCIPAL": (
            "reads one SupportAccessTicket platform registry node by id when the support person "
            "the caller gives asked for it"
        ),
        "Q-SUPPORT-TICKETS-OF-TENANT": (
            "lists the SupportAccessTicket platform registry nodes that name one tenant, newest "
            "first, for that tenant's administrator"
        ),
        "Q-SUPPORT-TICKETS-OF-PRINCIPAL": (
            "lists the SupportAccessTicket platform registry nodes one support person asked for, "
            "newest first"
        ),
        "Q-SUPPORT-TICKET-MOVE": (
            "changes one SupportAccessTicket platform registry node when it names the tenant and "
            "is in the state the caller read (compare and set): a decision, an opening, an end"
        ),
    }
)

# THE GUARANTEE (TEN-007 round 2, DEC-163 item 2): every global statement is pinned by the SHA-256
# of its exact text, stripped of leading and trailing whitespace and nothing else. A global
# statement registers only when its id is in this mapping AND the digest of its text equals the one
# here, so a changed byte, a comment, a case change or a new clause is refused. Adding or changing a
# global statement is a deliberate edit of this constant, to be reviewed like any security-relevant
# diff, with its reason in GLOBAL_QUERY_IDS and its text in test_global_allowlist.py. The structural
# checks below are a second defence, not a parser and not the guarantee: DEC-142 chose a registry
# of fixed statements over any analysis of arbitrary Cypher, and an earlier Cypher reader leaked
# through every verification round.
GLOBAL_STATEMENTS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Q-NEO4J-PING": "505067033faf8e26ec2f3ea6c987e7e79bb32316d5db6e84ad32b16ff2e6f81b",
        "Q-TENANT-GET": "965a4ab096723692fa714be037e194e81dc2a8b017d6fc3e71c9f6a87b2b80be",
        "Q-TENANT-LIST-ACTIVE": "8060d795ec86eea21ee4368cc2406b7530211faec8750e3e4ec23529f20d340d",
        "Q-TENANT-ACTIVE-IDS": "230af35beaafb4e989676fe9c7dc999173adc599ee2e13a65b004b8475a7ed98",
        "Q-TENANT-BY-NUMBER": "f8b70805b9fc22b2d3e55ebcb146543528bb44e4f63251690ab60fd8c5ff65c6",
        "Q-TENANT-BY-ACCOUNT": "d835f568a9fb00629afba8db585d72d9d516d90aceea42191046fee236891550",
        "Q-TENANT-ACTIVE-LINE": "5d63a256430a4267c7848d6f6e445759b94049a937ef9631a1d042d915182f76",
        "Q-TENANT-BY-HOST": "6d54e9494484becff85e4c68de1c95f2e070c302e575657011295042235a2d21",
        "Q-TENANT-BY-ENTRA": "cde6d057e41dba1d35ca029ef4f29e51b16d1d4e0c9dfd909d297bcaba844888",
        "Q-INVARIANT-UNSTAMPED": "795489a314b9d937367c5d30b530ded1f438ece68ffc863bcb3bcb013ed90f3f",
        "Q-INVARIANT-CROSS-SCOPE": (
            "bbd3e4db80928a1d8dba2bf3991dc4c840acd649e682b3b0961f04ed9e55a179"
        ),
        "Q-NETWORK-GET": ("ff1b798a243eaa94d749d8b5a139f0982b27d3cd2ac06cf2cd75caf36277a08a"),
        "Q-NETWORK-MEMBERSHIPS": (
            "cf92e1d41dd751757ebd3e335cb2e62626eb945ed2876bc24e3ca61fbb3eb214"
        ),
        "Q-NETWORK-MEMBERSHIPS-OF": (
            "1100de69d690b2e2a4968ad121edec6e1cdc2314410cb37a055665d2ff8c9a70"
        ),
        "Q-NETWORK-MEMBERSHIP-ACTIVE": (
            "17a281a087580bb9b9a8478e5da681907fe0406b80ecec2f5618e75c6aac1397"
        ),
        "Q-NETWORK-GRANT-GET": ("f05af3f980f16e2cfa85ae16f255baff496a037ae8e31f1a3c26822925ca1fa2"),
        "Q-NETWORK-GRANTS": ("aa91b805e94484416c56359dcb1ef3da190b1a32643a722b4adf9b1c1056064e"),
        "Q-NETWORK-GRANTS-OF": ("b78b32896edb14f2f2e911589b63921132f9909c652df6b5cc49ab4e8f4e1672"),
        "Q-NETWORK-GRANT-ACTIVE-FOR": (
            "0a6e6f512ff465e7938b8f45da1d41ce8ab2fb005c0ac1ca058af47e489b4b1b"
        ),
        "Q-NETWORK-LISTING-GET": (
            "5b4b13d3cd3a3dcecba20e96263461ee5a1710b765705f5d6334bc07dcb9f2f6"
        ),
        "Q-NETWORK-LISTINGS": ("5f7d8ca16ae152b94c7b81cb163e4ef0fc92d01c777ec2533df570b704317a57"),
        "Q-NETWORK-LISTINGS-OF": (
            "30e09997dd51efc743e928f49d37dfcdb923d5d5f9d63e552373570f85057e8c"
        ),
        "Q-NETWORK-CREATE": ("8732644ba94620e596d76bd7bc82f1506427eaa5aec83f36289684d403f5866d"),
        "Q-NETWORK-SAVE": ("e6295bff855065317509834639d601ea030a0cb0de9693b3aab2efc30cb58dfc"),
        "Q-NETWORK-MEMBER-CREATE": (
            "1b53050ab54e6ffd5b92f88e0057d923f1a1dc6c157fa89d777b4c022b7a1416"
        ),
        "Q-NETWORK-MEMBER-SAVE": (
            "6d5dd5a7849237358e0f88eab5891c94f657d8fd44b6abe5c16b39f476ec5e65"
        ),
        "Q-NETWORK-GRANT-CREATE": (
            "7810b92b84614a07ce88d4859534c9401545bdece5cfcdaba63aa474552c7d93"
        ),
        "Q-NETWORK-GRANT-SAVE": (
            "49ce209d320428c2231e6e763932dced25f8336f1d5cb890ce76ec0b23aaca6c"
        ),
        "Q-NETWORK-LISTING-CREATE": (
            "5facf39c4da9be8e85618bf69dafe60e4766b0997e750801bbafb31e57007509"
        ),
        "Q-NETWORK-LISTING-SAVE": (
            "9e65052c9ff7532bdf1b3334be13c1da9f5051ba04b8f0d10ffde4f80b35a2bd"
        ),
    }
)


# The pin of each platform statement, as for the global ones (see GLOBAL_STATEMENTS).
PLATFORM_STATEMENTS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Q-TENANT-REG-CREATE": ("e16c9163a9fb8d58cc0956502926eb28780534514897f52767d7957196dc85db"),
        "Q-TENANT-REG-SAVE": ("3c91de7d4e95ffc373d5a925b99dead381fc377f9c5494b0f33a209e7042da6c"),
        "Q-TENANT-REG-SET-HOST": (
            "81f488eb7dd2f5efe7122a0b1c6a748d4ad0fec42bb58b078999ebb39584ca5c"
        ),
        "Q-TENANT-REG-SET-DIRECTORY": (
            "fd9b8905e44244f759edf96b65ce531e34334512301596ec84977e29b28b1e1c"
        ),
        "Q-TENANT-REG-PUT-NUMBER": (
            "dfc4def5a3d9af616f9898d1c9967a606adb070005984e503e0820d9d5efbf85"
        ),
        "Q-TENANT-REG-MARK-TESTED": (
            "797ca905a9d0a4b6b990edc1c33e5848283852dadc98899b386d95a732f470dd"
        ),
        "Q-TENANT-REG-NUMBERS": (
            "4d79b14ddb793344cadceda9973790d53551f1e8e1730e8bba2e13b69853c6eb"
        ),
        "Q-TENANT-REG-LIST": ("ac2dce20e0c19f359f2cdc4450d09356326ab89cbc9e65d1e703bd67368aec6e"),
        "Q-TENANT-REG-GET": ("73f61ba62534e1e5a48eeab6d353982534fd33f666d23484766673621bac7be0"),
        "Q-PLATFORM-AUDIT-LOCK": (
            "bcde6de470ba527d604ddc07a9baeec320910393f1bbddfa45dde75270c0a9ba"
        ),
        "Q-PLATFORM-AUDIT-APPEND": (
            "c01aeea2e1eb4da9ad5d2c5ebad5385c759248ef16fa42bee15544ca07344bc7"
        ),
        "Q-PLATFORM-AUDIT-ENTRIES": (
            "efa2cb8a32e6688ad29046b8762656440a1fa7f8f08a06f48da08c8ad9bb26c1"
        ),
        "Q-PLATFORM-AUDIT-HEAD": (
            "bda6b0cff54eb347e1316c647f9adc87b39bd2fa1e0f098f0ccbdc97fbd6f6e7"
        ),
        "Q-SUPPORT-TICKET-ADD": (
            "746b4e4296ed8ba20a9de7b09268b401c1ce937220376ad71c673a6dd227a75c"
        ),
        "Q-SUPPORT-TICKET-OF-TENANT": (
            "0a80d9a6f5a4592c6d132eebb1270dbe9296131d0393dca116b3454851c29a44"
        ),
        "Q-SUPPORT-TICKET-OF-PRINCIPAL": (
            "485cdf23b17f42882509d58d0d3951d8929006fead53fa23682f3a1d985687ea"
        ),
        "Q-SUPPORT-TICKETS-OF-TENANT": (
            "2b8c4bb3101d8579494eec85603e36a0de27d6b2e4b71e38d19872c3df6cb885"
        ),
        "Q-SUPPORT-TICKETS-OF-PRINCIPAL": (
            "48262d7062f10f902f62edfdc945602b303bc6eb4bb7b54289b12ddb282241ce"
        ),
        "Q-SUPPORT-TICKET-MOVE": (
            "801a0ffd16d03d5f37278f7c3de90206bde3355875b76081879c83a75d7d690a"
        ),
    }
)


def statement_digest(cypher: str) -> str:
    """The SHA-256 hex digest of a statement's text, stripped of leading and trailing whitespace
    and otherwise unchanged: the value pinned in GLOBAL_STATEMENTS."""
    return hashlib.sha256(cypher.strip().encode("utf-8")).hexdigest()


# The labels a global statement may name: the registry nodes, which carry no tenant (DEC-132,
# `REGISTRY_LABELS` in migrations_tenant.py). A global statement runs with no tenant, so it must not
# be able to match a node that holds a tenant's data. Adding a label here is as deliberate as adding
# an id to the allowlist, and the pinned test names both.
GLOBAL_STATEMENT_LABELS: Final[frozenset[str]] = frozenset(
    {"Tenant", "TenantNumber"} | NETWORK_REGISTRY_LABELS
)
# The platform's own records (TEN-075): the platform audit chain and the support-access tickets.
# Like the registry they carry no `tenantId`; only a platform statement may name them. A global
# statement may not (it is not on GLOBAL_STATEMENT_LABELS), so a global read cannot reach them.
PLATFORM_RECORD_LABELS: Final[frozenset[str]] = frozenset(
    {"PlatformAuditHead", "PlatformAuditEntry", "SupportAccessTicket"}
)

_IDENT = r"(?:[A-Za-z_]\w*|`[^`]*`)"
# A node pattern in its simple form, matched where a `(` stands: `(x:Label:Label {key: value})`,
# every part optional.
_NODE_PATTERN = re.compile(rf"\(\s*(?:{_IDENT})?\s*((?::\s*{_IDENT}\s*)*)(?:\{{[^{{}}]*\}})?\s*\)")
_LABEL = re.compile(rf":\s*({_IDENT})")
_NAME_BEFORE = re.compile(r"(?:[\w.]+|`[^`]*`)$")
_WRITES = re.compile(
    r"\b(?:CREATE|MERGE|SET|DELETE|DETACH|REMOVE|CALL|LOAD|FOREACH|DROP)\b", re.IGNORECASE
)
# What a global write may not contain: everything of `_WRITES` except CREATE and SET.
_WRITES_BEYOND_CREATE_AND_SET = re.compile(
    r"\b(?:MERGE|DELETE|DETACH|REMOVE|CALL|LOAD|FOREACH|DROP)\b", re.IGNORECASE
)
# What a platform write may not contain: it may CREATE, MERGE and SET, and nothing that removes,
# calls, loads or loops. `SET x:Label` and `SET x = ...` are not seen here: the digest pin is the
# guarantee, and the labels of a platform statement are checked as for a global one.
_PLATFORM_FORBIDDEN = re.compile(
    r"\b(?:DELETE|DETACH|REMOVE|CALL|LOAD|FOREACH|DROP)\b", re.IGNORECASE
)
_BARE_NODE = re.compile(r"\(\s*(\w+)\s*\)$")
_NODE_VARIABLE = re.compile(r"\(\s*(\w+)")
# A `(` that follows a name with no space is a function call only when the name is on the short
# list of functions (`properties(t)`); after a clause keyword (`MATCH(n:X)`, `WHERE(...)`) it is
# a node pattern or an expression, read exactly as it would be with a space; after any other name
# it is refused. So a keyword cannot hide a node pattern.
_FUNCTIONS = frozenset({"properties", "count", "coalesce", "tolower", "toupper", "size", "labels"})
# The functions a whole-graph count adds: `none(l IN labels(n) WHERE ...)` and `type(r)`.
_WHOLE_GRAPH_FUNCTIONS = _FUNCTIONS | {"none", "type"}
# What a whole-graph count may return: a label set or a relationship type, and a count.
_WHOLE_GRAPH_RETURN = re.compile(
    r"\bRETURN\s+(?:labels\(\s*\w+\s*\)|type\(\s*\w+\s*\))\s+AS\s+\w+\s*,"
    r"\s*count\(\s*\*\s*\)\s+AS\s+\w+\s*$"
)
_KEYWORDS = frozenset(
    [
        "match",
        "optional",
        "where",
        "with",
        "return",
        "union",
        "all",
        "unwind",
        "and",
        "or",
        "not",
        "xor",
        "in",
        "exists",
        "distinct",
        "as",
        "by",
        "order",
        "skip",
        "limit",
        "then",
        "else",
        "when",
        "case",
        "on",
        "is",
        "null",
        "starts",
        "ends",
        "contains",
        "asc",
        "desc",
    ]
)


def _blank(query_id: str, cypher: str) -> str:
    """The statement with each comment replaced by a space and the inside of each string literal
    removed, so a pattern in a comment or a string is not read as one. An unterminated string,
    quoted name or comment is refused."""
    out: list[str] = []
    i, n = 0, len(cypher)
    while i < n:
        c = cypher[i]
        if c in "'\"":
            i += 1
            while True:
                if i >= n:
                    raise ValueError(f"query {query_id}: a string in the statement is open")
                if cypher[i] == "\\":
                    i += 2
                elif cypher[i] == c:
                    i += 1
                    break
                else:
                    i += 1
            out.append(c + c)
        elif c == "`":
            end = cypher.find("`", i + 1)
            if end < 0:
                raise ValueError(f"query {query_id}: a quoted name in the statement is open")
            out.append(cypher[i : end + 1])
            i = end + 1
        elif cypher.startswith("//", i):
            end = cypher.find("\n", i)
            i = n if end < 0 else end
            out.append(" ")
        elif cypher.startswith("/*", i):
            end = cypher.find("*/", i + 2)
            if end < 0:
                raise ValueError(f"query {query_id}: a comment in the statement is open")
            i = end + 2
            out.append(" ")
        else:
            out.append(c)
            i += 1
    return "".join(out)


class TenantPredicateMissing(ValueError):
    """A tenant statement that has no `tenantId: $tenant` entry."""


class ScenarioMissing(ValueError):
    """A tenant statement that has no scenario."""


def _check_global_text(
    query_id: str,
    cypher: str,
    *,
    writes: bool = False,
    registry_writes: bool = False,
    platform: bool = False,
) -> None:
    """The structural checks of a global statement's text: DEFENCE IN DEPTH behind the digest pin,
    not a parser and not the guarantee (see GLOBAL_STATEMENTS). They refuse a write or procedure
    word, a `;`, a `(` after a name that is not an allowed function (so `MATCH(n:X)` is read as a
    node pattern, as `MATCH (n:X)` is), a node with no label, a label outside the registry, a
    parenthesis that is neither a node nor a function call, and a brace outside a node's property
    map. Comments and the inside of strings are removed first. The two whole-graph counts
    (GLOBAL_WHOLE_GRAPH_IDS) may name a node by variable alone and call `none` and `type`, and must
    return a label set or a relationship type and a count and nothing else.

    A global write (`registry_writes=True`, `GLOBAL_WRITE_IDS`, TEN-051) may use `CREATE` and `SET`
    and nothing else that writes, may name the network registry labels only, and may not assign a
    map (`+=`) or a label (`SET n:X`).

    A platform statement that writes (`writes=True`, TEN-028) is checked the same way, except that
    it may CREATE, MERGE and SET, and may name a node it has already declared with a registry label
    by its variable alone (a relationship merged between two nodes that an earlier MATCH bound)."""
    text = _blank(query_id, cypher)
    whole_graph = query_id in GLOBAL_WHOLE_GRAPH_IDS
    functions = _WHOLE_GRAPH_FUNCTIONS if whole_graph else _FUNCTIONS
    if whole_graph and (
        len(re.findall(r"\bRETURN\b", text, re.IGNORECASE)) != 1
        or _WHOLE_GRAPH_RETURN.search(text) is None
    ):
        raise ValueError(
            f"query {query_id}: a whole-graph count may return only a label set or a "
            "relationship type and a count"
        )
    if writes and _PLATFORM_FORBIDDEN.search(text) is not None:
        raise ValueError(f"query {query_id}: a platform statement may only create, merge and set")
    if registry_writes:
        forbidden = _WRITES_BEYOND_CREATE_AND_SET.search(text) is not None
    else:
        forbidden = not writes and _WRITES.search(text) is not None
    if forbidden:
        raise ValueError(f"query {query_id}: a global statement cannot write or call a procedure")
    if registry_writes and "+=" in text:
        raise ValueError(f"query {query_id}: a global write cannot assign a map")
    if registry_writes:
        allowed_labels = NETWORK_REGISTRY_LABELS
    elif platform:
        # A platform statement works on the tenant registry and the platform's own records
        # (TEN-075); a platform write is not on the network registry's labels.
        registry = (
            GLOBAL_STATEMENT_LABELS - NETWORK_REGISTRY_LABELS
            if writes
            else (GLOBAL_STATEMENT_LABELS)
        )
        allowed_labels = registry | PLATFORM_RECORD_LABELS
    else:
        allowed_labels = GLOBAL_STATEMENT_LABELS
    if ";" in text:
        raise ValueError(f"query {query_id}: a global statement is one statement")
    remaining = text
    declared: set[str] = set()
    for position in (m.start() for m in re.finditer(r"\(", text)):
        before = _NAME_BEFORE.search(text[:position])
        name = None if before is None or before.end() != position else before.group(0).lower()
        if name in functions:
            continue
        if name is not None and name not in _KEYWORDS:
            raise ValueError(
                f"query {query_id}: a global statement may put a parenthesis after the name "
                "of an allowed function or a clause keyword only"
            )
        node = _NODE_PATTERN.match(text, position)
        if node is None:
            raise ValueError(
                f"query {query_id}: a global statement may use parentheses only for node "
                "patterns and function calls"
            )
        labels = [label.strip("`") for label in _LABEL.findall(node.group(1))]
        if not labels and whole_graph and "{" not in node.group(0):
            # A scan names its nodes by variable only: `(n)`, `(a)`. No label, no property map.
            remaining = remaining.replace(node.group(0), " ", 1)
            continue
        bare = _BARE_NODE.match(node.group(0))
        if not labels and writes and bare is not None and bare.group(1) in declared:
            remaining = remaining.replace(node.group(0), " ", 1)
            continue
        if not labels:
            raise ValueError(f"query {query_id}: every node in a global statement needs a label")
        if not set(labels) <= allowed_labels:
            raise ValueError(f"query {query_id}: a global statement may name registry labels only")
        variable = _NODE_VARIABLE.match(node.group(0))
        if variable is not None:
            declared.add(variable.group(1))
        remaining = remaining.replace(node.group(0), " ", 1)
    if "{" in remaining or "}" in remaining:
        raise ValueError(
            f"query {query_id}: a global statement may use braces only in a node's properties"
        )
    if registry_writes and ":" in remaining:
        raise ValueError(f"query {query_id}: a global write cannot assign a label")


def _validate(
    query_id: str, mode: object, scope: object, scenario: object, scope_kinds: object
) -> None:
    if mode not in _MODES:
        raise ValueError(f"query {query_id}: mode must be 'read' or 'write', not {mode!r}")
    if scope not in _SCOPES:
        raise ValueError(
            f"query {query_id}: scope must be 'tenant', 'global' or 'platform', not {scope!r}"
        )
    if scenario is not None and not isinstance(scenario, Scenario):
        raise ValueError(f"query {query_id}: scenario must be a Scenario or None")
    if type(scope_kinds) is not frozenset or scope_kinds not in _KIND_SETS:
        raise ValueError(
            f"query {query_id}: scope_kinds must be TENANT_KINDS, NETWORK_KINDS or BOTH_KINDS"
        )
    if scope == "global" and scope_kinds != TENANT_KINDS:
        raise ValueError(f"query {query_id}: a global statement has no scope_kinds of its own")


@dataclass(frozen=True, slots=True)
class NamedQuery:
    id: str
    cypher: str
    mode: Literal["read", "write"]
    scope: Scope = "tenant"
    scenario: Scenario | None = None
    scope_kinds: frozenset[str] = TENANT_KINDS

    def __post_init__(self) -> None:
        _validate(self.id, self.mode, self.scope, self.scenario, self.scope_kinds)


@dataclass(frozen=True, slots=True)
class QueryTemplate:
    """One fixed statement with one `{insert}` place for a label chain or a relationship type."""

    id: str
    cypher: str
    mode: Literal["read", "write"]
    scope: Scope = "tenant"
    scenario: Scenario | None = None
    scope_kinds: frozenset[str] = TENANT_KINDS

    def __post_init__(self) -> None:
        _validate(self.id, self.mode, self.scope, self.scenario, self.scope_kinds)


def statement_labels(cypher: str) -> list[str]:
    """The node labels a statement names, each once, in the order written. Comments and the
    inside of strings are removed first, then relationship patterns (`[:TYPE]`) and property
    maps (`{...}`), so what is left holds a `:Name` only where a label is written: in a node
    pattern, a `WHERE n:X` or a `SET n:X`. Cheap, and not a parser (DEC-142)."""
    text = _blank("(statement)", cypher)
    for pattern in (_BRACKETS, _BRACES):
        previous = None
        while previous != text:
            previous = text
            text = pattern.sub(" ", text)
    labels: list[str] = []
    for match in _LABEL_NAME.finditer(text):
        label = match.group(1).strip("`")
        if label not in labels:
            labels.append(label)
    return labels


def _check_kinds(query_id: str, cypher: str, scope_kinds: frozenset[str]) -> None:
    """The label partition and the `$sourceTenant` rule for a tenant-scope-stamped statement."""
    text = _blank(query_id, cypher)
    if scope_kinds != NETWORK_KINDS and _SOURCE_TENANT_PARAMETER.search(text) is not None:
        raise ValueError(
            f"query {query_id}: only a network-only statement may mention $sourceTenant"
        )
    labels = set(statement_labels(cypher))
    if scope_kinds == TENANT_KINDS:
        bad = labels & (NETWORK_ONLY_LABELS | REGISTRY_NODE_LABELS)
        if bad:
            raise ValueError(
                f"query {query_id}: a tenant statement cannot name a network label or a registry "
                f"label: {', '.join(sorted(bad))}"
            )
    elif scope_kinds == NETWORK_KINDS:
        bad = labels - (NETWORK_ONLY_LABELS | SCOPE_GENERIC_LABELS)
        if bad:
            raise ValueError(
                f"query {query_id}: a network statement may name network and scope-generic "
                f"labels only: {', '.join(sorted(bad))}"
            )
    else:
        bad = labels - SCOPE_GENERIC_LABELS
        if bad:
            raise ValueError(
                f"query {query_id}: a statement for both kinds of scope may name scope-generic "
                f"labels only: {', '.join(sorted(bad))}"
            )


def _mentions_tenant(cypher: str) -> bool:
    return _TENANT_PARAMETER.search(cypher) is not None


class QueryRegistry:
    def __init__(self) -> None:
        self._queries: dict[str, NamedQuery] = {}
        self._templates: dict[str, QueryTemplate] = {}

    def register(self, query: NamedQuery) -> None:
        if _INSTANCE_SEPARATOR in query.id:
            raise ValueError(f"query {query.id}: a statement id cannot contain a colon")
        self._refuse_taken(query.id)
        self._check(query.id, query.cypher, query.mode, query.scope, query.scenario)
        self._check_kinds(query.id, query.cypher, query.scope, query.scope_kinds)
        self._queries[query.id] = query

    def register_template(self, template: QueryTemplate) -> None:
        if _INSTANCE_SEPARATOR in template.id:
            raise ValueError(f"template {template.id}: a statement id cannot contain a colon")
        if template.scope != "tenant":
            raise ValueError(
                f"template {template.id}: a template cannot be a global or platform statement"
            )
        self._refuse_taken(template.id)
        self._check(template.id, template.cypher, template.mode, template.scope, template.scenario)
        self._check_kinds(template.id, template.cypher, template.scope, template.scope_kinds)
        self._templates[template.id] = template

    def instance(self, template_id: str, insert: str = "") -> NamedQuery:
        """The statement of a template with its insert, registered the first time it is asked for.
        The insert must be a chain of label names (`:Resource:Organization`), or empty for a
        template with no `{insert}` place."""
        try:
            template = self._templates[template_id]
        except KeyError:
            raise KeyError(f"unknown query template: {template_id}") from None
        takes_insert = PLACEHOLDER in template.cypher
        if takes_insert and _INSERT.fullmatch(insert) is None:
            raise ValueError(f"template {template_id}: the insert must be a chain of label names")
        if not takes_insert and insert:
            raise ValueError(f"template {template_id}: the template takes no insert")
        query_id = f"{template_id}{insert}"
        existing = self._queries.get(query_id)
        if existing is not None:
            return existing
        query = NamedQuery(
            id=query_id,
            cypher=template.cypher.replace(PLACEHOLDER, insert),
            mode=template.mode,
            scope=template.scope,
            scenario=template.scenario,
            scope_kinds=template.scope_kinds,
        )
        # The template was judged with its insert empty: the labels the insert adds are judged now.
        _check_kinds(query_id, query.cypher, template.scope_kinds)
        self._queries[query_id] = query
        return query

    def template(self, template_id: str) -> QueryTemplate:
        """A registered template, for the tools that list every statement (the generated test)."""
        try:
            return self._templates[template_id]
        except KeyError:
            raise KeyError(f"unknown query template: {template_id}") from None

    def get(self, query_id: str) -> NamedQuery:
        try:
            return self._queries[query_id]
        except KeyError:
            raise KeyError(f"unknown query id: {query_id}") from None

    def ids(self) -> list[str]:
        return sorted(self._queries)

    def template_ids(self) -> list[str]:
        return sorted(self._templates)

    def is_registered(self, query: object) -> bool:
        """True only for the very statement that was registered: the same id and the same text,
        mode, scope and scenario. An id alone is not enough."""
        return isinstance(query, NamedQuery) and self._queries.get(query.id) == query

    def _refuse_taken(self, query_id: str) -> None:
        if query_id in self._queries or query_id in self._templates:
            raise ValueError(f"duplicate query id: {query_id}")

    def _check_kinds(
        self, query_id: str, cypher: str, scope: str, scope_kinds: frozenset[str]
    ) -> None:
        # Only a tenant-scope-stamped statement is partitioned by label: a global or platform
        # statement is on the registry and has its own label rules (`_check_global_text`).
        if scope == "tenant":
            _check_kinds(query_id, cypher, scope_kinds)

    def _check(
        self, query_id: str, cypher: str, mode: str, scope: str, scenario: Scenario | None
    ) -> None:
        if scope != "global" and query_id in GLOBAL_QUERY_IDS:
            raise ValueError(
                f"query {query_id}: this id is on the global allowlist, so it must be registered "
                "with scope='global'"
            )
        if scope != "platform" and query_id in PLATFORM_QUERY_IDS:
            raise ValueError(
                f"query {query_id}: this id is on the platform allowlist, so it must be "
                "registered with scope='platform'"
            )
        if scope == "platform":
            if query_id not in PLATFORM_QUERY_IDS:
                raise ValueError(f"query {query_id}: not on the platform allowlist")
            if _mentions_tenant(cypher):
                raise ValueError(f"query {query_id}: a platform statement cannot mention $tenant")
            _check_global_text(query_id, cypher, writes=mode == "write", platform=True)
            pinned = PLATFORM_STATEMENTS.get(query_id)
            if pinned is None:
                raise ValueError(f"query {query_id}: this platform statement has no pinned digest")
            if statement_digest(cypher) != pinned:
                raise ValueError(
                    f"query {query_id}: the text is not the pinned text of this platform statement"
                )
            return
        if scope == "global":
            if query_id not in GLOBAL_QUERY_IDS:
                raise ValueError(f"query {query_id}: not on the global allowlist")
            if _mentions_tenant(cypher):
                raise ValueError(f"query {query_id}: a global statement cannot mention $tenant")
            if (mode == "write") != (query_id in GLOBAL_WRITE_IDS):
                raise ValueError(
                    f"query {query_id}: a global statement must be read-only, except the "
                    "registry writes of GLOBAL_WRITE_IDS, which must be writes"
                )
            _check_global_text(query_id, cypher, registry_writes=mode == "write")
            pinned = GLOBAL_STATEMENTS.get(query_id)
            if pinned is None:
                raise ValueError(f"query {query_id}: this global statement has no pinned digest")
            if statement_digest(cypher) != pinned:
                raise ValueError(
                    f"query {query_id}: the text is not the pinned text of this global statement"
                )
            return
        if _TENANT_ENTRY.search(_blank(query_id, cypher)) is None:
            raise TenantPredicateMissing(
                f"query {query_id}: no tenantId: $tenant entry in the statement"
            )
        if scenario is None:
            raise ScenarioMissing(f"query {query_id}: no scenario")


REGISTRY = QueryRegistry()
