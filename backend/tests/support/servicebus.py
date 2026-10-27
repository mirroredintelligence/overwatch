"""Service Bus helpers for the emulator suites (I02). Nothing here reaches a cloud namespace."""

from azure.servicebus.aio import ServiceBusClient

from diucs.bootstrap.settings import Settings

# The emulator's documented local development connection string (infra/README.md). It is a
# public key for the local emulator only; a real namespace uses DIUCS_SERVICEBUS_CONNECTION.
EMULATOR_CONNECTION = (
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true"
)


def connection_string() -> str:
    secret = Settings().servicebus_connection
    return secret.get_secret_value() if secret is not None else EMULATOR_CONNECTION


def client() -> ServiceBusClient:
    return ServiceBusClient.from_connection_string(connection_string())
