# Deployment plan (design and plan only)

Status: plan, 2026-10-30. The owner's instruction: nothing is built in Azure now; this records the design so
that nothing in the application contradicts it. It does not gate building and verifying the application.

## Decided by the owner

| Area | Decision |
|---|---|
| Cloud | Azure, UK region (UK South; UK West for disaster recovery, to be confirmed) |
| Compute | Azure Container Apps (ACA): API, web (Next.js) and BFF, workers (outbox relay, bus consumers, scheduler), OpenTelemetry collector; ACA jobs for migrations and scheduled work |
| Images | Azure Container Registry (ACR) |
| Secrets | Azure Key Vault: per-tenant Twilio credentials named `<kind>/<tenant>/<name>`, signing and key-derivation keys, VAPID push keys, the address lookup key. One user-assigned managed identity per app; no secret in an environment variable |
| Graph | Neo4j Aura (managed). Tier (Professional or Business Critical) to be chosen for backups, availability and private networking |
| Messaging | Azure Service Bus, Standard tier for the pilot; topology in `infra/servicebus-config.json`, created by `infra/azure/servicebus-entities.sh` |
| Cache | Redis 7 as an internal container app in the same environment (`infra/azure/redis-app.bicep`): one replica, no persistence, password from Key Vault, plain TCP inside the environment. Azure Managed Redis was tried three times and failed with `OperationFailed` and no detail, so it is not used for the pilot. Revisit it before any tenant beyond the pilot; the code uses plain `redis.asyncio` either way |
| Edge and WAF | Cloudflare (not Front Door, not Application Gateway) |
| Network | No VNet for the pilot. Internal-only ingress is the isolation: only `web` has external ingress; `api`, `workers`, `collector` and `redis` are internal. Key Vault, storage and Service Bus are reachable from the internet with role-based access and TLS as the controls. Moving to a VNet means a new Container Apps environment and a cut-over |
| Storage | Storage account for backups and tenant exports (lifecycle and immutability rules) |
| Email and SMS | Twilio only. SMS and email use one subaccount per tenant and the same credentials. Email is Twilio's own Email API (`comms.twilio.com/v1/Emails`), not SendGrid and not Azure Communication Services Email |
| Governance | Defender for Cloud, Azure Policy, resource locks; deploys from GitHub Actions with OIDC federation (no stored Azure credential) |
| Observability | Log Analytics and Application Insights are NOT used for now. The collector's exporter stays configurable so one can be added; the ACA environment gets no workspace |
| Staff sign-in | Microsoft Entra ID; the operator directory is separate from the tenant directories (DEC-134) |

## What the application must hold to (checked when building)

- Cloudflare: the rate limiter and the tenant host binder must take the client address and original host from
  Cloudflare's headers only when the request comes from Cloudflare; ACA accepts traffic only from Cloudflare
  (IP allow-list or authenticated origin pulls); per-tenant hostnames are Cloudflare custom hostnames; Twilio
  webhooks pass the WAF with the original URL and host intact (signature validation depends on both).
- Email: a per-tenant verified sender domain is a tenant onboarding step (TEN-028 go-live checks); an email send
  answers 202 (queued) and delivery status is read from the Operation resource, mapped to the same delivered or
  failed model as SMS.
- Redis: no cross-slot multi-key operations (the pilot Redis is a single node, so this is not enforced there; a clustered service later would enforce it).
- Neo4j Aura: the schema uses only features the chosen Aura tier offers (to be checked before the tier is chosen).
- Telemetry: the exporter is configurable and may point nowhere.
- Phone numbers: Aura encrypts at rest (DEC-856, pilot only); application-level encryption is a condition for
  any tenant beyond the pilot.

## Planned, not started (each is application code against a port, or infrastructure code)

1. Infrastructure as code (Bicep by default; Terraform if the owner prefers) for the table above.
2. GitHub Actions deploy workflow with OIDC federation.
3. Production secret store: the Key Vault adapter (the production store is still empty, so no real message is sent).
4. Real Entra ID verifier behind the `IdentityVerifier` port (the fake is used today).
5. Trusted-proxy handling for Cloudflare in the edge (client address, host).
6. Twilio Email adapter (the email port is unchanged) and per-tenant domain verification in onboarding.
7. Application-level encryption of phone numbers (DEC-856 option a).
8. The link host and wording sources for production (TEN-022, TEN-028 follow-ups).

Open questions for the owner: Aura tier, UK West for disaster recovery, Bicep or Terraform.

## As built, 31 October 2026 (owner's report; details are in the Azure subscription, not here)

- The pilot infrastructure is provisioned in UK South: resource group, the Container Apps environment (no VNet, no Log
  Analytics), the container registry (empty), Key Vault, Service Bus, storage, four managed identities, and two Entra
  app registrations. Names follow `<type>-diucs-pilot-<suffix>`; the Azure resources keep the `diucs` name (resource
  groups cannot be renamed).
- Apps: `web` (external ingress, hostnames `overwatch.mirroredintelligence.com` for staff and
  `overwatch-admin.mirroredintelligence.com` for the operator console, managed certificates), `api`, `workers` and
  `collector` (internal), and `redis`. They run hello-world placeholders scaled to zero; no application image is
  deployed yet.
- Cloudflare DNS points both names at `web` with the proxy OFF (needed for managed certificate validation and renewal);
  proxying is turned on only after renewal is confirmed. The `edge-origin` header check and the Cloudflare IP
  restrictions are not enforced yet.
- Secrets are in Key Vault; `neo4j-password` and `os-places-api-key` are still to be added by hand.

Open points raised by the as-built design (tracked as work, not decisions): the Service Bus entities were created from an
older topology file and must be re-created from the current one (adds `projection.work`, `network.events`,
`codes.dispatch` and the new subscriptions; the script never deletes, so subscriptions removed from the config stay until
removed by hand); the Twilio webhooks need a public route to the API (`api` is internal); and the API's edge-trust mode
for traffic that arrives from `web` rather than Cloudflare.


### Runtime secrets and the non-secret settings of each app (DEC-1303, DEC-1304)

Secrets are read from Key Vault at run time through each app's managed identity; the environment carries none. These
values are identifiers and URLs, not secrets, and are set on the container apps:

| Setting | api | web | workers | collector |
|---|---|---|---|---|
| `DIUCS_KEY_VAULT_URL` | `https://kv-diucs-pilot-7k2q.vault.azure.net/` | same | same | not needed |
| `AZURE_CLIENT_ID` (the app's own identity) | `9d8902dc-4bcb-4703-8183-67dfcaaf55d6` | `8e25e547-e457-4dce-b0b1-29dd0ed0a5e7` | `dfb0c9ba-6f9d-4f0e-bc68-5a98d6a49670` | `e4700742-daa0-4df1-ba9c-252fb7b4d91a` (no secrets) |

Each of api, web and workers holds Key Vault Secrets User on the vault and nothing more; collector and redis hold none.
`web` also needs `DIUCS_FHIR_BASE_URL` (the API's internal address ending `/fhir`); `api` needs `DIUCS_BASE_URL`
(`https://overwatch.mirroredintelligence.com`) and `DIUCS_EDGE=none`. Twilio: no global credential (DEC-1304 item 9);
the Auth Token is `twilio--<tenant>--auth-token`.

`api` and `workers` also need the Aura connection as plain, non-secret settings: `DIUCS_NEO4J_URI=neo4j+s://8cb817d8.databases.neo4j.io` and `DIUCS_NEO4J_USER=8cb817d8`. The password is the Key Vault secret `neo4j-password` (to be added by the owner).
