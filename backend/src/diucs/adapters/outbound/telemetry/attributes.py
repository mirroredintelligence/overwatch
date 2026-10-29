"""Names of every span, attribute and metric label the back end emits, and the allow-list (O01).

Stub for the red commit: the allow-list is not enforced yet.
"""

from typing import Final

SERVICE_NAME: Final = "diucs-backend"
INSTRUMENTATION_NAME: Final = "diucs"
TENANT_ID: Final = "tenant.id"
SESSION_ID: Final = "session.id"
SERVICE_ID: Final = "service.id"
USECASE_OUTCOME: Final = "usecase.outcome"
USECASE_IDEMPOTENT_REPLAY: Final = "usecase.idempotent_replay"
DB_SYSTEM: Final = "db.system"
DB_SYSTEM_NAME: Final = "db.system.name"
DB_QUERY_ID: Final = "db.query.id"
DB_ACCESS_MODE: Final = "db.access_mode"
DB_ROW_COUNT: Final = "db.row_count"
NEO4J_SYSTEM: Final = "neo4j"

ALLOWED_KEYS: frozenset[str] = frozenset()


def is_allowed_key(key: str) -> bool:
    return True
