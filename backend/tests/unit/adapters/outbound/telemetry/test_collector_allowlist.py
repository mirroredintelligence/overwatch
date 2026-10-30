"""The OpenTelemetry Collector's allow-list matches the back end's (O04).

The collector is the second scrub layer: an attribute key that is not on its list is removed before
anything is stored. These tests keep three things equal: the back end's own allow-list
(attributes.py, O01), the list in infra/otel-allowlist.txt, and the `keep_keys` statements in
infra/otel-collector.yaml. They also pin the privacy rule: no query text and no parameters.
"""

import re
from pathlib import Path
from typing import Final

import yaml

from diucs.adapters.outbound.telemetry.attributes import (
    ALLOWED_KEYS,
    ALLOWED_PREFIXES,
    DENIED_FRAGMENTS,
    is_allowed_key,
)

REPO_ROOT: Final = Path(__file__).resolve().parents[6]
ALLOWLIST_FILE: Final = REPO_ROOT / "infra" / "otel-allowlist.txt"
COLLECTOR_CONFIG: Final = REPO_ROOT / "infra" / "otel-collector.yaml"
COMPOSE_FILE: Final = REPO_ROOT / "infra" / "docker-compose.yml"
TEST_OVERLAY: Final = REPO_ROOT / "infra" / "otel-collector.test.yaml"

# The browser attributes from docs/spec/observability.md (O04 "Allowed keys"), plus trace_id,
# which the
# browser sends on every ui.* event so the event joins the back-end spans of the same interaction.
BROWSER_KEYS_FROM_SPEC: Final = frozenset(
    {
        "from.route",
        "load.type",
        "ttfb_ms",
        "lcp_ms",
        "dwell_ms",
        "result",
        "valid",
        "length_bucket",
        "state",
        "form.id",
        "error_count",
        "time_to_submit_ms",
        "error.code",
        "kind",
        "count",
        "window_ms",
        "name",
        "value",
        "rating",
        "duration_ms",
        "gap_ms",
        "standalone",
        "session_code_shared",
    }
)
BROWSER_KEYS_ADDED_HERE: Final = frozenset({"trace_id"})
# The spec's ui.web_vital keys are free-text words (DENIED_FRAGMENTS). They are not kept anywhere:
# the back end refuses them, the browser allow-list and the O05 schema do not send them, and the
# collector cannot limit a key to one event, so the O04 integration removed them from the list.
REFUSED_FREE_TEXT_KEYS: Final = frozenset({"name", "value"})
RESOURCE_KEYS: Final = frozenset({"service.name", "service.version", "deployment.environment"})
FRONTEND_EVENTS_FILE: Final = REPO_ROOT / "frontend" / "lib" / "telemetry" / "events.ts"

# A key the back end must never let out, and a key the collector must never list, even by mistake.
PRIVACY_KEYS: Final = (
    "db.statement",
    "db.query.text",
    "db.query.parameters",
    "patient.postcode",
    "patient.name",
    "nhs.number",
    "support.code",
)


def _sections() -> dict[str, set[str]]:
    sections: dict[str, set[str]] = {}
    current: str | None = None
    for raw in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections[current] = set()
            continue
        assert current is not None, f"a key before any section: {line}"
        sections[current].add(line)
    return sections


