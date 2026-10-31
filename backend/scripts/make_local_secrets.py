"""Writes random development secrets into a private directory for running the API and the workers
locally (B8). No value is printed.

    uv run python scripts/make_local_secrets.py ~/.diucs/secrets
    export DIUCS_SECRETS_DIR=~/.diucs/secrets

See `diucs/bootstrap/local_secrets.py`. The files are the development store (`FileSecretStore`),
which a process refuses in the production profile.
"""

from diucs.bootstrap.local_secrets import main

if __name__ == "__main__":
    raise SystemExit(main())
