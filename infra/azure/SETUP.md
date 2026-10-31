# Azure and Entra set-up commands (run by the owner; nothing here has been run)

Status: written 2026-10-31 for the owner to run. The agent has no Azure access and has not run any of this. Flags
were written from memory of the `az` CLI: if one is refused, run the command with `--help` and tell me what it says.
Nothing here is applied to the repository. Secrets are piped straight into Key Vault and never printed.

Decisions already made (docs/delivery/deployment-plan.md): UK South; Aura for Neo4j (not created here: it is bought
from Neo4j); Azure Managed Redis; Cloudflare in front (DNS, WAF, custom hostnames are in Cloudflare, not here); a VNet
with private endpoints; a storage account; no Log Analytics or Application Insights for now; Twilio for SMS and email.

## 0. Variables (edit these first)

```bash
export SUB="<subscription id>"
export LOC="uksouth"
export P="diucs"                 # prefix
export E="pilot"                 # environment name: pilot, prod
export RG="rg-$P-$E-uks"
export VNET="vnet-$P-$E"
# Names that must be globally unique (lower case letters and digits, check availability):
export ACR="acr${P}${E}$RANDOM"          # 5 to 50 characters
export KV="kv-$P-$E-$RANDOM"             # 3 to 24 characters
export SA="st${P}${E}$RANDOM"            # 3 to 24 characters, lower case and digits only
export SB="sb-$P-$E-$RANDOM"             # 6 to 50 characters
export REDIS="redis-$P-$E-$RANDOM"
```

Write the generated names down: later steps and the application settings need them.

## 1. Subscription, resource providers, resource group

```bash
az account set --subscription "$SUB"
for ns in Microsoft.App Microsoft.ContainerRegistry Microsoft.KeyVault Microsoft.ServiceBus Microsoft.Cache Microsoft.Storage Microsoft.Network Microsoft.ManagedIdentity; do az provider register --namespace $ns; done
az group create --name "$RG" --location "$LOC" --tags app=diucs env="$E"
az lock create --name no-delete --lock-type CanNotDelete --resource-group "$RG"
```

## 2. Network: VNet, a subnet for Container Apps, a subnet for private endpoints

```bash
az network vnet create -g "$RG" -n "$VNET" --address-prefixes 10.20.0.0/16 --subnet-name snet-aca --subnet-prefixes 10.20.0.0/23
az network vnet subnet update -g "$RG" --vnet-name "$VNET" -n snet-aca --delegations Microsoft.App/environments
az network vnet subnet create -g "$RG" --vnet-name "$VNET" -n snet-pe --address-prefixes 10.20.4.0/24
```

## 3. Managed identities (one per app; they hold the permissions, so no secret goes in an environment variable)

```bash
for app in api web workers collector; do az identity create -g "$RG" -n "id-$P-$app-$E" --location "$LOC"; done
```

## 4. Container registry

```bash
az acr create -g "$RG" -n "$ACR" --sku Premium --admin-enabled false --location "$LOC"
for app in api web workers collector; do
  az role assignment create --assignee-object-id "$(az identity show -g "$RG" -n "id-$P-$app-$E" --query principalId -o tsv)" --assignee-principal-type ServicePrincipal --role AcrPull --scope "$(az acr show -n "$ACR" --query id -o tsv)"
done
```

Premium is needed for a private endpoint. Standard is cheaper and has no private endpoint.

## 5. Key Vault (role-based access; purge protection on)

```bash
az keyvault create -g "$RG" -n "$KV" --location "$LOC" --enable-rbac-authorization true --enable-purge-protection true --retention-days 90
for app in api web workers; do
  az role assignment create --assignee-object-id "$(az identity show -g "$RG" -n "id-$P-$app-$E" --query principalId -o tsv)" --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" --scope "$(az keyvault show -n "$KV" --query id -o tsv)"
done
# You need to be able to write secrets yourself:
az role assignment create --assignee "$(az ad signed-in-user show --query id -o tsv)" --role "Key Vault Secrets Officer" --scope "$(az keyvault show -n "$KV" --query id -o tsv)"
```

