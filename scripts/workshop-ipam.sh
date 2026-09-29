#!/usr/bin/env bash

# A failed read must never leave values from an earlier workshop in the caller's shell.
clear_ipam_cidrs() {
  unset HUB_VNET_CIDR SPOKEA_VNET_CIDR SPOKEB_VNET_CIDR \
    HUB_SUBNET_CIDR SPOKEA_SUBNET_CIDR SPOKEB_SUBNET_CIDR FIREWALL_SUBNET_CIDR \
    RG SUBNET PREFIX VNET VM NSG
}

# Read all seven live resources, validate their identities and allocations, then publish atomically.
load_ipam_cidrs() {
  clear_ipam_cidrs || return 1
  local zone rg vnet name target response envelope result
  local -a values
  local -A vnets subnets
  [[ -n "${RUN_ID:-}" && -n "${SUBSCRIPTION_ID:-}" && -n "${IPAM_POOL_ID:-}" &&
    -n "${RG_HUB:-}" && -n "${RG_SPOKEA:-}" && -n "${RG_SPOKEB:-}" ]] ||
    { fail "Load a workshop state before resolving IPAM CIDRs."; return 1; }
  for zone in hub spokea spokeb; do
    case "$zone" in
      hub) rg="$RG_HUB" ;;
      spokea) rg="$RG_SPOKEA" ;;
      spokeb) rg="$RG_SPOKEB" ;;
    esac
    vnet="vnet-lzbegin-$zone-$RUN_ID"
    response=$(az network vnet show --resource-group "$rg" --name "$vnet" \
      -o json --subscription "$SUBSCRIPTION_ID") ||
      { fail "Cannot read VNet: $vnet"; return 1; }
    vnets[$zone]="$response"
  done
  for target in hub/snet-management hub/AzureFirewallSubnet spokea/snet-workload spokeb/snet-workload; do
    zone="${target%%/*}"
    name="${target#*/}"
    case "$zone" in
      hub) rg="$RG_HUB" ;;
      spokea) rg="$RG_SPOKEA" ;;
      spokeb) rg="$RG_SPOKEB" ;;
    esac
    vnet="vnet-lzbegin-$zone-$RUN_ID"
    response=$(az network vnet subnet show --resource-group "$rg" --vnet-name "$vnet" \
      --name "$name" -o json --subscription "$SUBSCRIPTION_ID") ||
      { fail "Cannot read Subnet: $vnet/$name"; return 1; }
    subnets["$zone/$name"]="$response"
  done
  envelope=$(jq -cn --arg runId "$RUN_ID" --arg subscriptionId "$SUBSCRIPTION_ID" \
    --arg poolId "$IPAM_POOL_ID" \
    --argjson hub "${vnets[hub]}" --argjson spokea "${vnets[spokea]}" \
    --argjson spokeb "${vnets[spokeb]}" \
    --argjson management "${subnets[hub/snet-management]}" \
    --argjson firewall "${subnets[hub/AzureFirewallSubnet]}" \
    --argjson workloadA "${subnets[spokea/snet-workload]}" \
    --argjson workloadB "${subnets[spokeb/snet-workload]}" \
    '{runId:$runId,subscriptionId:$subscriptionId,poolId:$poolId,
      vnets:{hub:$hub,spokea:$spokea,spokeb:$spokeb},
      subnets:{"hub/snet-management":$management,"hub/AzureFirewallSubnet":$firewall,
               "spokea/snet-workload":$workloadA,"spokeb/snet-workload":$workloadB}}') ||
    { fail "Malformed Azure VNet or Subnet JSON."; return 1; }
  result=$(python3 "$(dirname "${BASH_SOURCE[0]}")/check-ipam-cidrs.py" <<< "$envelope") ||
    { fail "Live IPAM CIDR validation failed."; return 1; }
  mapfile -t values <<< "$result"
  [[ ${#values[@]} == 7 ]] || { fail "Expected seven validated IPAM CIDRs."; return 1; }
  HUB_VNET_CIDR="${values[0]}"
  SPOKEA_VNET_CIDR="${values[1]}"
  SPOKEB_VNET_CIDR="${values[2]}"
  HUB_SUBNET_CIDR="${values[3]}"
  SPOKEA_SUBNET_CIDR="${values[4]}"
  SPOKEB_SUBNET_CIDR="${values[5]}"
  FIREWALL_SUBNET_CIDR="${values[6]}"
  export HUB_VNET_CIDR SPOKEA_VNET_CIDR SPOKEB_VNET_CIDR \
    HUB_SUBNET_CIDR SPOKEA_SUBNET_CIDR SPOKEB_SUBNET_CIDR FIREWALL_SUBNET_CIDR
}

# 공유 pool은 운영자 자원입니다. 이 함수는 읽기 전용 검증만 수행합니다.
assert_shared_ipam_pool() {
  local subscription="${SUBSCRIPTION_ID:-}" pool_id manager_id response
  [[ "$subscription" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] ||
    { fail "Invalid subscription for shared IPAM pool."; return 1; }
  subscription="${subscription,,}"
  manager_id="/subscriptions/$subscription/resourceGroups/rg-lzbegin-ipam/providers/Microsoft.Network/networkManagers/avnm-lzbegin-ipam"
  pool_id="$manager_id/ipamPools/ipam-lzbegin-shared"
  [[ -z "${IPAM_POOL_ID:-}" || "${IPAM_POOL_ID,,}" == "${pool_id,,}" ]] ||
    { fail "Shared IPAM pool ID differs from the selected subscription: ${IPAM_POOL_ID}"; return 1; }
  response=$(az rest --method get --url "$pool_id?api-version=2024-05-01" --subscription "$subscription" -o json) ||
    { fail "Cannot read shared IPAM pool $pool_id. Ask the operator to check its existence and your read/use permissions."; return 1; }
  jq -e --arg id "${pool_id,,}" '
    type == "object" and
    (.id | type == "string" and ascii_downcase == $id) and
    (.location | type == "string" and ascii_downcase == "koreacentral") and
    .properties.addressPrefixes == ["172.20.0.0/14"] and
    .properties.provisioningState == "Succeeded"
  ' <<< "$response" >/dev/null 2>&1 ||
    { fail "Shared IPAM pool is missing or does not match the expected ID, region, prefix, or ready state: $pool_id. Ask the operator to inspect it."; return 1; }
  response=$(az rest --method get --url "$manager_id?api-version=2024-05-01" --subscription "$subscription" -o json) ||
    { fail "Cannot read shared IPAM Network Manager $manager_id. Ask the operator to check its existence and your read permissions."; return 1; }
  jq -e --arg id "${manager_id,,}" --arg scope "/subscriptions/$subscription" '
    type == "object" and
    (.id | type == "string" and ascii_downcase == $id) and
    (.location | type == "string" and ascii_downcase == "koreacentral") and
    .properties.provisioningState == "Succeeded" and
    (.properties.networkManagerScopes | type == "object" and
      (.subscriptions | type == "array" and length == 1 and
        (.[0] | type == "string" and ascii_downcase == $scope)) and
      .managementGroups == []) and
    .properties.networkManagerScopeAccesses == ["Connectivity"]
  ' <<< "$response" >/dev/null 2>&1 ||
    { fail "Shared IPAM Network Manager does not match the expected ID, region, subscription scope, Connectivity access, or ready state: $manager_id. Ask the operator to inspect it."; return 1; }
}
