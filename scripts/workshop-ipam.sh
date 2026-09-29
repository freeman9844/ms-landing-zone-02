#!/usr/bin/env bash

# 공유 pool은 운영자 자원입니다. 이 함수는 읽기 전용 검증만 수행합니다.
assert_shared_ipam_pool() {
  local subscription="${SUBSCRIPTION_ID:-}" pool_id response
  [[ "$subscription" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] ||
    { fail "Invalid subscription for shared IPAM pool."; return 1; }
  subscription="${subscription,,}"
  pool_id="/subscriptions/$subscription/resourceGroups/rg-lzbegin-ipam/providers/Microsoft.Network/networkManagers/avnm-lzbegin-ipam/ipamPools/ipam-lzbegin-shared"
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
}