### 5a. What each app is given, and the secrets it reads (DEC-1304)

No secret is ever an environment value of a container app. Each app reads its secrets from Key Vault at run
time through its own managed identity. An app is given exactly these settings, and nothing secret:

| Setting | Value (pilot) | Apps |
|---|---|---|
| `DIUCS_KEY_VAULT_URL` | `https://kv-diucs-pilot-7k2q.vault.azure.net/` | api, web, workers |
| `AZURE_CLIENT_ID` | the client id of the app's own identity (below) | api, web, workers |
| `DIUCS_NEO4J_URI` | `neo4j+s://8cb817d8.databases.neo4j.io` | api, workers |
| `DIUCS_NEO4J_USER` | `8cb817d8` | api, workers |

`AZURE_CLIENT_ID` for each identity: api `9d8902dc-4bcb-4703-8183-67dfcaaf55d6`, web
`8e25e547-e457-4dce-b0b1-29dd0ed0a5e7`, workers `dfb0c9ba-6f9d-4f0e-bc68-5a98d6a49670`, collector
`e4700742-daa0-4df1-ba9c-252fb7b4d91a` (the collector and Redis are given no vault setting and no vault role).
The other non-secret settings (`DIUCS_PROFILE=production`, `DIUCS_BASE_URL`, `DIUCS_EDGE`, ...) are plain settings
too. When creating or updating an app, give the settings like this, one to a line, so none can be mistaken for a
secret (the pilot values are in the table above):

```bash
az containerapp create -g "$RG" -n "ca-$P-api-$E" --environment "cae-$P-$E" --user-assigned "$ID_API" \
  --image "$ACR.azurecr.io/diucs-api:<tag>" --registry-server "$ACR.azurecr.io" --registry-identity "$ID_API" \
  --env-vars \
    "DIUCS_PROFILE=production" \
    "DIUCS_KEY_VAULT_URL=https://kv-diucs-pilot-7k2q.vault.azure.net/" \
    "AZURE_CLIENT_ID=9d8902dc-4bcb-4703-8183-67dfcaaf55d6" \
    "DIUCS_NEO4J_URI=neo4j+s://8cb817d8.databases.neo4j.io" \
    "DIUCS_NEO4J_USER=8cb817d8"
```

Never set `DIUCS_NEO4J_PASSWORD`, `DIUCS_REDIS_URL`, `DIUCS_SERVICEBUS_CONNECTION` or `DIUCS_OS_PLACES_API_KEY` on
an app that has `DIUCS_KEY_VAULT_URL`: the process refuses to start (it names the variable and the vault secret that
replaces it, never a value). Never set `AZURE_CLIENT_SECRET` (or `AZURE_TENANT_ID` with it) for these apps: the
identity is the managed identity, and a client secret in the environment would be used before it and would be a
secret in plain configuration.

Each identity holds `Key Vault Secrets User` on this one vault (the three role assignments above are api, web and
workers) and nothing wider; the collector and Redis hold no vault role. The names below are exactly what the
start-up check reads. A missing required name stops the process and the message names the secret, never a value; an
optional one is a warning and the feature it serves stays off. A value that is shorter than 32 bytes is refused.
Each value is cached for 10 minutes (`DIUCS_SECRET_CACHE_SECONDS`), so a rotated secret reaches a running app within
that time; if the vault cannot be reached a value already held is served for up to an hour more
(`DIUCS_SECRET_STALE_SECONDS`, `0` for strict).

#### The api: secrets it reads

Required (the process stops without them): `bff-jwt`, `account-ref`, `phone-hash`, `link-token`, `link-csrf`,
`code-hmac`, `pin-hmac`, `device-token`, `support-code`, `telemetry-markers`, and the three the settings come from:
`neo4j-password`, `redis-url`, `servicebus-connection`.

