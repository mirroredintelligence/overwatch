"""Service Bus helpers for the emulator suites (I02, TEN-020). Nothing here reaches a cloud
namespace.

The emulator and its entities are shared by every run on a machine, so a run sends only messages
of its own tenants, with ids no other run can produce (lessons L6 and L101: the duplicate
detection window and messages left by an earlier run).
"""

import re
from uuid import uuid4

from azure.servicebus.aio import ServiceBusClient

from diucs.application.tenancy import is_valid_tenant_id
from diucs.bootstrap.settings import Settings

RUN_ID: str = uuid4().hex[:8]
_LABEL = re.compile(r"[a-z0-9-]{1,20}")

# The emulator's documented local development connection string (infra/README.md). It is a
# public key for the local emulator only; a real namespace uses DIUCS_SERVICEBUS_CONNECTION.
EMULATOR_CONNECTION = (
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true"
)


def connection_string() -> str:
    secret = Settings().servicebus_connection
    return secret.get_secret_value() if secret is not None else EMULATOR_CONNECTION


def client(**options: int) -> ServiceBusClient:
    return ServiceBusClient.from_connection_string(connection_string(), **options)


def run_tenant(label: str) -> str:
    """A tenant id for this run and a label: `sb<run id>-<label>`, a valid tenant id."""
    if _LABEL.fullmatch(label) is None:
        raise ValueError("a run tenant label is 1 to 20 characters of a-z, 0-9 and hyphen")
    tenant = f"sb{RUN_ID}-{label}"
    if not is_valid_tenant_id(tenant):
        raise ValueError("a run tenant id is not a valid tenant id")
    return tenant


def unique_id(prefix: str) -> str:
    """A message id no other run, and no earlier send of this run, has used."""
    return f"{prefix}-{uuid4()}"
