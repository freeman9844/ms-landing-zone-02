#!/usr/bin/env bash

# Status checks are read-only: a failed inventory or unexpected configuration is never "missing".
foundation_vnet_status() {
  local zone="$1" rg inventory resource name expected_id
  case "$zone" in
    hub) rg="$RG_HUB" ;;
    spokea) rg="$RG_SPOKEA" ;;
    spokeb) rg="$RG_SPOKEB" ;;
    *) fail "Unknown VNet zone: $zone"; return 1 ;;
  esac
  name="vnet-lzbegin-$zone-$RUN_ID"
  expected_id="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$rg/providers/Microsoft.Network/virtualNetworks/$name"
  inventory=$(az network vnet list --resource-group "$rg" -o json --subscription "$SUBSCRIPTION_ID") ||
    { fail "Cannot list VNets in $rg"; return 1; }
  jq -e 'type == "array" and all(.[]; type == "object" and (.name | type == "string"))' \
    <<< "$inventory" >/dev/null || { fail "Malformed VNet inventory in $rg"; return 1; }
  resource=$(jq -c --arg name "${name,,}" '[.[] | select(.name | ascii_downcase == $name)]' \
    <<< "$inventory") || return 1
  if jq -e 'length == 0' <<< "$resource" >/dev/null; then
    printf 'missing\n'
    return 0
  fi
  jq -e --arg id "${expected_id,,}" --arg name "${name,,}" \
    --arg pool "${IPAM_POOL_ID,,}" --arg run "$RUN_ID" --arg location "${LOCATION,,}" '
    length == 1 and (.[0] |
      (.id | type == "string" and ascii_downcase == $id) and
      (.name | ascii_downcase == $name) and
      (.location | type == "string" and ascii_downcase == $location) and
      .provisioningState == "Succeeded" and
      .tags.workshop == "lz-beginner" and .tags.environment == "lab" and
      .tags.runId == $run and .tags.managedBy == "workshop" and
      (.addressSpace.addressPrefixes | type == "array" and length == 1 and
        (.[0] | type == "string" and
          test("^172\\.(2[0-3])\\.(0|16|32|48|64|80|96|112|128|144|160|176|192|208|224|240)\\.0/20$"))) and
      (.addressSpace.ipamPoolPrefixAllocations | type == "array" and length == 1 and
        (.[0].numberOfIpAddresses | tostring) == "4096" and
        ((.[0].pool.id // .[0].id | strings | ascii_downcase) == $pool)) and
      ((.addressSpace.ipamPoolPrefixAllocations[0].allocatedAddressPrefixes // [.addressSpace.addressPrefixes[0]]) ==
        .addressSpace.addressPrefixes))
  ' <<< "$resource" >/dev/null ||
    { fail "Existing VNet $name is not this run's ready IPAM /20 VNet; inspect it, do not overwrite."; return 1; }
  printf 'ready\n'
}

foundation_subnet_status() {
  local zone="$1" subnet="$2" rg inventory resource name expected_id vnet_status size
  case "$zone" in
    hub) rg="$RG_HUB" ;;
    spokea) rg="$RG_SPOKEA" ;;
    spokeb) rg="$RG_SPOKEB" ;;
    *) fail "Unknown Subnet zone: $zone"; return 1 ;;
  esac
  case "$zone/$subnet" in
    hub/snet-management|spokea/snet-workload|spokeb/snet-workload) size=256 ;;
    hub/AzureFirewallSubnet) size=64 ;;
    *) fail "Unexpected Subnet: $zone/$subnet"; return 1 ;;
  esac
  vnet_status=$(foundation_vnet_status "$zone") || return 1
  [[ "$vnet_status" == ready ]] ||
    { fail "Parent VNet must be ready before creating $subnet"; return 1; }
  name="vnet-lzbegin-$zone-$RUN_ID"
  expected_id="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$rg/providers/Microsoft.Network/virtualNetworks/$name/subnets/$subnet"
  inventory=$(az network vnet subnet list --resource-group "$rg" --vnet-name "$name" \
    -o json --subscription "$SUBSCRIPTION_ID") ||
    { fail "Cannot list Subnets in $name"; return 1; }
  jq -e 'type == "array" and all(.[]; type == "object" and (.name | type == "string"))' \
    <<< "$inventory" >/dev/null || { fail "Malformed Subnet inventory in $name"; return 1; }
  resource=$(jq -c --arg name "${subnet,,}" '[.[] | select(.name | ascii_downcase == $name)]' \
    <<< "$inventory") || return 1
  if jq -e 'length == 0' <<< "$resource" >/dev/null; then
    printf 'missing\n'
    return 0
  fi
  jq -e --arg id "${expected_id,,}" --arg name "${subnet,,}" \
    --arg pool "${IPAM_POOL_ID,,}" --arg size "$size" \
    --arg nsg "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$rg/providers/Microsoft.Network/networkSecurityGroups/nsg-lzbegin-$zone-$RUN_ID" '
    length == 1 and (.[0] |
      (.id | type == "string" and ascii_downcase == $id) and
      (.name | ascii_downcase == $name) and .provisioningState == "Succeeded" and
      (.ipamPoolPrefixAllocations | type == "array" and length == 1 and
        (.[0].numberOfIpAddresses | tostring) == $size and
        ((.[0].pool.id // .[0].id | strings | ascii_downcase) == $pool)) and
      (if $size == "64" then
        (.addressPrefix // .addressPrefixes[0] | type == "string" and endswith("/26")) and
        .networkSecurityGroup == null
       else
        (.addressPrefix // .addressPrefixes[0] | type == "string" and endswith("/24")) and
        .defaultOutboundAccess == false and
        (.networkSecurityGroup.id | type == "string" and ascii_downcase == ($nsg | ascii_downcase))
       end) and
      ((.ipamPoolPrefixAllocations[0].allocatedAddressPrefixes // [(.addressPrefix // .addressPrefixes[0])]) ==
        [(.addressPrefix // .addressPrefixes[0])]))
  ' <<< "$resource" >/dev/null ||
    { fail "Existing Subnet $name/$subnet does not match this run's IPAM allocation or settings; do not overwrite."; return 1; }
  printf 'ready\n'
}
