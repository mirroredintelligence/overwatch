"""The export classes and the manifest (TEN-074, audit F section 2.4).

Every label a registered statement names has one place: a data class, the protected set (held back
unless the tenant asks) or the excluded set (never exported). A new label cannot be added without a
decision, because this file fails until `tenant_export.py` names it.
"""

import importlib
import json
import pkgutil
from datetime import UTC, datetime

import pytest

from diucs.domain.rules.tenant_export import (
    CLASS_OF_LABEL,
    EXCLUDED_LABELS,
    PROTECTED_LABELS,
    ExportClass,
    FileEntry,
    Handling,
    UnclassifiedData,
    classify,
    file_name,
    jsonl,
    manifest_bytes,
    plain,
    sha256_hex,
)


def _labels_of_every_tenant_statement() -> set[str]:
    import diucs.adapters.outbound.audit_neo4j as audit_package
    import diucs.adapters.outbound.graph_store as graph_store_package
    from diucs.adapters.outbound.graph_store.queries import REGISTRY, statement_labels

    for package in (graph_store_package, audit_package):
        for module in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
            importlib.import_module(module.name)
    found: set[str] = set()
    for query_id in REGISTRY.ids():
        query = REGISTRY.get(query_id)
        if query.scope == "tenant" and "tenant" in query.scope_kinds:
            found |= set(statement_labels(query.cypher))
    return found


def test_every_label_a_tenant_statement_names_has_a_place() -> None:
    placed = set(CLASS_OF_LABEL) | PROTECTED_LABELS | EXCLUDED_LABELS
    missing = _labels_of_every_tenant_statement() - placed
    assert missing == set(), f"decide how a tenant's export treats: {sorted(missing)}"


def test_the_three_sets_do_not_overlap() -> None:
    assert not set(CLASS_OF_LABEL) & PROTECTED_LABELS
    assert not set(CLASS_OF_LABEL) & EXCLUDED_LABELS
    assert not PROTECTED_LABELS & EXCLUDED_LABELS


@pytest.mark.parametrize(
    ("labels", "handling", "export_class"),
    [
        (("HealthcareService", "Resource"), Handling.EXPORT, ExportClass.DIRECTORY_AND_CRITERIA),
        (("Observation", "Resource"), Handling.EXPORT, ExportClass.CAPACITY_REPORTS),
        (("AuditEvent", "ChainLink"), Handling.EXPORT, ExportClass.AUDIT_CHAIN),
        (("ProtectedContact",), Handling.PROTECTED, ExportClass.PROTECTED),
        (("Credential",), Handling.EXCLUDED, None),
        # a node that carries a secret label is never exported, whatever else it is
        (("Resource", "Credential"), Handling.EXCLUDED, None),
        (("Resource", "ProtectedText"), Handling.PROTECTED, ExportClass.PROTECTED),
    ],
)
def test_a_label_set_is_classified(
    labels: tuple[str, ...], handling: Handling, export_class: ExportClass | None
) -> None:
    result = classify(labels)
    assert (result.handling, result.export_class) == (handling, export_class)


def test_a_label_no_class_names_is_refused_with_a_fixed_message() -> None:
    with pytest.raises(UnclassifiedData) as caught:
        classify(("SomethingNew",))
    assert str(caught.value) == "a kind of data has no export class"


def test_a_file_is_named_by_class_and_the_sorted_labels() -> None:
    assert (
        file_name(ExportClass.CAPACITY_REPORTS, ("Resource", "Observation"))
        == "capacity-reports/Observation+Resource.jsonl"
    )


def test_the_same_rows_are_always_the_same_bytes_and_one_line_each() -> None:
    rows = [{"b": 1, "a": "x"}, {"a": datetime(2026, 10, 30, 9, 0, tzinfo=UTC)}]
    first = jsonl(rows)
    assert first == jsonl([{"a": "x", "b": 1}, {"a": datetime(2026, 10, 30, 9, 0, tzinfo=UTC)}])
    assert first.decode().splitlines() == ['{"a":"x","b":1}', '{"a":"2026-10-30T09:00:00+00:00"}']
    assert jsonl([]) == b""


def test_plain_turns_a_set_into_a_sorted_list() -> None:
    assert plain({"b", "a"}) == ["a", "b"]
    assert plain({"k": {2, 1}}) == {"k": [1, 2]}


def test_the_manifest_lists_every_file_with_its_hash_and_is_canonical() -> None:
    entries = [
        FileEntry("b/x.jsonl", "people", 2, sha256_hex(b"1")),
        FileEntry("a/y.jsonl", "audit-chain", 1, sha256_hex(b"2")),
    ]
    args = dict(
        tenant_id="org-a",
        package_id="export-1",
        generated_at=datetime(2026, 10, 30, 9, 0, tzinfo=UTC),
        held_back={"ProtectedContact": 3},
        excluded={"Credential": 4},
        audit_last_hash="ab" * 32,
        audit_last_seq=9,
        protected_included=False,
    )
    one = manifest_bytes(files=entries, **args)  # type: ignore[arg-type]
    two = manifest_bytes(files=list(reversed(entries)), **args)  # type: ignore[arg-type]
    assert one == two  # the order the files were written in does not matter
    body = json.loads(one)
    assert [f["name"] for f in body["files"]] == ["a/y.jsonl", "b/x.jsonl"]
    assert body["held_back"] == {"ProtectedContact": 3} and body["excluded"] == {"Credential": 4}
    assert body["audit_chain"] == {"last_hash": "ab" * 32, "last_seq": 9}
    assert body["protected_included"] is False
