"""FileSecretStore: the development-only secret store, a file per secret (B8, DEC-1304 addendum).

The directory is private to its owner, a name is checked by the one function the vault uses (so a
name that works here works in the vault), and a value is never in a repr, a log or an exception.
"""

import logging
import os
import stat
from pathlib import Path

import pytest

from diucs.adapters.outbound.file_secrets import FileSecretStore, SecretsDirectoryError
from diucs.adapters.outbound.keyvault_secrets import vault_secret_name
from diucs.application.ports.outbound.tokens import SecretStore, SecretStoreUnavailable
from diucs.domain.errors import NotFound

CANARY = "FILE-secret-canary-3d9a1c"


def _private(path: Path) -> Path:
    path.mkdir(exist_ok=True)
    path.chmod(0o700)
    return path


def _write(directory: Path, name: str, value: str | bytes, mode: int = 0o600) -> Path:
    file = directory / name
    file.write_bytes(value.encode() if isinstance(value, str) else value)
    file.chmod(mode)
    return file


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    return _private(tmp_path / "secrets")


def test_it_is_a_secret_store(directory: Path) -> None:
    _write(directory, "bff-jwt", CANARY)
    store: SecretStore = FileSecretStore(directory)

    assert store.get("bff-jwt") == CANARY.encode()


def test_a_slash_in_a_name_is_two_hyphens_in_the_file_name(directory: Path) -> None:
    _write(directory, "twilio--tenant-a--auth-token", "tok")

    assert FileSecretStore(directory).get("twilio/tenant-a/auth-token") == b"tok"


def test_the_file_name_is_the_vault_name(directory: Path) -> None:
    for name in ("bff-jwt", "twilio/tenant-a/auth-token"):
        _write(directory, vault_secret_name(name) or "x", "v")
        assert FileSecretStore(directory).get(name) == b"v"


def test_trailing_line_ends_are_not_part_of_the_value(directory: Path) -> None:
    _write(directory, "bff-jwt", "value\n")
    _write(directory, "link-token", "value\r\n")

    store = FileSecretStore(directory)

    assert store.get("bff-jwt") == b"value"
    assert store.get("link-token") == b"value"


def test_a_value_is_read_again_each_time_so_a_changed_file_is_taken(directory: Path) -> None:
    file = _write(directory, "bff-jwt", "one")
    store = FileSecretStore(directory)
    assert store.get("bff-jwt") == b"one"

    file.write_bytes(b"two")

    assert store.get("bff-jwt") == b"two"


def test_a_missing_file_is_not_found(directory: Path) -> None:
    with pytest.raises(NotFound, match="bff-jwt"):
        FileSecretStore(directory).get("bff-jwt")


def test_an_empty_file_is_not_found(directory: Path) -> None:
    _write(directory, "bff-jwt", "")

    with pytest.raises(NotFound):
        FileSecretStore(directory).get("bff-jwt")


@pytest.mark.parametrize("name", ["", "a--b", "A", "../x", "a/../b", "a_b", "a/", "x" * 128])
def test_a_refused_name_is_not_found_and_no_file_is_opened(
    directory: Path, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[object] = []
    real_open = os.open
    monkeypatch.setattr(os, "open", lambda *a, **k: (opened.append(a), real_open(*a, **k))[1])

    with pytest.raises(NotFound):
        FileSecretStore(directory).get(name)

    assert opened == []


def test_a_name_cannot_reach_a_file_outside_the_directory(tmp_path: Path, directory: Path) -> None:
    _write(tmp_path, "outside", CANARY)

    with pytest.raises(NotFound):
        FileSecretStore(directory).get("../outside")


def test_a_symbolic_link_is_not_followed(tmp_path: Path, directory: Path) -> None:
    target = _write(tmp_path, "elsewhere", CANARY)
    (directory / "bff-jwt").symlink_to(target)

    with pytest.raises(SecretStoreUnavailable) as raised:
        FileSecretStore(directory).get("bff-jwt")

    assert CANARY not in str(raised.value)


def test_a_secret_file_readable_by_others_is_refused_naming_the_secret(directory: Path) -> None:
    _write(directory, "bff-jwt", CANARY, mode=0o644)

    with pytest.raises(SecretStoreUnavailable, match="bff-jwt") as raised:
        FileSecretStore(directory).get("bff-jwt")

    assert CANARY not in str(raised.value)


def test_a_file_that_is_a_directory_is_unreadable_not_missing(directory: Path) -> None:
    (directory / "bff-jwt").mkdir(mode=0o700)

    with pytest.raises(SecretStoreUnavailable):
        FileSecretStore(directory).get("bff-jwt")


def test_a_huge_file_is_refused(directory: Path) -> None:
    _write(directory, "bff-jwt", b"x" * 70_000)

    with pytest.raises(SecretStoreUnavailable):
        FileSecretStore(directory).get("bff-jwt")


# ---- the directory


@pytest.mark.parametrize("mode", [0o750, 0o755, 0o701, 0o770, 0o707])
def test_a_directory_open_to_group_or_others_is_refused(tmp_path: Path, mode: int) -> None:
    open_directory = tmp_path / "open"
    open_directory.mkdir()
    open_directory.chmod(mode)

    with pytest.raises(SecretsDirectoryError, match="group or others"):
        FileSecretStore(open_directory)


@pytest.mark.parametrize("mode", [0o700, 0o500])
def test_a_directory_private_to_its_owner_is_accepted(tmp_path: Path, mode: int) -> None:
    private = tmp_path / "private"
    private.mkdir()
    private.chmod(mode)

    FileSecretStore(private)
    private.chmod(0o700)


def test_a_missing_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SecretsDirectoryError, match="does not exist"):
        FileSecretStore(tmp_path / "nowhere")


def test_a_file_in_place_of_the_directory_is_refused(tmp_path: Path) -> None:
    file = _write(tmp_path, "plain", "x")

    with pytest.raises(SecretsDirectoryError, match="not a directory"):
        FileSecretStore(file)


def test_a_symbolic_link_to_a_directory_is_followed_only_when_the_target_is_private(
    tmp_path: Path, directory: Path
) -> None:
    link = tmp_path / "link"
    link.symlink_to(directory)

    FileSecretStore(link)  # the mode checked is the target's


def test_the_directory_mode_is_the_permission_bits_only(directory: Path) -> None:
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


# ---- no leak


def test_nothing_shows_the_value(directory: Path, caplog: pytest.LogCaptureFixture) -> None:
    _write(directory, "bff-jwt", CANARY)
    _write(directory, "link-token", CANARY, mode=0o666)
    store = FileSecretStore(directory)
    shown: list[str] = []

    with caplog.at_level(logging.DEBUG):
        assert store.get("bff-jwt") == CANARY.encode()
        shown += [repr(store), str(store), repr(vars(store)), str(vars(store))]
        for name in ("link-token", "absent", "a--b"):
            with pytest.raises((NotFound, SecretStoreUnavailable)) as raised:
                store.get(name)
            shown += [str(raised.value), repr(raised.value)]

    assert CANARY not in caplog.text + "\n".join(shown)
