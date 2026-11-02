"""TEMPORARY DEMO (DEC-1320): the start-up side of OVERWATCH_DEMO_INBOUND_TENANT.

An invalid value stops start-up with a plain message (never silently ignored); a good value is a
loud start-up warning; the inbound directory has the demo route only when the setting is set; the
Bicep parameter defaults to off with no value in the repo.
"""

from pathlib import Path
from typing import Any

import pytest

from overwatch.application.tenant_resolution import DemoInboundLines, DirectoryInboundLines
from overwatch.bootstrap import api_main
from overwatch.bootstrap.api_main import ApiConfigError, check_settings
from overwatch.bootstrap.settings import Settings
from overwatch.bootstrap.tenant_senders import demo_inbound_problem

SHARED_LINE = {
    "platform_twilio_account_sid": "AC" + "9" * 32,
    "platform_sms_from": "+447700900000",
}
INFRA = Path(__file__).resolve().parents[4] / "infra" / "azure"


def test_the_demo_tenant_is_unset_by_default_and_read_from_its_environment_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().demo_inbound_tenant is None
    monkeypatch.setenv("OVERWATCH_DEMO_INBOUND_TENANT", "demo-trust")
    assert Settings().demo_inbound_tenant == "demo-trust"


@pytest.mark.parametrize("value", ["Not A Tenant!", "", "UPPER", "a" * 80])
def test_a_demo_tenant_that_is_not_a_tenant_id_stops_start_up(value: str) -> None:
    with pytest.raises(ApiConfigError, match="OVERWATCH_DEMO_INBOUND_TENANT") as stopped:
        check_settings(Settings(demo_inbound_tenant=value, **SHARED_LINE))

    assert "Not A Tenant" not in str(stopped.value)  # the value is not repeated


def test_a_demo_tenant_with_no_shared_line_stops_start_up() -> None:
    with pytest.raises(ApiConfigError, match="shared line"):
        check_settings(Settings(demo_inbound_tenant="demo-trust"))


def test_a_good_demo_tenant_and_no_demo_tenant_both_start() -> None:
    check_settings(Settings(demo_inbound_tenant="demo-trust", **SHARED_LINE))
    check_settings(Settings())
    assert demo_inbound_problem(Settings()) is None


def test_the_start_up_warning_text_is_the_loud_one() -> None:
    from overwatch.bootstrap.container import build
    from tests.unit.bootstrap.test_api_main import _parts, _secrets

    container = build(Settings(), secrets=_secrets())
    on = Settings(demo_inbound_tenant="demo-trust", **SHARED_LINE)

    warnings = api_main.startup_warnings(on, container, _parts())

    assert (
        "DEMO inbound routing is ON: texts to the shared line go to tenant demo-trust. "
        "Not for production."
    ) in warnings
    assert not any("DEMO" in w for w in api_main.startup_warnings(Settings(), container, _parts()))


def test_the_inbound_directory_has_the_demo_route_only_when_the_setting_is_set() -> None:
    anything: Any = object()
    base = DirectoryInboundLines(anything)
    on = Settings(demo_inbound_tenant="demo-trust", **SHARED_LINE)

    assert api_main.demo_inbound_lines(Settings(**SHARED_LINE), base, anything) is base
    assert isinstance(api_main.demo_inbound_lines(on, base, anything), DemoInboundLines)


def test_the_bicep_parameter_defaults_to_off_with_no_value_in_the_repo() -> None:
    bicep = (INFRA / "apps.bicep").read_text(encoding="utf-8")

    assert "param demoInboundTenant string = ''" in bicep
    # The api takes the setting (the text arrives there), and so do the workers (they send replies)
    # and the relay (it publishes what a demo text wrote).
    assert bicep.count("{ name: 'OVERWATCH_DEMO_INBOUND_TENANT', value: demoInboundTenant }") == 3
    assert "TEMPORARY DEMO" in bicep