Optional (a warning at start-up): `edge-origin` (the origin secret behind Cloudflare), `webpush-vapid-private-key`
and `webpush-vapid-public-key` (web push), `os-places-api-key` (address lookup; with none, registration offers no
address). Read when a tenant sends or receives, never at start-up: `twilio/<tenant>/auth-token`, stored as the vault
name `twilio--<tenant>--auth-token` (a tenant id with `--` or a trailing hyphen has no vault name, so its secret
cannot be stored: choose another id).

#### The workers: secrets they read

Required: `link-token` (the key of the sealed message content), and the settings' `neo4j-password`, `redis-url`,
`servicebus-connection`. Optional: `webpush-vapid-private-key` (without it no push is sent). Per tenant, at the
moment of a send: `twilio--<tenant>--auth-token` and the SMTP login of the tenant's own reference. The workers
read the vault themselves and never call the api, so an api outage does not stop them.

#### The web app: secrets it reads

`session-secret` and `edge-origin` only, nothing else. (How the web app reads them from the vault is the front end's
change; this file only fixes what its identity may hold.)

#### Names in the vault, and the two still to add

The pilot script created: `bff-jwt`, `account-ref`, `phone-hash`, `link-token`, `link-csrf`, `code-hmac`, `pin-hmac`,
`device-token`, `support-code`, `telemetry-markers`, `edge-origin`, `session-secret`, `webpush-vapid-private-key`,
`webpush-vapid-public-key`, `servicebus-connection`, `redis-url`, `entra-staff-client-secret`,
`entra-operator-client-secret`. Add by hand (see section 13): `neo4j-password` and `os-places-api-key`. The two
global Twilio entries (`twilio-account-sid`, `twilio-auth-token`) are not read by any code: copy the auth token once
to `twilio--<tenant>--auth-token` for the tenant it belongs to, then delete both (DEC-1304 item 9).

A vault name holds lower-case letters, digits and single hyphens only, up to 127 characters; the code writes
`<kind>/<tenant>/<name>` as `<kind>--<tenant>--<name>`, and refuses anything else without calling the vault.

## 6. Service Bus

Standard supports topics, sessions and duplicate detection and has no private endpoint. Premium (about a thousand pounds
a year per messaging unit more) adds private endpoints and a VNet. Choose one:

```bash
az servicebus namespace create -g "$RG" -n "$SB" --location "$LOC" --sku Standard
# or: az servicebus namespace create -g "$RG" -n "$SB" --location "$LOC" --sku Premium --capacity 1
```

The queues, topics and subscriptions come from the repository's config so the cloud matches what the tests run
against. From the repository root (after pulling the branch that holds `infra/servicebus-config.json`; run it again after
the code-sending change lands, because the `codes.dispatch` topic is being added), this creates them over the ARM REST
API so the property names are the ones in the file:

```bash
bash infra/azure/servicebus-entities.sh "$RG" "$SB"
```

(the script is in this folder: `infra/azure/servicebus-entities.sh`)

```bash
for app in api workers; do
  az role assignment create --assignee-object-id "$(az identity show -g "$RG" -n "id-$P-$app-$E" --query principalId -o tsv)" --assignee-principal-type ServicePrincipal --role "Azure Service Bus Data Owner" --scope "$(az servicebus namespace show -g "$RG" -n "$SB" --query id -o tsv)"
done
```

(Data Owner is wider than needed; Data Sender plus Data Receiver per entity is tighter and can follow.)

## 7. Redis (Azure Managed Redis)

Pilot tier: `Balanced_B0`, the smallest Azure Managed Redis SKU. The Enterprise and Enterprise Flash tiers are not used,
and no classic Azure Cache for Redis (Basic or Standard) is used: Microsoft has blocked creating new classic caches for
existing customers from 1 October 2026 and retires them on 30 September 2028, so classic is not a choice here.

