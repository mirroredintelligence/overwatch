"""No source reads a tenant out of a message payload (TEN-020, DEC-130 item 7, audit B section 7).

A worker binds the tenant from the validated message property (`from_wire`). A tenant in the body
would be a second source that a producer, or a replayed or forged message, could set differently.
The same rule is on `BusMessage` itself, which refuses a payload that names one; this test keeps
the readers honest too.
"""

import re
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "diucs"
_READS_A_TENANT = re.compile(
    r"""(?:payload|message\.payload)\s*(?:\.get\(\s*|\[\s*)["'](?:tenant|tenantId|tenant_id)["']"""
)


def test_no_source_reads_a_tenant_from_a_message_payload() -> None:
    offenders = {
        str(path.relative_to(PACKAGE_ROOT)): [
            number
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
            if _READS_A_TENANT.search(line)
        ]
        for path in PACKAGE_ROOT.rglob("*.py")
    }

    assert {name: lines for name, lines in offenders.items() if lines} == {}


def test_the_pattern_finds_what_it_is_meant_to_find() -> None:
    for line in (
        'tenant = payload.get("tenant")',
        "tenant = payload['tenantId']",
        'x = message.payload.get("tenant_id")',
    ):
        assert _READS_A_TENANT.search(line), line
    for line in ('payload.get("sealed_code")', 'payload["tenants"]', 'tenant = scope["tenant"]'):
        assert not _READS_A_TENANT.search(line), line
