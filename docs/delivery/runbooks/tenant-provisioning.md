# Runbook: provisioning a tenant, and a network

For the platform operator. A tenant is created in `provisioning`, filled in, and only then activated; a network is created for an active owner. Every command runs as a named operator (`--operator`), for one tenant at a time, prints fixed words and ids (never a number, address, token or link), and can be run again if it stopped (the steps are repeatable: what is done is not done twice). Decisions: DEC-503 to DEC-506, DEC-136 item 10, DEC-960, DEC-961.

Commands are run from `backend/`:

    uv run python scripts/provision_tenant.py --operator <name> <command> ...
    uv run python scripts/tenant_lifecycle.py --operator <name> <command> ...

## Before you start

- The organisation has signed the data sharing agreement and you hold its references (data sharing, data protection impact assessment, clinical safety case). The system records that you asserted them; it cannot prove them. Information governance and clinical safety approval are human steps that come first (DEC-132 item 9).
- You have: the organisation's id (lower case, letters, digits and hyphens, 2 to 31 characters; it cannot start with `net-`), its legal and display names, the sub-domain it will use (one sub-domain a tenant, DEC-134 item 3), its Twilio subaccount SID and sender number, its Entra directory id, and the first administrator's mobile.
- Secrets (the subaccount's auth token) are put in the secret store under the reference the system derives (`twilio/<tenant>/token`). Never in a command, a ticket or the chat.

## 1. Create and fill in

1. `create <tenant-id> --display-name "..." --legal-name "..." --type <icb|trust|...>` creates the record in `provisioning`, its audit chain (its own genesis) and its scope list.
2. `host <tenant-id> <host>`: its sub-domain. A host another tenant holds is refused.
3. `number <tenant-id> <e164> <account-sid> --label "<sender label>"`, then send a test text from it and record it: `number-tested <tenant-id> <e164>`.
4. `references <tenant-id> --dsa <ref> --dpia <ref> --dcb0160 <ref>`.
5. `verify-directory <tenant-id> <directory-id>` once the tenant's administrator has bound the directory.
6. `invite <tenant-id> <mobile>`: the first administrator's invitation (valid 48 hours). The text is sent from the tenant's own number.
7. The tenant's configuration (names, contacts, retention, role mapping) is drafted and approved by the tenant's people (two approvers for a clinical setting); retention must be set for every data class before activation (DEC-136 item 10).

## 2. Check, then activate

`status <tenant-id>` lists what activation still waits for, in fixed words. When it lists nothing: `activate <tenant-id>`. From that moment the tenant's people can sign in, its recurring jobs are scheduled and it is on the list the workers serve.

If `activate` is refused it says which blockers remain; fix them and run it again. If the process stopped part-way, run the same command again.

## 3. Join a network (optional)

A network is created for an **active** owner organisation, by the operator, and is then run by the owner's network administrator (the API under `/network-admin`, `docs/delivery/fragments/W9A-routes.md`).

    tenant_lifecycle.py --operator <name> network-create <owner-tenant> <network-id> \
        --name "..." --agreement-reference <ref> --agreement-version 1 \
        --system-name "..." --pathway-name "..."

This makes the network's own audit chain first (so a network that exists has somewhere to write to), the registry record, the owner's own membership, and the records in the owner's chain and the network's. The agreement is its reference and version: never its content. Members are then invited by the owner's network administrator and accept the agreement version in force; they share nothing until each member's administrator and the owner's administrator have both approved a grant, and the owner has admitted a listing (see `grant-incidents.md`).

### Naming the owner's network administrators

Nobody can run the network until the owner's directory has a group mapped to the role `network-admin` (TEN-080, DEC-1260). The role is given only while the owner organisation owns an active network, from a group of the owner's own verified directory; a mapping on any other organisation is stored and gives nothing. The owner's tenant administrator cannot make the first mapping until the first administrator can sign in, so the operator names it, once, after the network exists:

    tenant_lifecycle.py --operator <name> network-admin-group <owner-tenant> <directory-group-id>

It maps one group (its object id in the owner's directory) to the role, writes one audit entry in the owner's chain (the role, never the group), and is safe to run again. A group that already gives another role is refused: pick another group. Later groups are the owner's tenant administrator's (`PUT /tenant/role-mappings`).

## What to verify afterwards

- `status` says `active`; the sub-domain opens the tenant's sign-in page and no other tenant's.
- A test text from the tenant's number arrives at the tenant's first reporter and the reply is read by the tenant's scope only (the synthetic check in a dedicated tenant outside every network, TEN-085).
- The audit chain of the tenant holds your commands, by your name; for a network, the network's own chain holds `CreateNetwork`.
- A person of the mapped group signs in on the owner's host and lands on `/network-admin`; a person of the same group on a member's host gets the access message and nothing else.

## Failure modes

| What you see | What it means | What to do |
|---|---|---|
| `refused: this value is held by another tenant` | a host, number or directory is another tenant's | check the value; a retired number is quarantined 90 days and cannot move |
| `refused: Activation is unavailable until: ...` | blockers remain | `status`, then fix each |
| `refused: the owner organisation was not found` | the network's owner is not an active tenant | activate the owner first |
| `refused: a network with this id already exists` | another network holds the id | choose another id; the same network run again is a repeat and finishes what is missing |
| the command stopped (connection lost) | a step did not finish | run the same command again |
