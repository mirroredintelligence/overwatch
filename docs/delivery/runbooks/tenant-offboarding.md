# Runbook: offboarding, exporting and purging a tenant

For the platform operator. A tenant that leaves goes through offboarding (a 30-day notice), is given its data, is offboarded, and only then can be purged by two operators. Decisions: DEC-136 item 10, DEC-132 item 6, DEC-271 item 6, DEC-968 to DEC-971; hazards H-T18 (a purge deletes the wrong tenant's data) and H-T29 (backups).

    uv run python scripts/tenant_lifecycle.py --operator <name> offboard <tenant-id> --confirm <tenant-id>
    uv run python scripts/tenant_lifecycle.py --operator <name> export <tenant-id> --out <dir> [--protected]
    uv run python scripts/tenant_lifecycle.py --operator <name> complete-offboarding <tenant-id> --out <dir> --manifest <hash> [--export-waived] [--notice-waived]
    uv run python scripts/tenant_lifecycle.py --operator <name> purge <tenant-id> --second <name> --type-id <tenant-id> [--manifest <hash>] [--dry-run]

## 0. Before

- A tenant that **owns a network** cannot be offboarded: transfer the network or close it first. The command refuses and changes nothing.
- The tenant (or its contract) has asked in writing. A tenant-administrator request or a platform decision starts the 30 days.
- Tell the clinical safety officer: a member that leaves removes its services from the network board.

## 1. Start

`offboard <tenant-id> --confirm <tenant-id>` (or `POST /platform/tenants/{id}/offboarding`, which runs the same step) ends every network membership of the tenant, as a leave: its grants lapse, its listings are withdrawn, its projections in the network scope end with the date (history stays, nothing is deleted), the events are published; then the tenant's record moves to `offboarding`. From then on the edge refuses the tenant's people and the workers skip it: nothing is prompted, sent or projected. The tenant's administrator does not read anything while offboarding; the export is how it gets its data (DEC-968).

If it stopped, run it again. A membership already ended is not met twice.

## 2. Export

`export <tenant-id> --out <dir>` writes one package under `<dir>/<tenant-id>/<package-id>/`: a file for each label set of the tenant's scope grouped by data class (directory and criteria, capacity reports, registrations, communications, cases and requests, people, alerts and flags, configuration, telemetry, support, audit chain), `relationships.jsonl`, and `manifest.json` with the row count and SHA-256 of every file, what was held back or left out (by label set and count), and the head of the audit chain. The command prints the **manifest hash**: that is the receipt.

- Never exported: credentials, device and link-token hashes, sessions, idempotency and outbox bookkeeping, scheduled work.
- Held back unless the tenant asked in writing (`--protected`): staff phone numbers and the text of safety concerns.
- A kind of data with no export class refuses the whole export (`a kind of data has no export class`): do not work around it; file it, the table in `domain/rules/tenant_export.py` needs a decision.
- Hand the directory to the tenant by the route the agreement names (encrypted transfer, with the manifest hash given by another route so they can check it). Every run is its own package; run it again if the tenant asks.

## 3. Complete

`complete-offboarding <tenant-id> --out <dir> --manifest <hash>` needs the export delivered (a package of this tenant whose manifest has this hash) or `--export-waived` (the tenant waived it in writing), and the notice period over (30 days from `offboarding`) or `--notice-waived` (the tenant waived the rest in writing). The record becomes `offboarded`; every active number is **quarantined for 90 days**: it cannot be given to another tenant before. Closing the tenant's Twilio subaccount is a human step: do it and note it.

## 4. Purge

Purging is irreversible. Two operators, the tenant's id typed again, an offboarded tenant whose retention hold has passed (`retentionHoldUntil`), and the dry run reviewed first.

1. `purge <tenant-id> --second <other-operator> --type-id <tenant-id> --dry-run` prints the nodes by label set that would be deleted and changes nothing. Both operators read it against the export's manifest.
2. Run the same command without `--dry-run`.

The order is the safety: the tombstone (both operators' references, the tenant's id, the **head of its audit chain** (last hash and sequence), the export's manifest hash, the counts) is appended to the platform's file first, and if it cannot be written nothing is deleted; then the record becomes `purged`; then the tenant's data is deleted in batches by `tenantId` and nothing else; then its cache names; the audit chain **last**; then a check that nothing of the tenant is left; then the completion entry. The audit chain is kept until the purge (DEC-271) and its final hash outlives it in the tombstone.

If it stopped, run the same command again (`purged` tenants are finished, not refused).

## What stays after a purge

- The registry's record of the tenant (status `purged`), its numbers (quarantined) and its past memberships and grants (`left`, `lapsed`): they carry no tenant data.
- The network scope's projections of the tenant, marked with the date it left: organisational capacity records, kept by the network's retention (information governance decides it).
- The platform's tombstone file. Keep it with the agreement.
- **Backups** are not touched: they expire by their schedule, and information governance has to accept that (H-T29). Do not restore a purged tenant without two operators.

## If something looks wrong

- `refused: Purge is unavailable until: ...` lists the blockers (not offboarded; retention hold not passed; two different operators needed; the tenant id was not typed correctly).
- `the purge did not remove every node of the tenant`: a node is left (a statement refused, a connection lost). Run it again; if it repeats, stop and raise it: do not delete by hand.
- Another tenant's data must never move. The integration test `tests/integration/graph_store/test_tenant_purge.py::test_purging_one_tenant_leaves_the_other_exactly_as_it_was` shows it; if you ever doubt it, stop.
