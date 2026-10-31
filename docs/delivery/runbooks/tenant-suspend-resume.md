# Runbook: suspending and resuming a tenant

For the platform operator. A suspension stops a tenant at once without losing anything; a resume puts it back and restarts what stopped. Decisions: DEC-136 item 10, DEC-507, hazards H-20 (a suspended board is a safety event) and H-13 (a service nobody prompts is silent).

    uv run python scripts/provision_tenant.py --operator <name> suspend <tenant-id> --mode <read-only|blocked> --reason <code>
    uv run python scripts/provision_tenant.py --operator <name> resume <tenant-id>

Reasons are a fixed list: `security-incident`, `information-governance`, `clinical-safety`, `contract`, `operator-request`. Free text is never a reason.

## When

- **blocked**: a security incident (a stolen token, a compromised directory). Nobody of the tenant is let in.
- **read-only**: information governance or contract holds, where the tenant's administrator still needs to read and export.
- Before suspending, tell the tenant's shift lead by phone: the tenant's board goes to "Not updated" and its advisors must phone services (the tool-offline state). A suspension in working hours is a clinical-safety event: tell the clinical safety officer.

## What happens

- The registry record is written first and its epoch goes up, so every token issued before is refused (within the edge's cache time, 60 seconds, and for good after a resume).
- The relay and the consumers skip the tenant: nothing is sent, prompted or projected. The tenant's own network sharing is not ended: its projections go stale and read "Not updated, phone to confirm" on the network board by the staleness rule (the status is computed at the time of the read).
- The command run from the script cannot make the **serving** process forget the tenant, so the bound is the cache interval (60 seconds).

## Resume

`resume` does the tenant's work first and the record last: for each active service that its lead has not suspended, the stale prompt is cancelled, the next prompt is scheduled, and a `StatusChanged` is written so the boards recompute; then the record is made active. If it stopped, run it again: the work is marked under the tenant and the epoch and is not done twice.

After a resume, check: the board of the tenant moves off "Not updated" as reporters answer; its network projections catch up within the heartbeat interval (5 minutes); a service the lead had suspended is still suspended.

## What not to do

- Do not suspend to end a tenant's life: use `tenant-offboarding.md`.
- Do not ask for a person's data to "help": the operator has no data access (DEC-134 item 4). Support access to one tenant is the tenant administrator's code, for one hour, audited (DEC-528).