def _config() -> dict:
    loaded = yaml.safe_load(COLLECTOR_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _keep_key_lists(config: dict) -> list[tuple[str, str, set[str]]]:
    """Every keep_keys statement in the transform processor: (context, target, keys)."""
    found: list[tuple[str, str, set[str]]] = []
    pattern = re.compile(r"^keep_keys\((attributes|resource\.attributes),\s*\[(.*)\]\)$")
    for name, processor in config["processors"].items():
        if not name.startswith("transform"):
            continue
        for section in ("trace_statements", "log_statements", "metric_statements"):
            for block in processor.get(section, []):
                for statement in block["statements"]:
                    match = pattern.match(statement.strip())
                    if match is None:
                        continue
                    keys = {
                        key.strip().strip('"') for key in match.group(2).split(",") if key.strip()
                    }
                    found.append((block["context"], match.group(1), keys))
    return found


def test_the_backend_section_of_the_file_equals_the_o01_allow_list() -> None:
    assert _sections()["backend"] == set(ALLOWED_KEYS)


# Keys on the list that contain a denied word, each reviewed by hand. O01 lets an explicit key
# pass by
# name, so a denied word in one of them is a decision, and a new one must be reviewed here.
REVIEWED_BACKEND_DENIED_WORD_KEYS: Final = frozenset(
    {
        "messaging.destination.name",  # a Service Bus queue or topic name
        "db.system.name",  # the semantic-convention database name, such as neo4j
    }
)
REVIEWED_BROWSER_DENIED_WORD_KEYS: Final = frozenset()  # none: name and value are refused (above)


def _with_denied_word(keys: set[str]) -> set[str]:
    return {key for key in keys if any(fragment in key for fragment in DENIED_FRAGMENTS)}


def test_every_backend_key_passes_the_o01_rule() -> None:
    for key in _sections()["backend"]:
        assert is_allowed_key(key), key


def test_only_the_reviewed_keys_contain_a_denied_word() -> None:
    sections = _sections()
    assert _with_denied_word(sections["backend"]) == REVIEWED_BACKEND_DENIED_WORD_KEYS
    assert _with_denied_word(sections["browser"]) == REVIEWED_BROWSER_DENIED_WORD_KEYS


def test_the_browser_section_is_the_spec_list_less_the_refused_keys_plus_trace_id() -> None:
    expected = (BROWSER_KEYS_FROM_SPEC - REFUSED_FREE_TEXT_KEYS) | BROWSER_KEYS_ADDED_HERE
    assert _sections()["browser"] == set(expected)


def test_free_text_keys_are_on_no_list_and_no_keep_keys_statement() -> None:
    sections = _sections()
    for section in sections.values():
        assert section.isdisjoint(REFUSED_FREE_TEXT_KEYS)
    for _context, _target, keys in _keep_key_lists(_config()):
        assert keys.isdisjoint(REFUSED_FREE_TEXT_KEYS)
    for key in REFUSED_FREE_TEXT_KEYS:
        assert not is_allowed_key(key), key


def test_the_browser_allow_list_does_not_send_free_text_keys() -> None:
    # The browser sends only the keys of ALLOWED_ATTRIBUTES (frontend/lib/telemetry/events.ts); none
    # of the refused keys may be among them, or the collector and the browser would disagree.
    source = FRONTEND_EVENTS_FILE.read_text(encoding="utf-8")
    block = re.search(r"ALLOWED_ATTRIBUTES[^=]*=\s*\[(.*?)\];", source, re.DOTALL)
    assert block is not None, "ALLOWED_ATTRIBUTES not found"
    sent = set(re.findall(r"'([^']+)'", block.group(1)))
    assert sent, "ALLOWED_ATTRIBUTES is empty"
    assert sent.isdisjoint(REFUSED_FREE_TEXT_KEYS), sent & REFUSED_FREE_TEXT_KEYS


def test_the_resource_section_is_the_three_resource_keys() -> None:
    assert _sections()["resource"] == set(RESOURCE_KEYS)


def test_the_collector_keep_keys_statements_equal_the_file() -> None:
    sections = _sections()
    span_and_log_keys = sections["backend"] | sections["browser"]
    statements = _keep_key_lists(_config())

    assert statements, "the transform processor has no keep_keys statements"
    for context, _target, keys in statements:
        # The resource context keeps the resource keys; span, span event and log contexts keep the
        # rest.
        if context == "resource":
            assert keys == sections["resource"], context
        else:
            assert keys == span_and_log_keys, context


def test_tenant_id_is_on_the_collector_list() -> None:
    assert "tenant.id" in _sections()["backend"]


def test_privacy_keys_are_refused_by_the_back_end_and_absent_from_the_collector() -> None:
    sections = _sections()
    listed = sections["backend"] | sections["browser"] | sections["resource"]
    for key in PRIVACY_KEYS:
        assert key not in listed, key
        assert not is_allowed_key(key), key
    for statement in _keep_key_lists(_config()):
        for key in PRIVACY_KEYS:
            assert key not in statement[2], key


def test_no_prefix_family_is_listed_as_a_wildcard() -> None:
    # The collector matches exact keys only: a prefix in the file would be a pattern it does not
    # read.
    listed = set().union(*_sections().values())
    for key in listed:
        assert not key.endswith("*"), key
        assert not key.endswith("."), key
    assert ALLOWED_PREFIXES, "the back end's prefix families are expressed as exact keys"


def test_the_pipelines_run_the_processors_in_order_and_sample_only_traces() -> None:
    service = _config()["service"]["pipelines"]
    assert service["traces"]["processors"] == [
        "memory_limiter",
        "transform/allowlist",
        "tail_sampling",
        "batch",
    ]
    assert service["logs"]["processors"] == ["memory_limiter", "transform/allowlist", "batch"]
    assert "tail_sampling" not in service["logs"]["processors"]


def test_tail_sampling_keeps_errors_slow_traces_and_ten_percent_of_the_rest() -> None:
    policies = _config()["processors"]["tail_sampling"]["policies"]
    by_type = {policy["type"]: policy for policy in policies}
    assert by_type["status_code"]["status_code"]["status_codes"] == ["ERROR"]
    assert by_type["latency"]["latency"]["threshold_ms"] == 1000
    assert by_type["probabilistic"]["probabilistic"]["sampling_percentage"] == 10


def test_the_receivers_are_otlp_grpc_and_http() -> None:
    protocols = _config()["receivers"]["otlp"]["protocols"]
    assert protocols["grpc"]["endpoint"].endswith(":4317")
    assert protocols["http"]["endpoint"].endswith(":4318")


def test_the_azure_connection_string_comes_from_the_environment_only() -> None:
    exporter = _config()["exporters"]["azuremonitor"]
    assert exporter["connection_string"] == "${env:APPLICATIONINSIGHTS_CONNECTION_STRING}"


def test_zipkin_is_defined_but_not_in_any_pipeline() -> None:
    config = _config()
    assert "zipkin" in config["exporters"]
    for pipeline in config["service"]["pipelines"].values():
        assert "zipkin" not in pipeline["exporters"]


def test_the_file_exporter_appears_only_in_the_test_overlay() -> None:
    assert not any(name.startswith("file") for name in _config()["exporters"])
    overlay = yaml.safe_load(TEST_OVERLAY.read_text(encoding="utf-8"))
    assert overlay["exporters"]["file/test"]["path"] == "/tmp/otel/out.json"
    for pipeline in overlay["service"]["pipelines"].values():
        assert pipeline["exporters"] == ["file/test"]


def test_the_collector_image_is_pinned_to_an_exact_contrib_version() -> None:
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    image = compose["services"]["otel-collector"]["image"]
    assert re.fullmatch(r"otel/opentelemetry-collector-contrib:\d+\.\d+\.\d+", image), image


def test_the_compose_collector_runs_only_under_the_test_profile() -> None:
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    service = compose["services"]["otel-collector"]
    assert service["profiles"] == ["test"]
    assert any("otel-collector.test.yaml" in volume for volume in service["volumes"])
