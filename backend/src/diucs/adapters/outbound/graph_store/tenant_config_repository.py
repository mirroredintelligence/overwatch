"""A tenant's configuration records on Neo4j (TEN-026). Stub for the red commit."""

from typing import Any, Final

from diucs.domain.model.tenant import TenantConfig
from diucs.domain.model.tenant_policy import SettingValue

CONFIG_QUERY_IDS: Final[tuple[str, ...]] = ()


def setting_row(key: str, value: SettingValue) -> dict[str, Any]:
    raise NotImplementedError


def values_from_rows(rows: list[dict[str, Any]]) -> dict[str, SettingValue]:
    raise NotImplementedError


def version_props(config: TenantConfig) -> dict[str, Any]:
    raise NotImplementedError


def version_from_props(props: dict[str, Any], values: dict[str, SettingValue]) -> TenantConfig:
    raise NotImplementedError


def contact_params(contact: object) -> dict[str, Any]:
    raise NotImplementedError


def contact_from_props(props: dict[str, Any]) -> object:
    raise NotImplementedError


def channel_params(channel: object) -> dict[str, Any]:
    raise NotImplementedError


def channel_from_props(props: dict[str, Any]) -> object:
    raise NotImplementedError


def retention_params(rule: object) -> dict[str, Any]:
    raise NotImplementedError


def retention_from_props(props: dict[str, Any]) -> object:
    raise NotImplementedError


def binding_params(binding: object) -> dict[str, Any]:
    raise NotImplementedError


def binding_from_props(props: dict[str, Any]) -> object:
    raise NotImplementedError


def mapping_params(mapping: object) -> dict[str, Any]:
    raise NotImplementedError


def mapping_from_props(props: dict[str, Any]) -> object:
    raise NotImplementedError
