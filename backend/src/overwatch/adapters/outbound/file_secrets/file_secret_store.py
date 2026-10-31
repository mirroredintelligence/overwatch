"""FileSecretStore: a directory with one file for each secret, for running the API and the workers
on a development machine (DEC-1304 addendum). It is never the production store: the process refuses
it when the profile is production (`bootstrap/secret_store.py`).

The file is named by the secret's store name (`vault_secret_name`: `/` becomes `--`, the same
alphabet as the vault), and its content is the value, with any trailing line end removed. A name
with no store name is `NotFound`, and no file is opened for it, so a name cannot reach outside the
directory. The directory must be private to its owner (no permission for group or others), and so
must each secret file; a symbolic link is not followed. A value is read afresh each time (nothing is
cached; a changed file is taken at once). A value is never in a repr, a log or an exception.
"""

import os
import stat
from pathlib import Path
from typing import Final

from diucs.application.ports.outbound.tokens import SecretStoreUnavailable
from diucs.domain.errors import NotFound
from diucs.domain.rules.secret_names import vault_secret_name

MAX_SECRET_BYTES: Final = 65_536
_OTHERS: Final = 0o077
_OPEN_FLAGS: Final = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


class SecretsDirectoryError(Exception):
    """The secrets directory cannot be used. The text names no value."""


class FileSecretStore:
    def __init__(self, directory: Path) -> None:
        try:
            info = directory.stat()
        except FileNotFoundError:
            raise SecretsDirectoryError("the secrets directory does not exist") from None
        except OSError:
            raise SecretsDirectoryError("the secrets directory cannot be read") from None
        if not stat.S_ISDIR(info.st_mode):
            raise SecretsDirectoryError("the secrets path is not a directory")
        if stat.S_IMODE(info.st_mode) & _OTHERS:
            raise SecretsDirectoryError(
                "the secrets directory is open to group or others: run chmod 700 on it"
            )
        self._directory = directory

    def get(self, name: str) -> bytes:
        file_name = vault_secret_name(name)
        if file_name is None:
            raise NotFound("secret name is not a valid reference")
        try:
            descriptor = os.open(self._directory / file_name, _OPEN_FLAGS)
        except FileNotFoundError:
            raise NotFound(f"secret {name}") from None
        except OSError:
            raise SecretStoreUnavailable(f"secret {name} could not be read") from None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & _OTHERS:
                raise SecretStoreUnavailable(
                    f"secret {name} could not be read: its file is not a plain file private to "
                    "its owner"
                )
            if info.st_size > MAX_SECRET_BYTES:
                raise SecretStoreUnavailable(
                    f"secret {name} could not be read: its file is too big"
                )
            raw = os.read(descriptor, MAX_SECRET_BYTES + 1)
        except OSError:
            raise SecretStoreUnavailable(f"secret {name} could not be read") from None
        finally:
            os.close(descriptor)
        value = raw.rstrip(b"\r\n")
        if not value:
            raise NotFound(f"secret {name}")
        return value

    def __repr__(self) -> str:
        return f"FileSecretStore({self._directory})"
