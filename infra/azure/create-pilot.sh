#!/usr/bin/env bash
# Creates the DIUCS pilot resources in Azure (no VNet, no Log Analytics: see docs/delivery/deployment-plan.md and
# infra/azure/SETUP.md). Written by the agent; NOT RUN by the agent, which has no Azure access. The `az` flags
# are from memory: a step that fails prints what failed and the script goes on where it safely can; send the text.
#
# Needs: az CLI logged in (`az login`), `openssl`, `jq`; the role to create resources and role assignments in the
# subscription (Owner, or Contributor plus User Access Administrator), and in Entra the right to register apps.
#
#   SFX=7k2q STAFF_HOST=capacity.example.org OPS_HOST=ops.example.org bash infra/azure/create-pilot.sh
#
# SFX is 4 lower-case letters or digits that make the globally unique names unique. It is required: choose it once
# and keep it. STAFF_HOST and OPS_HOST are optional here (placeholders are used, with the command to fix them).
# Secrets are generated here, written to Key Vault from a private temporary file and never printed. The non-secret
# outputs (names, ids) are written to ./pilot-outputs.txt: send me that file, never a secret.
set -uo pipefail

SUB="3547cde4-a873-4904-95ac-5f87e0d9e8d5"
LOC="uksouth"
P="diucs"
E="pilot"
RG="rg-diucs-pilot-uks"
SFX="${SFX:?set SFX to 4 lower-case letters or digits, for example SFX=7k2q}"
[[ "$SFX" =~ ^[a-z0-9]{4}$ ]] || { echo "SFX must be 4 lower-case letters or digits" >&2; exit 1; }

VNET_NOT_USED="no VNet for the pilot"
ACR="acr${P}${E}${SFX}"
KV="kv-${P}-${E}-${SFX}"
SA="st${P}${E}${SFX}"
SB="sb-${P}-${E}-uks"
REDIS="redis-${P}-${E}-uks"
CAE="cae-${P}-${E}-uks"
STAFF_HOST="${STAFF_HOST:-capacity.example.invalid}"
OPS_HOST="${OPS_HOST:-ops.example.invalid}"
OUT="./pilot-outputs.txt"
FAILED=()

say() { printf '\n== %s\n' "$*"; }
try() { # try <description> <command...>: run, record a failure, keep going
  local d="$1"; shift
  if ! "$@"; then FAILED+=("$d"); echo "!! FAILED: $d" >&2; return 1; fi
}
note() { echo "$*" >> "$OUT"; }

: > "$OUT"
command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

say "subscription"
az account set --subscription "$SUB" || { echo "cannot select the subscription" >&2; exit 1; }
ME_OID="$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)"
note "subscription=$SUB resource_group=$RG location=$LOC suffix=$SFX"

say "extensions and resource providers"
try "extensions" az extension add --name containerapp --upgrade --only-show-errors
try "redisenterprise extension" az extension add --name redisenterprise --upgrade --only-show-errors
for ns in Microsoft.App Microsoft.ContainerRegistry Microsoft.KeyVault Microsoft.ServiceBus Microsoft.Cache Microsoft.Storage Microsoft.ManagedIdentity; do
  az provider register --namespace "$ns" --only-show-errors >/dev/null
done

say "resource group"
try "resource group" az group create --name "$RG" --location "$LOC" --tags app=diucs env="$E" --output none
try "resource lock" az lock create --name no-delete --lock-type CanNotDelete --resource-group "$RG" --output none

say "managed identities"
for app in api web workers collector; do
  try "identity $app" az identity create -g "$RG" -n "id-${P}-${app}-${E}" --location "$LOC" --output none
done
pid() { az identity show -g "$RG" -n "id-${P}-$1-${E}" --query principalId -o tsv; }

say "container registry (Standard)"
if try "registry" az acr create -g "$RG" -n "$ACR" --sku Standard --admin-enabled false --location "$LOC" --output none; then
  ACR_ID="$(az acr show -n "$ACR" --query id -o tsv)"
  for app in api web workers collector; do
    try "AcrPull $app" az role assignment create --assignee-object-id "$(pid $app)" --assignee-principal-type ServicePrincipal --role AcrPull --scope "$ACR_ID" --output none
  done
  note "acr=$ACR login_server=$(az acr show -n "$ACR" --query loginServer -o tsv)"
fi

say "key vault (role-based access, purge protection)"
if try "key vault" az keyvault create -g "$RG" -n "$KV" --location "$LOC" --enable-rbac-authorization true --enable-purge-protection true --retention-days 90 --output none; then
  KV_ID="$(az keyvault show -n "$KV" --query id -o tsv)"
  for app in api web workers; do
    try "Key Vault Secrets User $app" az role assignment create --assignee-object-id "$(pid $app)" --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" --scope "$KV_ID" --output none
  done
  if [[ -n "$ME_OID" ]]; then
    try "Key Vault Secrets Officer (you)" az role assignment create --assignee-object-id "$ME_OID" --assignee-principal-type User --role "Key Vault Secrets Officer" --scope "$KV_ID" --output none
  fi
  note "key_vault=$KV vault_uri=$(az keyvault show -n "$KV" --query properties.vaultUri -o tsv)"
