"""The platform operator's network creation, offboarding, export and purge (TEN-077, TEN-074).

    uv run python scripts/tenant_lifecycle.py --operator <name> offboard <tenant-id>

See `diucs/bootstrap/lifecycle_operations.py` for the commands. The script is a thin entry:
everything it does is a use case of `network_admin.py`, `tenant_offboard.py` or `tenant_purge.py`,
run for one tenant at a time as the platform operator. It prints no secret, number, token, link or
value of a tenant's data.
"""

from diucs.bootstrap.lifecycle_operations import main

if __name__ == "__main__":
    raise SystemExit(main())
