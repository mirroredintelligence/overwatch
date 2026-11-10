"""The Analytics User and Advisor v2 hold no standing access to anything yet (DEC-1362).

A new role is refused everywhere until a route or a use case names it. This test keeps the
places that name roles from naming these two by accident: they may appear only in the files that
define them, map them and issue their token. A later task that gives Advisor v2 or the Analytics
User a read adds its file here, in the same change, with its own tests (the service detail read
is the first, DEC-1367).
"""

from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "overwatch"
ALLOWED = {
    # Advisor v2's own reads (DEC-1366): find a service and the capacity overview.
    "application/use_cases/find_services.py",
    "domain/codes.py",
    "domain/model/tenant_records.py",
    "domain/rules/token_exchange.py",
    # The Analytics User's one read (DEC-1368), with its own tests. Advisor v2 stays out of both.
    "application/use_cases/analytics_views.py",
    "adapters/inbound/fhir_rest/routes_analytics.py",
    # The service detail read, named by both new roles (DEC-1367).
    "application/use_cases/service_detail.py",
    # The two postcode lookups Advisor v2's Find a Service uses (DEC-1371).
    "adapters/inbound/fhir_rest/routes_clinical.py",
}
# The files that belong to the Analytics User alone: they must never name Advisor v2. (The
# service detail read is named by both roles, DEC-1367, and Advisor v2's reads are its own.)
ANALYTICS_FILES = {
    "application/use_cases/analytics_views.py",
    "adapters/inbound/fhir_rest/routes_analytics.py",
}
NAMES = ("Role.ANALYTICS_USER", "Role.ADVISOR_V2")


def test_only_the_defining_and_mapping_files_name_the_new_roles() -> None:
    found = {
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if any(name in path.read_text(encoding="utf-8") for name in NAMES)
    }

    assert found <= ALLOWED, sorted(found - ALLOWED)
    assert found, "the new roles are not named anywhere"


def test_no_role_set_that_is_everyone_but_a_few_lets_the_new_roles_in() -> None:
    from overwatch.adapters.inbound.fhir_rest.routes_clinical import PROBLEM_ROLES
    from overwatch.domain.codes import Role

    # Reporting a problem is open to every signed-in person; it reads nothing.
    assert Role.ANALYTICS_USER in PROBLEM_ROLES
    assert Role.ADVISOR_V2 in PROBLEM_ROLES


def test_the_analytics_read_names_the_analytics_user_only() -> None:
    for name in ANALYTICS_FILES:
        path = SRC / name
        assert path.exists(), name
        assert "Role.ADVISOR_V2" not in path.read_text(encoding="utf-8"), name
