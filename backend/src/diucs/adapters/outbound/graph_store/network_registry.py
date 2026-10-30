"""The network registry on Neo4j (TEN-051). Stub for the red commit."""

from typing import Any, Final

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection

RECORD_MESSAGE: Final = ""


def network_properties(network: Any, settings: Any) -> dict[str, Any]:
    raise NotImplementedError


def network_from_properties(props: Any) -> Any:
    raise NotImplementedError


def membership_properties(membership: Any) -> dict[str, Any]:
    raise NotImplementedError


def membership_from_properties(props: Any) -> Any:
    raise NotImplementedError


def grant_properties(grant: Any) -> dict[str, Any]:
    raise NotImplementedError


def grant_from_properties(props: Any) -> Any:
    raise NotImplementedError


def listing_properties(listing: Any) -> dict[str, Any]:
    raise NotImplementedError


def listing_from_properties(props: Any) -> Any:
    raise NotImplementedError


class Neo4jNetworkRegistry:
    def __init__(self, connection: Neo4jConnection) -> None:
        self._connection = connection

    def __getattr__(self, name: str) -> Any:
        raise NotImplementedError