```bash
az redisenterprise create -g "$RG" -n "$REDIS" --location "$LOC" --sku Balanced_B0 --clustering-policy EnterpriseCluster --public-network-access Disabled
```

This is the least certain command here: Azure Managed Redis uses the `redisenterprise` command group, and the SKU
names and flags change. Run `az redisenterprise create --help` and tell me if a flag is refused. `EnterpriseCluster`
gives a single endpoint and no cross-slot restrictions. With public access disabled you also need a private endpoint
(section 9) before anything can connect.

## 8. Storage account (backups and tenant exports)

```bash
az storage account create -g "$RG" -n "$SA" --location "$LOC" --sku Standard_GRS --kind StorageV2 --allow-blob-public-access false --min-tls-version TLS1_2 --https-only true
az storage container create --account-name "$SA" --name tenant-exports --auth-mode login
az storage container create --account-name "$SA" --name neo4j-backups --auth-mode login
az storage container immutability-policy create --account-name "$SA" --container-name tenant-exports --period 30 2>/dev/null || echo "set the immutability policy in the portal or tell me the error"
```

## 9. Private endpoints (Key Vault, Service Bus if Premium, Redis, storage, registry)

```bash
export SNPE="$(az network vnet subnet show -g "$RG" --vnet-name "$VNET" -n snet-pe --query id -o tsv)"
az network private-endpoint create -g "$RG" -n pe-kv --subnet "$SNPE" --private-connection-resource-id "$(az keyvault show -n "$KV" --query id -o tsv)" --group-id vault --connection-name kv
az network private-endpoint create -g "$RG" -n pe-st-blob --subnet "$SNPE" --private-connection-resource-id "$(az storage account show -g "$RG" -n "$SA" --query id -o tsv)" --group-id blob --connection-name stblob
az network private-endpoint create -g "$RG" -n pe-acr --subnet "$SNPE" --private-connection-resource-id "$(az acr show -n "$ACR" --query id -o tsv)" --group-id registry --connection-name acr
```

Each private endpoint also needs a private DNS zone (`privatelink.vaultcore.azure.net`,
`privatelink.blob.core.windows.net`, `privatelink.azurecr.io`, and for Service Bus Premium
`privatelink.servicebus.windows.net`, and for Redis `privatelink.redis.azure.net`) linked to the VNet. I can write
those out once you confirm the Service Bus tier and the Redis SKU, because their group ids depend on the choice.

## 10. Container Apps environment (no log destination, as agreed; apps are created at deploy time)

```bash
az containerapp env create -g "$RG" -n "cae-$P-$E" --location "$LOC" --infrastructure-subnet-resource-id "$(az network vnet subnet show -g "$RG" --vnet-name "$VNET" -n snet-aca --query id -o tsv)" --logs-destination none --enable-workload-profiles
```

## 11. Entra app registrations

The staff app serves other organisations' staff (each tenant has its own Entra directory), so it is multi-tenant. The
operator app is the platform operator's own directory only. Replace the hostnames.

```bash
export STAFF_HOST="<the tenant host, for example capacity.example.org>"
export OPS_HOST="<the operator console host, a separate host>"
```

```bash
az ad app create --display-name "DIUCS Staff" --sign-in-audience AzureADMultipleOrgs --web-redirect-uris "https://$STAFF_HOST/api/bff/auth/entra/callback" --enable-id-token-issuance true --query appId -o tsv
```

Save that application (client) id as `STAFF_APP_ID`, then:

```bash
az ad sp create --id "$STAFF_APP_ID"
az ad app update --id "$STAFF_APP_ID" --set groupMembershipClaims=SecurityGroup
az ad app credential reset --id "$STAFF_APP_ID" --display-name diucs-bff --years 1 --query password -o tsv | az keyvault secret set --vault-name "$KV" --name entra-staff-client-secret --value @/dev/stdin --output none
```