fi

# Writes a secret to Key Vault from a private temp file (never printed, never in the process list).
# put_secret <name> reads the value from stdin.
put_secret() {
  local name="$1" tmp
  tmp="$(mktemp)"; chmod 600 "$tmp"
  cat > "$tmp"
  local n=0
  until az keyvault secret set --vault-name "$KV" --name "$name" --file "$tmp" --encoding utf-8 --output none 2>/dev/null; do
    n=$((n + 1)); [[ $n -ge 12 ]] && { rm -f "$tmp"; FAILED+=("secret $name"); echo "!! FAILED: secret $name (role assignment may still be propagating: rerun)" >&2; return 1; }
    sleep 15   # a new role assignment can take a few minutes to reach Key Vault
  done
  rm -f "$tmp"
}

say "key vault secrets: platform keys (random, 48 bytes each; never printed)"
for name in bff-jwt account-ref phone-hash link-token link-csrf code-hmac pin-hmac device-token support-code telemetry-markers edge-origin session-secret; do
  if az keyvault secret show --vault-name "$KV" --name "$name" --query id -o tsv >/dev/null 2>&1; then
    echo "  $name already exists, left as it is"
  else
    openssl rand -base64 48 | tr -d '\n' | put_secret "$name" && echo "  $name created"
  fi
done

say "web push (VAPID) key pair"
if az keyvault secret show --vault-name "$KV" --name webpush-vapid-private-key >/dev/null 2>&1; then
  echo "  VAPID keys already exist, left as they are"
else
  TMPK="$(mktemp -d)"; chmod 700 "$TMPK"
  if openssl ecparam -name prime256v1 -genkey -noout -out "$TMPK/priv.pem" 2>/dev/null; then
    # The application expects the URL-safe base64 raw keys web-push libraries use: private = 32-byte scalar,
    # public = 65-byte uncompressed point.
    openssl ec -in "$TMPK/priv.pem" -outform DER 2>/dev/null | tail -c +8 | head -c 32 | basenc --base64url -w0 2>/dev/null | tr -d '=' | put_secret webpush-vapid-private-key && \
    openssl ec -in "$TMPK/priv.pem" -pubout -outform DER 2>/dev/null | tail -c 65 | basenc --base64url -w0 2>/dev/null | tr -d '=' | put_secret webpush-vapid-public-key && echo "  VAPID keys created" \
      || { FAILED+=("VAPID keys"); echo "!! VAPID key generation failed: tell me the output of 'openssl version' and 'basenc --version'" >&2; }
  else
    FAILED+=("VAPID keys")
  fi
  rm -rf "$TMPK"
fi

say "service bus (Standard) and its queues, topics and subscriptions"
if try "service bus" az servicebus namespace create -g "$RG" -n "$SB" --location "$LOC" --sku Standard --output none; then
  note "service_bus=$SB"
  CONFIG="${CONFIG:-infra/servicebus-config.json}"
  if [[ -f "$CONFIG" && -f infra/azure/servicebus-entities.sh ]]; then
    try "service bus entities" bash infra/azure/servicebus-entities.sh "$RG" "$SB"
  else
    echo "  run from the repository root to create the entities: bash infra/azure/servicebus-entities.sh $RG $SB"
  fi
  CS="$(az servicebus namespace authorization-rule keys list -g "$RG" --namespace-name "$SB" --name RootManageSharedAccessKey --query primaryConnectionString -o tsv 2>/dev/null || true)"
  if [[ -n "$CS" ]]; then printf '%s' "$CS" | put_secret servicebus-connection && echo "  servicebus-connection stored"; fi
  unset CS
fi

say "redis (Azure Managed Redis, Enterprise cluster policy, public endpoint with TLS)"
if try "redis" az redisenterprise create --cluster-name "$REDIS" -g "$RG" --location "$LOC" --sku Balanced_B0 --clustering-policy EnterpriseCluster --output none; then
  note "redis=$REDIS (default database: check with: az redisenterprise database list --cluster-name $REDIS -g $RG)"
  KEY="$(az redisenterprise database list-keys --cluster-name "$REDIS" -g "$RG" --query primaryKey -o tsv 2>/dev/null || true)"
  HOST="$(az redisenterprise show --cluster-name "$REDIS" -g "$RG" --query hostName -o tsv 2>/dev/null || true)"
  if [[ -n "$KEY" && -n "$HOST" ]]; then
    printf 'rediss://:%s@%s:10000/0' "$KEY" "$HOST" | put_secret redis-url && echo "  redis-url stored"
  else
    echo "  could not read the Redis key or host: create the default database and tell me what 'az redisenterprise database list --cluster-name $REDIS -g $RG' says"
  fi
  unset KEY HOST
fi

