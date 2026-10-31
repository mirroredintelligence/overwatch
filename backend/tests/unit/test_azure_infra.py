"""The Azure set-up files and the secrets the applications read (B8, DEC-1304 item 5).

Each app's identity holds `Key Vault Secrets User` on the vault and nothing more; the collector and
Redis hold none; no secret goes to a container app as a plain environment value; SETUP.md names the
secrets each app reads (from the same lists the code checks at start-up).
"""

import re
from pathlib import Path

import pytest

from diucs.bootstrap.api_main import API_OPTIONAL_SECRETS, REQUIRED_SECRETS
from diucs.bootstrap.secret_store import SETTING_SECRET_NAMES
from diucs.bootstrap.workers_main import WORKER_REQUIRED_SECRETS

INFRA = Path(__file__).resolve().parents[3] / "infra" / "azure"
SCRIPT = (INFRA / "create-pilot.sh").read_text(encoding="utf-8")
SETUP = (INFRA / "SETUP.md").read_text(encoding="utf-8")


def _loops(text: str, role: str) -> list[list[str]]:
    """The app names of every `for app in ...; do` loop that creates `role`."""
    found = []
    for match in re.finditer(r"for app in ([a-z ]+); do(.*?)\n\s*done", text, re.S):
        if role in match.group(2):
            found.append(match.group(1).split())
    return found


def test_the_script_gives_api_web_and_workers_secrets_user_on_the_vault() -> None:
    loops = _loops(SCRIPT, "Key Vault Secrets User")

    assert loops == [["api", "web", "workers"]]


def test_setup_gives_the_same_three_the_same_role() -> None:
    assert _loops(SETUP, "Key Vault Secrets User") == [["api", "web", "workers"]]


def test_the_collector_has_no_vault_role() -> None:
    for text in (SCRIPT, SETUP):
        for line in text.splitlines():
            if "Key Vault Secrets" in line and "role assignment" in line:
                assert "collector" not in line
                assert "redis" not in line.lower().replace("redis-url", "")


def test_nothing_is_given_a_broader_vault_role_than_secrets_user_except_the_owner() -> None:
    for text in (SCRIPT, SETUP):
        for role in re.findall(r'--role "([^"]+)"', text):
            if "Key Vault" in role:
                assert role in {"Key Vault Secrets User", "Key Vault Secrets Officer"}
    for line in SCRIPT.splitlines():
        if "Secrets Officer" in line and "role assignment" in line:
            assert "$ME_OID" in line  # the signed-in person, never an app identity


@pytest.mark.parametrize("text", [SCRIPT, SETUP], ids=["create-pilot.sh", "SETUP.md"])
def test_no_container_app_is_given_a_secret_as_an_environment_value(text: str) -> None:
    for line in text.splitlines():
        if re.search(r"--(env-vars|set-env-vars|secrets)\b", line):
            # Only a reference to the vault or a non-secret may follow these flags.
            assert not re.search(
                r"(PASSWORD|SECRET|KEY|TOKEN|CONNECTION|CREDENTIAL)\w*=", line, re.I
            ), line


def test_setup_names_the_two_environment_values_a_vault_app_needs() -> None:
    assert "DIUCS_KEY_VAULT_URL" in SETUP
    assert "AZURE_CLIENT_ID" in SETUP


def test_setup_says_not_to_set_a_client_secret_for_the_identity() -> None:
    assert "AZURE_CLIENT_SECRET" in SETUP


@pytest.mark.parametrize(
    "name",
    sorted(
        {*REQUIRED_SECRETS, *API_OPTIONAL_SECRETS, *SETTING_SECRET_NAMES, *WORKER_REQUIRED_SECRETS}
        | {"session-secret", "edge-origin"}
    ),
)
def test_setup_lists_every_secret_name_the_apps_read(name: str) -> None:
    assert f"`{name}`" in SETUP


def test_setup_has_a_section_for_each_app() -> None:
    for app in ("api", "web", "workers"):
        assert re.search(rf"^#+ .*\b{app}\b.*secrets", SETUP, re.I | re.M), app


def test_the_script_creates_the_platform_secrets_the_apps_read() -> None:
    created = set(
        re.search(r"for name in ([a-z0-9 -]+); do", SCRIPT).group(1).split()  # type: ignore[union-attr]
    )

    assert created >= {name for name in REQUIRED_SECRETS if "/" not in name}
    assert {"session-secret", "edge-origin"} <= created
