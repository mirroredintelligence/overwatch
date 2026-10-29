"""Every span name, attribute key and resource name the back end emits, and the allow-list (O01).

Names live here and nowhere else. Anything not on the allow-list is removed by
AllowListSpanProcessor before export. A key is allowed when it is in ALLOWED_KEYS, begins with
an ALLOWED_PREFIXES entry, or ends with `.id`, and it contains none of the DENIED_FRAGMENTS, so a
token, phone number or name cannot pass as an id. Values are scanned for phone numbers, link tokens
and postcodes too (redaction.py).

Semantic-convention names checked against opentelemetry-semantic-conventions 0.66b2: `http.route`,
`http.request.method`, `http.response.status_code`, `url.scheme`, `server.address`, `error.type`
and `db.system.name` are the current stable names. `db.system` is the name the query matrix and the
O01 acceptance tests use; the SDK marks it deprecated, so both are emitted for Neo4j spans.
"""

from typing import Final

SERVICE_NAME: Final = "diucs-backend"
INSTRUMENTATION_NAME: Final = "diucs"
NEO4J_SYSTEM: Final = "neo4j"

SPAN_NEO4J_QUERY: Final = "neo4j.query {query_id}"
SPAN_SERVICEBUS_PROCESS: Final = "servicebus.process {topic}"
SERVICEBUS_SYSTEM: Final = "servicebus"

TENANT_ID: Final = "tenant.id"
SESSION_ID: Final = "session.id"
SERVICE_ID: Final = "service.id"
USER_ROLE: Final = "user.role"
PAGE_ROUTE: Final = "page.route"
COMPONENT_ID: Final = "component.id"
ELEMENT_ID: Final = "element.id"
RELEASE: Final = "release"
DEVICE_TYPE: Final = "device.type"
APP_MODE: Final = "app.mode"
NET_EFFECTIVE_TYPE: Final = "net.effective_type"
USECASE_OUTCOME: Final = "usecase.outcome"
USECASE_IDEMPOTENT_REPLAY: Final = "usecase.idempotent_replay"
DB_SYSTEM: Final = "db.system"
DB_SYSTEM_NAME: Final = "db.system.name"
DB_QUERY_ID: Final = "db.query.id"
DB_ACCESS_MODE: Final = "db.access_mode"
DB_ROW_COUNT: Final = "db.row_count"
HTTP_REQUEST_METHOD: Final = "http.request.method"
HTTP_ROUTE: Final = "http.route"
HTTP_RESPONSE_STATUS_CODE: Final = "http.response.status_code"
URL_SCHEME: Final = "url.scheme"
SERVER_ADDRESS: Final = "server.address"
ERROR_TYPE: Final = "error.type"
MESSAGING_SYSTEM: Final = "messaging.system"
MESSAGING_DESTINATION_NAME: Final = "messaging.destination.name"
MESSAGING_MESSAGE_ID: Final = "messaging.message.id"

ALLOWED_KEYS: Final[frozenset[str]] = frozenset(
    {
        SESSION_ID,
        USER_ROLE,
        SERVICE_ID,
        PAGE_ROUTE,
        COMPONENT_ID,
        ELEMENT_ID,
        RELEASE,
        DEVICE_TYPE,
        APP_MODE,
        NET_EFFECTIVE_TYPE,
        TENANT_ID,
        HTTP_REQUEST_METHOD,
        HTTP_ROUTE,
        HTTP_RESPONSE_STATUS_CODE,
        URL_SCHEME,
        SERVER_ADDRESS,
        ERROR_TYPE,
        USECASE_OUTCOME,
        USECASE_IDEMPOTENT_REPLAY,
        DB_SYSTEM,
        DB_SYSTEM_NAME,
        DB_QUERY_ID,
        DB_ACCESS_MODE,
        DB_ROW_COUNT,
        MESSAGING_SYSTEM,
        MESSAGING_DESTINATION_NAME,
        MESSAGING_MESSAGE_ID,
    }
)
ALLOWED_PREFIXES: Final[tuple[str, ...]] = ("usecase.", "db.", "messaging.")
DOMAIN_ID_SUFFIX: Final = ".id"

# A key on ALLOWED_KEYS passes by name. Any other key that contains one of these words is refused,
# even when it ends in `.id` or matches a prefix. The words are the kinds of value that must never
# reach telemetry (docs/spec/observability.md, "Privacy and governance").
DENIED_FRAGMENTS: Final[tuple[str, ...]] = (
    "token",
    "secret",
    "password",
    "phone",
    "msisdn",
    "nhs",
    "postcode",
    "email",
    "name",
    "body",
    "payload",
    "content",
    "patient",
    "value",
    "text",
    "pairing",
    "support.code",
    # `db.` is an allowed prefix, so the keys that carry the query itself are refused by word.
    "statement",
    "cypher",
    "sql",
    "parameter",
)


def is_allowed_key(key: str) -> bool:
    if key in ALLOWED_KEYS:
        return True
    if any(fragment in key for fragment in DENIED_FRAGMENTS):
        return False
    if key.startswith(ALLOWED_PREFIXES):
        return True
    return key.endswith(DOMAIN_ID_SUFFIX)
