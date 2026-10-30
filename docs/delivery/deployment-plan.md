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
| Messaging | Azure Service Bus (Premium if private endpoints are wanted); topology in `infra/servicebus-config.json` |
| Cache | Azure Managed Redis (Microsoft's recommended service; Azure Cache for Redis is on a retirement path). Use the Enterprise clustering policy unless the code is shown to use no multi-key operations |
| Edge and WAF | Cloudflare (not Front Door, not Application Gateway) |
| Network | VNet, private endpoints and private DNS for Key Vault, Service Bus, Redis and storage |
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
- Redis: no cross-slot multi-key operations unless the Enterprise policy is set.
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
