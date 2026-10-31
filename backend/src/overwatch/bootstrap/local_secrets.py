"""Random platform secrets for running the API and the workers on a development machine (B8).

    uv run python scripts/make_local_secrets.py <directory>
    export DIUCS_SECRETS_DIR=<directory>

Writes a file for every secret the API requires (`REQUIRED_SECRETS`, which holds what the workers
read too), each 48 random bytes as base64 text (64 characters, like the pilot's vault values), into
a directory only its owner can use (mode 700, files 600). A file that exists is kept: running it
again adds what is missing and never rotates a secret. It prints the names it wrote and kept and no
value. The files are read by `FileSecretStore`, which the process refuses in production.
"""

import argparse
import base64
import os
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from diucs.bootstrap.api_main import REQUIRED_SECRETS
from diucs.bootstrap.secret_store import SecretConfigError

SECRET_BYTES: Final = 48
_OTHERS: Final = 0o077


def _prepare(directory: Path) -> None:
    if directory.exists():
        if not directory.is_dir():
            raise SecretConfigError("the secrets path is not a directory")
        if stat.S_IMODE(directory.stat().st_mode) & _OTHERS:
            raise SecretConfigError(
                "the secrets directory is open to group or others: run chmod 700 on it, or use "
                "a new directory"
            )
        return
    directory.mkdir(parents=True)
    directory.chmod(0o700)


def make_local_secrets(directory: Path) -> list[str]:
    """Write the missing secret files into `directory` and return the names written, in order."""
    directory = Path(directory)
    _prepare(directory)
    written: list[str] = []
    for name in REQUIRED_SECRETS:
        path = directory / name
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(descriptor, "wb") as file:
            file.write(base64.b64encode(os.urandom(SECRET_BYTES)))
        path.chmod(0o600)
        written.append(name)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write random development secrets, one file for each, into a private directory."
    )
    parser.add_argument("directory", type=Path, help="the directory to fill (created, mode 700)")
    arguments = parser.parse_args(argv)
    directory: Path = arguments.directory
    try:
        written = make_local_secrets(directory)
    except SecretConfigError as error:
        parser.exit(1, f"{error}\n")
    kept = [name for name in REQUIRED_SECRETS if name not in written]
    print(f"wrote {len(written)} secret files into {directory}: {', '.join(written) or 'none'}")
    if kept:
        print(f"kept {len(kept)} that were there: {', '.join(kept)}")
    print(f"next: export DIUCS_SECRETS_DIR={directory}")
    return 0