say "storage account"
if try "storage account" az storage account create -g "$RG" -n "$SA" --location "$LOC" --sku Standard_GRS --kind StorageV2 --allow-blob-public-access false --allow-shared-key-access false --min-tls-version TLS1_2 --https-only true --output none; then
  SA_ID="$(az storage account show -g "$RG" -n "$SA" --query id -o tsv)"
  if [[ -n "$ME_OID" ]]; then
    try "Storage Blob Data Contributor (you)" az role assignment create --assignee-object-id "$ME_OID" --assignee-principal-type User --role "Storage Blob Data Contributor" --scope "$SA_ID" --output none
    sleep 30
  fi
  for c in tenant-exports neo4j-backups; do
    try "container $c" az storage container create --account-name "$SA" --name "$c" --auth-mode login --output none
  done
  try "export immutability" az storage container immutability-policy create --account-name "$SA" --container-name tenant-exports --period 30 --output none \
    || echo "  set a 30-day time-based retention on tenant-exports in the portal if this failed"
  note "storage=$SA"
fi

say "container apps environment (no VNet, no log destination)"
try "container apps environment" az containerapp env create -g "$RG" -n "$CAE" --location "$LOC" --logs-destination none --enable-workload-profiles --output none && note "container_apps_env=$CAE"

say "entra app registrations"
STAFF_APP_ID="$(az ad app create --display-name "DIUCS Staff (pilot)" --sign-in-audience AzureADMultipleOrgs --web-redirect-uris "https://${STAFF_HOST}/api/bff/auth/entra/callback" --enable-id-token-issuance true --query appId -o tsv 2>/dev/null || true)"
if [[ -n "$STAFF_APP_ID" ]]; then
  az ad sp create --id "$STAFF_APP_ID" --only-show-errors >/dev/null 2>&1 || true
  az ad app update --id "$STAFF_APP_ID" --set groupMembershipClaims=SecurityGroup >/dev/null 2>&1 || FAILED+=("staff app group claims")
  az ad app credential reset --id "$STAFF_APP_ID" --display-name diucs-bff --years 1 --query password -o tsv 2>/dev/null | tr -d '\n' | put_secret entra-staff-client-secret && echo "  staff client secret stored"
  note "staff_app_id=$STAFF_APP_ID staff_host=$STAFF_HOST"
else
  FAILED+=("staff app registration")
fi
OPS_APP_ID="$(az ad app create --display-name "DIUCS Operator Console (pilot)" --sign-in-audience AzureADMyOrg --web-redirect-uris "https://${OPS_HOST}/api/bff/platform/auth/callback" --enable-id-token-issuance true --query appId -o tsv 2>/dev/null || true)"
if [[ -n "$OPS_APP_ID" ]]; then
  az ad sp create --id "$OPS_APP_ID" --only-show-errors >/dev/null 2>&1 || true
  az ad app update --id "$OPS_APP_ID" --set groupMembershipClaims=SecurityGroup >/dev/null 2>&1 || FAILED+=("operator app group claims")
  az ad app credential reset --id "$OPS_APP_ID" --display-name diucs-operator --years 1 --query password -o tsv 2>/dev/null | tr -d '\n' | put_secret entra-operator-client-secret && echo "  operator client secret stored"
  note "operator_app_id=$OPS_APP_ID operator_host=$OPS_HOST operator_directory_id=$(az account show --query tenantId -o tsv)"
else
  FAILED+=("operator app registration")
fi
if [[ "$STAFF_HOST" == *.invalid || "$OPS_HOST" == *.invalid ]]; then
  echo
  echo "Placeholder hostnames were used. When you have the real ones, set the redirect URIs:"
  echo "  az ad app update --id $STAFF_APP_ID --web-redirect-uris https://<staff host>/api/bff/auth/entra/callback"
  echo "  az ad app update --id $OPS_APP_ID --web-redirect-uris https://<operator host>/api/bff/platform/auth/callback"
fi

say "still to do by hand"
cat <<'TODO'
  - Neo4j Aura: create the instance (UK region); then store its password:  printf '%s' '<password>' | az keyvault secret set --vault-name <kv> --name neo4j-password --file /dev/stdin --encoding utf-8
  - Cloudflare: zone, DNS, custom hostnames, WAF, origin lock; the origin secret is the Key Vault secret edge-origin
  - Twilio: account, a subaccount and number per tenant, a verified email domain per tenant (secrets at onboarding)
  - OS Places API key:  printf '%s' '<key>' | az keyvault secret set --vault-name <kv> --name os-places-api-key --file /dev/stdin --encoding utf-8
  - Container apps (api, web, workers, collector) are created at deploy time, when there are images.
TODO

say "result"
if ((${#FAILED[@]})); then
  echo "These steps failed (send me the text printed above for each):"
  printf '  - %s\n' "${FAILED[@]}"
  echo "Non-secret outputs so far are in $OUT"
  exit 1
fi
echo "All steps ran. Non-secret outputs are in $OUT: send me that file (it holds no secrets)."
