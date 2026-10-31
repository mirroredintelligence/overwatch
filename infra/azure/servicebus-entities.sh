#!/usr/bin/env bash
# Creates the Service Bus queues, topics and subscriptions of infra/servicebus-config.json in an Azure
# Service Bus namespace, so the cloud matches what the tests run against (the emulator reads the same file).
#
#   bash infra/azure/servicebus-entities.sh <resource-group> <namespace-name>
#
# It uses the ARM REST API through `az rest`, so the property names are the ones in the config (the first
# letter lower-cased); a property with an empty value (ForwardTo and the like) is left out. Idempotent: a
# second run updates what exists. Run it again whenever the config changes (the `codes.dispatch` topic is
# being added to the config). It does not create filters/rules: subscriptions get the default (all
# messages); the tenant filters are applied by the consumers (see docs/delivery/deployment-plan.md).
# Nothing here has been run by the agent.
set -euo pipefail

RG="${1:?resource group}"
NS="${2:?namespace name}"
CONFIG="${CONFIG:-infra/servicebus-config.json}"
API="2021-11-01"

command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
SUB="$(az account show --query id -o tsv)"
BASE="https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.ServiceBus/namespaces/$NS"

# A config entry's Properties as an ARM `properties` body: lower-case first letter, empty strings dropped.
props() {
  jq -c 'with_entries(select(.value != "")) | with_entries(.key |= (.[0:1] | ascii_downcase) + .[1:]) | {properties: .}'
}

put() {
  local url="$1" body="$2"
  az rest --method put --url "$url?api-version=$API" --body "$body" --output none
}

NS_JSON=".UserConfig.Namespaces[0]"

echo "queues:"
jq -r "$NS_JSON.Queues[].Name" "$CONFIG" | while read -r q; do
  echo "  $q"
  body="$(jq -c --arg q "$q" "$NS_JSON.Queues[] | select(.Name == \$q) | .Properties" "$CONFIG" | props)"
  put "$BASE/queues/$q" "$body"
done

echo "topics and subscriptions:"
jq -r "$NS_JSON.Topics[].Name" "$CONFIG" | while read -r t; do
  echo "  $t"
  body="$(jq -c --arg t "$t" "$NS_JSON.Topics[] | select(.Name == \$t) | (.Properties // {})" "$CONFIG" | props)"
  put "$BASE/topics/$t" "$body"
  jq -r --arg t "$t" "$NS_JSON.Topics[] | select(.Name == \$t) | (.Subscriptions // [])[].Name" "$CONFIG" | while read -r s; do
    echo "    $s"
    sbody="$(jq -c --arg t "$t" --arg s "$s" "$NS_JSON.Topics[] | select(.Name == \$t) | .Subscriptions[] | select(.Name == \$s) | .Properties" "$CONFIG" | props)"
    put "$BASE/topics/$t/subscriptions/$s" "$sbody"
  done
done

echo "done"
