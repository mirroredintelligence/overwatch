"""The platform operator's tenant provisioning script (TEN-028, DEC-503).

    uv run python scripts/provision_tenant.py --operator <name> create <tenant-id> ...

See `diucs/bootstrap/provisioning.py` for the commands. The script is a thin entry: everything it
does is a use case of `application/use_cases/tenant_admin.py` or `tenant_access.py`, run for one
tenant at a time as the platform operator. It prints no secret, number, token or link.
"""

from diucs.bootstrap.provisioning import main

if __name__ == "__main__":
    raise SystemExit(main())
