"""Running the API and the workers on a laptop (B8, DEC-1304 addendum).

`DIUCS_SECRETS_DIR` names a private directory with a file for each secret: the development store.
It is refused in production, beside a vault URL and when the directory is open to others. The
`make_local_secrets` script fills the directory with random values and prints none. The lists the
two processes check at start-up are exactly what their code reads.
"""

import base64
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.outbound.file_secrets import FileSecretStore
from diucs.adapters.outbound.push_webpush.web_push import configured_push_sender
from diucs.bootstrap import api_main, outbox_relay_main, workers_main
from diucs.bootstrap.api_main import API_OPTIONAL_SECRETS, REQUIRED_SECRETS, check_secrets
from diucs.bootstrap.local_secrets import make_local_secrets
from diucs.bootstrap.secret_store import SecretConfigError, load_secret_store
from diucs.bootstrap.settings import Settings
from diucs.bootstrap.workers_main import (
    WORKER_OPTIONAL_SECRETS,
    WORKER_REQUIRED_SECRETS,
    WorkersConfigError,
    check_worker_secrets,
)
from diucs.domain.rules.tenant_keys import PER_TENANT_KEY_NAMES

BACKEND = Path(__file__).resolve().parents[3]
VAULT_URL = "https://kv-diucs-pilot-test.vault.azure.net/"
SERVICE_BUS = (
    "Endpoint=sb://sb-test.servicebus.windows.net/;SharedAccessKeyName=k;SharedAccessKey=Zm9v"
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DIUCS_SECRETS_DIR",
        "DIUCS_KEY_VAULT_URL",
        "DIUCS_PROFILE",
        "DIUCS_NEO4J_PASSWORD",
        "DIUCS_REDIS_URL",
        "DIUCS_SERVICEBUS_CONNECTION",
        "DIUCS_OS_PLACES_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def secrets_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "local-secrets"
    make_local_secrets(directory)
    return directory


# ---- the setting and the store it gives


def test_the_directory_setting_is_off_by_default_and_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert Settings().secrets_dir is None

    monkeypatch.setenv("DIUCS_SECRETS_DIR", str(tmp_path))

    assert Settings().secrets_dir == tmp_path


def test_a_directory_gives_the_file_store(secrets_dir: Path) -> None:
    store = load_secret_store(Settings(secrets_dir=secrets_dir))

    assert isinstance(store, FileSecretStore)
    assert len(store.get("bff-jwt")) >= 32


def test_the_vault_url_alone_is_still_the_vault_and_nothing_alone_is_no_store() -> None:
    assert load_secret_store(Settings()) is None


def test_the_production_profile_refuses_the_directory_naming_the_setting(secrets_dir: Path) -> None:
    with pytest.raises(SecretConfigError) as refused:
        load_secret_store(Settings(profile="production", secrets_dir=secrets_dir))

    assert "DIUCS_SECRETS_DIR" in str(refused.value)
    assert "production" in str(refused.value)


def test_the_production_profile_from_the_environment_refuses_it_too(
    monkeypatch: pytest.MonkeyPatch, secrets_dir: Path
) -> None:
    monkeypatch.setenv("DIUCS_PROFILE", "production")
    monkeypatch.setenv("DIUCS_SECRETS_DIR", str(secrets_dir))

    with pytest.raises(SecretConfigError, match="DIUCS_SECRETS_DIR"):
        load_secret_store(Settings())


def test_both_a_vault_url_and_a_directory_are_refused_naming_both(secrets_dir: Path) -> None:
    with pytest.raises(SecretConfigError) as refused:
        load_secret_store(Settings(key_vault_url=VAULT_URL, secrets_dir=secrets_dir))

    assert "DIUCS_KEY_VAULT_URL" in str(refused.value)
    assert "DIUCS_SECRETS_DIR" in str(refused.value)


def test_a_directory_open_to_others_is_refused_naming_the_setting(secrets_dir: Path) -> None:
    secrets_dir.chmod(0o755)

    with pytest.raises(SecretConfigError) as refused:
        load_secret_store(Settings(secrets_dir=secrets_dir))

    assert "DIUCS_SECRETS_DIR" in str(refused.value)
    assert "group or others" in str(refused.value)


def test_a_directory_that_does_not_exist_is_refused_naming_the_setting(tmp_path: Path) -> None:
    with pytest.raises(SecretConfigError, match="DIUCS_SECRETS_DIR"):
        load_secret_store(Settings(secrets_dir=tmp_path / "nowhere"))


def test_the_store_in_use_says_so_at_warning(
    secrets_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    load_secret_store(Settings(secrets_dir=secrets_dir))

    assert any(
        record.levelname == "WARNING" and "development" in record.getMessage()
        for record in caplog.records
    )


# ---- the script


def test_the_script_writes_a_file_for_every_secret_the_api_requires(tmp_path: Path) -> None:
    directory = tmp_path / "made"

    written = make_local_secrets(directory)

    assert set(written) == set(REQUIRED_SECRETS)
    assert {file.name for file in directory.iterdir()} == set(REQUIRED_SECRETS)


def test_the_modes_are_700_for_the_directory_and_600_for_each_file(tmp_path: Path) -> None:
    directory = tmp_path / "made"
    make_local_secrets(directory)

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for file in directory.iterdir():
        assert stat.S_IMODE(file.stat().st_mode) == 0o600, file.name


def test_each_value_is_48_random_bytes_as_base64_and_no_two_are_alike(tmp_path: Path) -> None:
    directory = tmp_path / "made"
    make_local_secrets(directory)

    values = [(directory / name).read_bytes() for name in REQUIRED_SECRETS]

    assert all(len(base64.b64decode(value, validate=True)) == 48 for value in values)
    assert len(set(values)) == len(values)


def test_a_second_run_keeps_what_is_there_and_adds_what_is_missing(tmp_path: Path) -> None:
    directory = tmp_path / "made"
    make_local_secrets(directory)
    before = (directory / "bff-jwt").read_bytes()
    (directory / "pin-hmac").unlink()

    written = make_local_secrets(directory)

    assert written == ["pin-hmac"]
    assert (directory / "bff-jwt").read_bytes() == before


def test_a_directory_open_to_others_is_not_written_to(tmp_path: Path) -> None:
    directory = tmp_path / "open"
    directory.mkdir()
    directory.chmod(0o755)

    with pytest.raises(SecretConfigError, match="group or others"):
        make_local_secrets(directory)

    assert list(directory.iterdir()) == []


def test_the_command_line_prints_names_and_no_value(tmp_path: Path) -> None:
    directory = tmp_path / "made"

    done = subprocess.run(
        [sys.executable, "-I", str(BACKEND / "scripts" / "make_local_secrets.py"), str(directory)],
        capture_output=True,
        text=True,
        check=False,
        cwd=BACKEND,
        env={"PYTHONPATH": str(BACKEND / "src"), "PATH": ""},
    )

    assert done.returncode == 0, done.stderr
    for name in REQUIRED_SECRETS:
        value = (directory / name).read_text(encoding="ascii")
        assert value not in done.stdout + done.stderr
    assert "bff-jwt" in done.stdout


def test_the_command_line_stops_with_a_message_when_no_directory_is_given() -> None:
    done = subprocess.run(
        [sys.executable, "-I", str(BACKEND / "scripts" / "make_local_secrets.py")],
        capture_output=True,
        text=True,
        check=False,
        cwd=BACKEND,
        env={"PYTHONPATH": str(BACKEND / "src"), "PATH": ""},
    )

    assert done.returncode != 0
    assert "directory" in (done.stdout + done.stderr).lower()


# ---- the API starts on it


def test_what_the_script_writes_passes_the_api_start_up_check(secrets_dir: Path) -> None:
    store = load_secret_store(Settings(secrets_dir=secrets_dir))
    assert store is not None

    check_secrets(store)


def test_the_api_prepares_its_parts_over_the_file_store_and_the_plain_settings(
    secrets_dir: Path,
) -> None:
    settings = Settings(secrets_dir=secrets_dir, servicebus_connection=SecretStr(SERVICE_BUS))

    prepared, parts = api_main.prepare_process(settings)

    assert isinstance(parts.secrets, FileSecretStore)
    assert prepared.neo4j_password.get_secret_value() == "diucs-test-password"
    assert prepared.servicebus_connection == settings.servicebus_connection


def test_the_api_entry_point_stops_in_production_with_the_directory(
    monkeypatch: pytest.MonkeyPatch, secrets_dir: Path
) -> None:
    monkeypatch.setenv("DIUCS_PROFILE", "production")
    monkeypatch.setenv("DIUCS_SECRETS_DIR", str(secrets_dir))
    monkeypatch.setenv("DIUCS_SERVICEBUS_CONNECTION", SERVICE_BUS)

    with pytest.raises(SystemExit) as stopped:
        api_main.main()

    assert "DIUCS_SECRETS_DIR" in str(stopped.value)


# ---- the workers start on it


def test_what_the_script_writes_passes_the_workers_start_up_check(secrets_dir: Path) -> None:
    store = load_secret_store(Settings(secrets_dir=secrets_dir))
    assert store is not None

    check_worker_secrets(store)


def test_the_workers_prepare_over_the_file_store(secrets_dir: Path) -> None:
    settings = Settings(secrets_dir=secrets_dir, servicebus_connection=SecretStr(SERVICE_BUS))

    prepared, store = workers_main.prepare_process(settings)

    assert isinstance(store, FileSecretStore)
    assert prepared.redis_url == settings.redis_url


def test_the_workers_stop_when_the_directory_lacks_what_they_read(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir(mode=0o700)
    settings = Settings(secrets_dir=empty, servicebus_connection=SecretStr(SERVICE_BUS))

    with pytest.raises(WorkersConfigError, match="link-token"):
        workers_main.prepare_process(settings)


def test_the_production_workers_refuse_to_run_with_no_secret_store() -> None:
    settings = Settings(profile="production", servicebus_connection=SecretStr(SERVICE_BUS))

    with pytest.raises(WorkersConfigError, match="DIUCS_KEY_VAULT_URL"):
        workers_main.prepare_process(settings)


def test_the_relay_has_no_use_for_the_directory(secrets_dir: Path) -> None:
    settings = Settings(secrets_dir=secrets_dir, servicebus_connection=SecretStr(SERVICE_BUS))

    assert outbox_relay_main.prepare_settings(settings) is settings


# ---- the workers' list is what the workers read


class _Recording:
    """A store that holds every name and records the names asked for."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def get(self, name: str) -> bytes:
        self.asked.append(name)
        return b"synthetic-secret-for-the-recording-store-0123456789"


def test_the_sealer_the_workers_use_reads_exactly_the_required_list() -> None:
    store = _Recording()
    sealer = AesGcmContentSealer(store)  # type: ignore[arg-type]

    sealer.seal("Sample", message_id="m-1", tenant_id="tenant-a", recipient_role_id="r-1")

    assert set(store.asked) == set(WORKER_REQUIRED_SECRETS)


def test_the_push_sender_the_workers_start_reads_exactly_the_optional_list() -> None:
    store = _Recording()

    configured_push_sender(store, "mailto:operations@diucs.example")  # type: ignore[arg-type]

    assert set(store.asked) == set(WORKER_OPTIONAL_SECRETS)


def test_the_workers_lists_are_these_names_and_only_names_the_api_also_knows() -> None:
    assert WORKER_REQUIRED_SECRETS == ("link-token",)
    assert WORKER_OPTIONAL_SECRETS == ("webpush-vapid-private-key",)
    assert set(WORKER_REQUIRED_SECRETS) <= set(PER_TENANT_KEY_NAMES) | set(REQUIRED_SECRETS)
    assert set(WORKER_OPTIONAL_SECRETS) <= set(API_OPTIONAL_SECRETS)


# ---- the address lookup key (OS Places) comes from the store


def test_the_api_reads_the_address_key_from_the_directory_when_the_file_is_there(
    secrets_dir: Path,
) -> None:
    (secrets_dir / "os-places-api-key").write_text("fake-os-key", encoding="ascii")
    (secrets_dir / "os-places-api-key").chmod(0o600)
    settings = Settings(secrets_dir=secrets_dir, servicebus_connection=SecretStr(SERVICE_BUS))

    prepared, _ = api_main.prepare_process(settings)

    assert prepared.os_places_api_key is not None
    assert prepared.os_places_api_key.get_secret_value() == "fake-os-key"
    assert "fake-os-key" not in repr(prepared)


def test_the_api_starts_without_the_address_key_when_the_directory_has_none(
    secrets_dir: Path,
) -> None:
    settings = Settings(secrets_dir=secrets_dir, servicebus_connection=SecretStr(SERVICE_BUS))

    prepared, _ = api_main.prepare_process(settings)

    assert prepared.os_places_api_key is None


def test_with_the_directory_a_key_in_the_environment_still_works_locally(secrets_dir: Path) -> None:
    settings = Settings(
        secrets_dir=secrets_dir,
        servicebus_connection=SecretStr(SERVICE_BUS),
        os_places_api_key=SecretStr("env-key"),
    )

    prepared, _ = api_main.prepare_process(settings)

    assert prepared.os_places_api_key is not None
    assert prepared.os_places_api_key.get_secret_value() == "env-key"


def test_the_api_entry_point_stops_when_the_address_key_is_also_in_the_environment_with_a_vault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_KEY_VAULT_URL", VAULT_URL)
    monkeypatch.setenv("DIUCS_OS_PLACES_API_KEY", "PLAIN-address-key-canary")

    with pytest.raises(SystemExit) as stopped:
        api_main.main()

    assert "DIUCS_OS_PLACES_API_KEY" in str(stopped.value)
    assert "os-places-api-key" in str(stopped.value)
    assert "PLAIN-address-key-canary" not in str(stopped.value)


def test_the_container_takes_the_address_key_from_the_prepared_settings_only() -> None:
    source = Path(api_main.__file__).read_text(encoding="utf-8")

    assert "settings_from_vault(settings, store)" in source
    assert "address_key_from_store" in source
