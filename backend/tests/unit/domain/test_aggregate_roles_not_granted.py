"""The Analytics User and Advisor v2 hold no standing access to anything yet (DEC-1362).

A new role is refused everywhere until a route or a use case names it. This test keeps the
places that name roles from naming these two by accident: they may appear only in the files that
define them, map them and issue their token. A later task that gives Advisor v2 or the Analytics
User a read adds its file here, in the same change, with its own tests.
"""

from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "overwatch"
ALLOWED = {
    # Advisor v2's own reads (DEC-1366): find a service and the capacity overview.
    "application/use_cases/find_services.py",
    "domain/codes.py",
    "domain/model/tenant_records.py",
    "domain/rules/token_exchange.py",
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