```bash
az ad app create --display-name "DIUCS Operator Console" --sign-in-audience AzureADMyOrg --web-redirect-uris "https://$OPS_HOST/api/bff/platform/auth/callback" --enable-id-token-issuance true --query appId -o tsv
```

Save it as `OPS_APP_ID`, then:

```bash
az ad sp create --id "$OPS_APP_ID"
az ad app update --id "$OPS_APP_ID" --set groupMembershipClaims=SecurityGroup
az ad app credential reset --id "$OPS_APP_ID" --display-name diucs-operator --years 1 --query password -o tsv | az keyvault secret set --vault-name "$KV" --name entra-operator-client-secret --value @/dev/stdin --output none
az account show --query tenantId -o tsv
```

The last line prints the operator directory id (`OPERATOR_ENTRA_DIRECTORY_ID`).

Things about the staff app you should know:
- The sign-in code reads one `DIUCS_PUBLIC_URL`, so today one deployment serves one tenant host. Each further tenant
  host needs its own redirect URI added to this app; that is a known gap I will close (per-tenant redirect), not
  something to work around by hand now.
- Every customer organisation's Entra administrator must consent to the app in their own directory, and you need
  security groups there to map to roles (`groups` claim). Give me the group object ids per tenant when you onboard one.
- The secrets expire in a year. A certificate is better than a secret; I can switch the code to a certificate later.


## Pilot without a VNet (owner's decision 2026-10-31)

For the pilot, skip section 2 (network), section 9 (private endpoints and private DNS) and the private-link parts of
sections 4, 6 and 7. Use these instead:

- Container registry: `--sku Standard` (Premium is only needed for a private endpoint).
- Service Bus: `--sku Standard`.
- Redis: create it with public network access enabled (TLS only, access keys or Entra authentication); store the
  connection string or key in Key Vault. Change `--public-network-access Disabled` to `Enabled`.
- Key Vault and storage: leave the public endpoint on; access is role-based only (no access policies, no keys for
  storage: `--allow-shared-key-access false` on the storage account).
- Container Apps environment: create it without `--infrastructure-subnet-resource-id`.

```bash
az containerapp env create -g "$RG" -n "cae-$P-$E" --location "$LOC" --logs-destination none --enable-workload-profiles
```

Restrict the front door instead: when the apps are created, set ingress IP restrictions to Cloudflare's published
ranges only (`az containerapp ingress access-restriction set`), and add the `edge-origin` secret check the API already
supports (`X-Edge-Auth`). Without a VNet the environment has no fixed outbound address, so Key Vault, storage and Redis
cannot be limited by source address: managed identities, role-based access and TLS are the controls.

Moving to a VNet later is not an in-place change: a Container Apps environment's network cannot be changed after it
is created, so it means a new environment, new apps and a cut-over. Do it before any tenant beyond the pilot.

## 12. Values to send back (not secrets)

Send me these, and nothing secret: subscription id, resource group name, the generated names (`ACR`, `KV`, `SA`, `SB`,
`REDIS`), `STAFF_APP_ID`, `OPS_APP_ID`, the operator directory id, `STAFF_HOST`, `OPS_HOST`, the Service Bus tier,
the Redis SKU you ended up with, any command that failed with its error text. Never paste a secret, key, token
or connection string into this chat.

## 13. Not here (needs you, outside Azure)

- Neo4j Aura: buy the instance from Neo4j (the Azure Marketplace listing or Aura directly) in a UK region. Send me the
  connection URI (not the password).
- Cloudflare: zone, DNS, custom hostnames, WAF rules, authenticated origin pulls.
- Twilio: account, a subaccount and number per tenant, a verified email sender domain per tenant.
- OS Places API key from OS Data Hub (stored as the vault secret `os-places-api-key`, optional), and the licensed
  Pathways Dx file. The Neo4j password is the vault secret `neo4j-password`.
