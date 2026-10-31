"""Writes random development secrets into a private directory for running the API and the workers
locally (B8). No value is printed.

    uv run python scripts/make_local_secrets.py ~/.overwatch/secrets
    export OVERWATCH_SECRETS_DIR=~/.overwatch/secrets

See `overwatch/bootstrap/local_secrets.py`. The files are the development store (`FileSecretStore`),
which a process refuses in the production profile.
"""

from overwatch.bootstrap.local_secrets import main

if __name__ == "__main__":
    raise SystemExit(main())
