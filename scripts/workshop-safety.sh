#!/usr/bin/env bash
# 모듈 공통 준비에서 workshop-common.sh 다음에 읽습니다. 아래 함수는 조회·검사만 합니다.
# 분리된 작업 사이의 예전 성공을 저장하지 않고, 호출할 때마다 현재 의존 관계를 확인합니다.

# Azure 응답의 ID 표기는 달라도 전체 구독·RG·종류·이름이 같아야 합니다. 원본 값은 변경하지 않습니다.
assert_resource_id() {
  local actual="${1:-}" expected="${2:-}"
  [[ -n "$actual" && -n "$expected" && "${actual,,}" == "${expected,,}" ]] ||
    { fail "Resource ID mismatch: expected=$expected actual=$actual"; return 1; }
}

peering_name_for_remote() {
  local local_rg="${1:-}" local_vnet="${2:-}" remote_id="${3:-}" peerings
  [[ -n "$local_rg" && -n "$local_vnet" && -n "$remote_id" ]] ||
    { fail "Peering lookup requires local RG, local VNet, and remote VNet ID."; return 1; }
  peerings=$(az network vnet peering list -g "$local_rg" --vnet-name "$local_vnet" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -er --arg remote "$remote_id" '
    [.[] | select(
      (.remoteVirtualNetwork.id | type == "string") and
      ((.remoteVirtualNetwork.id | ascii_downcase) == ($remote | ascii_downcase))
    )]
    | if length == 1 and ((.[0].name | type == "string") and (.[0].name | length > 0))
      then .[0].name
      else error("Expected exactly one peering for remote VNet")
      end
  ' <<< "$peerings" || {
    fail "Expected exactly one peering to remote VNet: $remote_id"
    return 1
  }
}

peering_for_forwarding() {
  local local_rg="$1" local_vnet="$2" remote_rg="$3" remote_vnet="$4" remote_id name current
  remote_id=$(az network vnet show -g "$remote_rg" -n "$remote_vnet" \
    --query id -o tsv --subscription "$SUBSCRIPTION_ID") || return 1
  assert_resource_id "$remote_id" \
    "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$remote_rg/providers/Microsoft.Network/virtualNetworks/$remote_vnet" || return 1
  name=$(peering_name_for_remote "$local_rg" "$local_vnet" "$remote_id") || return 1
  current=$(az network vnet peering show -g "$local_rg" --vnet-name "$local_vnet" \
    -n "$name" -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "$remote_id" '.peeringState == "Connected" and
    (.remoteVirtualNetwork.id | ascii_downcase) == ($id | ascii_downcase)' <<< "$current" >/dev/null ||
    { fail "Peering is not connected to the expected remote VNet."; return 1; }
  printf '%s\n' "$name"
}

assert_peering_forwarded() {
  local local_rg="$1" local_vnet="$2" remote_rg="$3" remote_vnet="$4" name="$5" current
  current=$(az network vnet peering show -g "$local_rg" --vnet-name "$local_vnet" \
    -n "$name" -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$remote_rg/providers/Microsoft.Network/virtualNetworks/$remote_vnet" '
    .peeringState == "Connected" and .allowForwardedTraffic == true and
    (.remoteVirtualNetwork.id | ascii_downcase) == ($id | ascii_downcase)
  ' <<< "$current" >/dev/null ||
    { fail "Peering forwarding did not become active."; return 1; }
  printf 'PASS: %s/%s -> %s\n' "$local_rg" "$local_vnet" "$remote_vnet"
}

assert_routing_creation_ready() {
  local manager groups members zone group expected existing
  assert_enforced_connectivity || return 1
  manager=$(az network manager show -g "$RG_HUB" -n "$AVNM" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "$AVNM_ID" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and
    .provisioningState == "Succeeded" and
    (.networkManagerScopeAccesses | sort) == (["Connectivity","SecurityAdmin","Routing"] | sort)
  ' <<< "$manager" >/dev/null || { fail "AVNM Routing scope is not ready."; return 1; }
  [[ "${ROUTE_GROUP_A_ID,,}" != "${ROUTE_GROUP_B_ID,,}" ]] ||
    { fail "Routing target groups must differ."; return 1; }
  for zone in spokea spokeb; do
    if [[ "$zone" == spokea ]]; then group="$ROUTE_GROUP_A_ID"; expected="$RG_SPOKEA"
    else group="$ROUTE_GROUP_B_ID"; expected="$RG_SPOKEB"; fi
    groups=$(az network manager group show --ids "$group" \
      -o json --subscription "$SUBSCRIPTION_ID") || return 1
    jq -e --arg id "$group" '(.id | ascii_downcase) == ($id | ascii_downcase) and
      .provisioningState == "Succeeded"' <<< "$groups" >/dev/null ||
      { fail "Routing group not ready: $zone"; return 1; }
    members=$(az network manager group static-member list \
      --network-group "ng-lzbegin-route-$zone-$RUN_ID" --network-manager "$AVNM" \
      --resource-group "$RG_HUB" -o json --subscription "$SUBSCRIPTION_ID") || return 1
    jq -e --arg id "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$expected/providers/Microsoft.Network/virtualNetworks/vnet-lzbegin-$zone-$RUN_ID" '
      type == "array" and length == 1 and .[0].provisioningState == "Succeeded" and
      (.[0].resourceId | ascii_downcase) == ($id | ascii_downcase)
    ' <<< "$members" >/dev/null || { fail "Unexpected routing group member: $zone"; return 1; }
  done
  existing=$(az network manager routing-config list -g "$RG_HUB" --manager-name "$AVNM" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e 'type == "array" and length == 0' <<< "$existing" >/dev/null ||
    { fail "Routing configuration already exists; inspect before changing it."; return 1; }
}

assert_routing_creation_result() {
  jq -e --arg id "$AVNM_ID/routingConfigurations/rc-lzbegin-spokes-$RUN_ID" '
    (.id | ascii_downcase) == ($id | ascii_downcase)
  ' <<< "$1" >/dev/null || { fail "Unexpected routing configuration ID."; return 1; }
}

assert_routing_collection_result() {
  local id="$AVNM_ID/routingConfigurations/rc-lzbegin-spokes-$RUN_ID/ruleCollections/$2"
  jq -e --arg id "$id" --arg group "$3" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and
    (.appliesTo | type == "array" and length == 1) and
    (.appliesTo[0].networkGroupId | ascii_downcase) == ($group | ascii_downcase)
  ' <<< "$1" >/dev/null || { fail "Unexpected routing collection or target: $2"; return 1; }
}

assert_routing_rule_result() {
  local id="$AVNM_ID/routingConfigurations/rc-lzbegin-spokes-$RUN_ID/ruleCollections/$2/rules/$3"
  jq -e --arg id "$id" --arg prefix "$4" --arg ip "$5" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and
    .destination.type == "AddressPrefix" and .destination.destinationAddress == $prefix and
    .nextHop.nextHopType == "VirtualAppliance" and .nextHop.nextHopAddress == $ip
  ' <<< "$1" >/dev/null || { fail "Unexpected routing rule: $2/$3"; return 1; }
}

assert_unattached_workload_subnets() {
  local zone rg subnet
  for zone in spokea spokeb; do
    if [[ "$zone" == spokea ]]; then rg="$RG_SPOKEA"; else rg="$RG_SPOKEB"; fi
    assert_owned_rg "$rg" || return 1
    subnet=$(az network vnet subnet show -g "$rg" \
      --vnet-name "vnet-lzbegin-$zone-$RUN_ID" -n snet-workload \
      -o json --subscription "$SUBSCRIPTION_ID") || return 1
    jq -e --arg id "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$rg/providers/Microsoft.Network/virtualNetworks/vnet-lzbegin-$zone-$RUN_ID/subnets/snet-workload" '
      (.id | ascii_downcase) == ($id | ascii_downcase) and
      .routeTable == null and .natGateway == null
    ' <<< "$subnet" >/dev/null ||
      { fail "Existing route table or NAT on workload subnet: $zone"; return 1; }
  done
}

# AVNM이 만든 네 Peering을 실제 remote ID로 확인합니다. Enforced 전후에 같은 검사를 사용합니다.
assert_forwarded_peerings() {
  local zone rg vnet expected peerings hub_id a_id b_id
  hub_id="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_HUB/providers/Microsoft.Network/virtualNetworks/vnet-lzbegin-hub-$RUN_ID"
  a_id="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_SPOKEA/providers/Microsoft.Network/virtualNetworks/vnet-lzbegin-spokea-$RUN_ID"
  b_id="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_SPOKEB/providers/Microsoft.Network/virtualNetworks/vnet-lzbegin-spokeb-$RUN_ID"
  for zone in hub spokea spokeb; do
    case "$zone" in
      hub) rg="$RG_HUB"; expected=$(jq -cn --arg a "$a_id" --arg b "$b_id" '[$a,$b]') ;;
      spokea) rg="$RG_SPOKEA"; expected=$(jq -cn --arg hub "$hub_id" '[$hub]') ;;
      spokeb) rg="$RG_SPOKEB"; expected=$(jq -cn --arg hub "$hub_id" '[$hub]') ;;
    esac
    assert_owned_rg "$rg" || return 1
    vnet="vnet-lzbegin-$zone-$RUN_ID"
    peerings=$(az network vnet peering list -g "$rg" --vnet-name "$vnet" \
      -o json --subscription "$SUBSCRIPTION_ID") || return 1
    jq -e --argjson expected "$expected" '
      type == "array" and length == ($expected | length) and
      all(.[]; .peeringState == "Connected" and .allowForwardedTraffic == true and
        .allowVirtualNetworkAccess == true and (.remoteVirtualNetwork.id | type == "string")) and
      ([.[].remoteVirtualNetwork.id | ascii_downcase] | sort) ==
      ([$expected[] | ascii_downcase] | sort)
    ' <<< "$peerings" >/dev/null ||
      { fail "Unexpected or non-forwarding AVNM peerings: $zone"; return 1; }
  done
}

assert_connectivity_config_ready() {
  local config expected_enforcement="${1:-}"
  config=$(az network manager connect-config show -g "$RG_HUB" \
    --network-manager-name "$AVNM" --configuration-name "$CONNECTIVITY_CONFIG" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "$CONNECTIVITY_CONFIG_ID" --arg enforcement "$expected_enforcement" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and
    .provisioningState == "Succeeded" and .connectivityTopology == "HubAndSpoke" and
    ($enforcement == "" or
      (.connectivityCapabilities.peeringEnforcement == $enforcement and
       .connectivityCapabilities.connectedGroupAddressOverlap == "Allowed" and
       .connectivityCapabilities.connectedGroupPrivateEndpointsScale == "Standard"))
  ' <<< "$config" >/dev/null ||
    { fail "Connectivity configuration is not ready or peering enforcement is not saved."; return 1; }
}

# 새 Connectivity 목표 상태와 Spoke의 실제 적용 상태를 별도로 확인합니다.
assert_enforced_connectivity() {
  local config status effective zone rg vnet hub_id vnet_id
  assert_owned_rg "$RG_HUB" || return 1
  hub_id="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_HUB/providers/Microsoft.Network/virtualNetworks/vnet-lzbegin-hub-$RUN_ID"
  config=$(az network manager connect-config show -g "$RG_HUB" \
    --network-manager-name "$AVNM" --configuration-name "$CONNECTIVITY_CONFIG" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "$CONNECTIVITY_CONFIG_ID" --arg hub "$hub_id" --arg group "$NETWORK_GROUP_ID" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and
    .provisioningState == "Succeeded" and .connectivityTopology == "HubAndSpoke" and
    (.deleteExistingPeering == false or .deleteExistingPeering == "False") and
    (.isGlobal == false or .isGlobal == "False") and
    (.hubs | type == "array" and length == 1) and
    (.hubs[0].resourceId | ascii_downcase) == ($hub | ascii_downcase) and
    (.appliesToGroups | type == "array" and length == 1) and
    (.appliesToGroups[0].networkGroupId | ascii_downcase) == ($group | ascii_downcase) and
    .appliesToGroups[0].groupConnectivity == "None" and
    (.appliesToGroups[0].useHubGateway == false or .appliesToGroups[0].useHubGateway == "False") and
    .connectivityCapabilities.peeringEnforcement == "Enforced" and
    .connectivityCapabilities.connectedGroupAddressOverlap == "Allowed" and
    .connectivityCapabilities.connectedGroupPrivateEndpointsScale == "Standard"
  ' <<< "$config" >/dev/null || { fail "Unexpected or unenforced Connectivity Configuration."; return 1; }
  status=$(az network manager list-deploy-status -g "$RG_HUB" --network-manager-name "$AVNM" \
    --deployment-types Connectivity --regions "$LOCATION" -o json \
    --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "$CONNECTIVITY_CONFIG_ID" --arg loc "$LOCATION" '
    if type == "array" then .
    elif type == "object" and (.skipToken == null or .skipToken == "") and (.value | type == "array") then .value
    else error("Invalid deployment status") end |
    [.[] | select(.deploymentType == "Connectivity" and .region == $loc)] |
    if length == 0 then error("Missing Connectivity deployment") else sort_by(.commitTime) | last end |
    .deploymentStatus == "Deployed" and
    (.configurationIds | type == "array" and length == 1) and
    (.configurationIds[0] | ascii_downcase) == ($id | ascii_downcase)
  ' <<< "$status" >/dev/null || { fail "Connectivity enforcement deployment is not complete."; return 1; }
  for zone in spokea spokeb; do
    if [[ "$zone" == spokea ]]; then rg="$RG_SPOKEA"; else rg="$RG_SPOKEB"; fi
    assert_owned_rg "$rg" || return 1
    vnet="vnet-lzbegin-$zone-$RUN_ID"
    vnet_id="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$rg/providers/Microsoft.Network/virtualNetworks/$vnet"
    effective=$(az rest --method post \
      --url "$vnet_id/listNetworkManagerEffectiveConnectivityConfigurations?api-version=2025-05-01" \
      --body '{}' -o json --subscription "$SUBSCRIPTION_ID") || return 1
    jq -e --arg id "$CONNECTIVITY_CONFIG_ID" '
      (.skipToken == null or .skipToken == "") and
      (.value | type == "array" and length == 1) and
      (.value[0].id | ascii_downcase) == ($id | ascii_downcase) and
      .value[0].properties.provisioningState == "Succeeded" and
      .value[0].properties.connectivityCapabilities.peeringEnforcement == "Enforced"
    ' <<< "$effective" >/dev/null ||
      { fail "Enforced Connectivity is not effective on $zone."; return 1; }
  done
  assert_forwarded_peerings || return 1
  printf 'PASS: Enforced Connectivity is effective on both spokes; four forwarded peerings are connected.\n'
}

assert_security_admin_undeployed() {
  local status
  status=$(az rest --method post \
    --url "$AVNM_ID/listDeploymentStatus?api-version=2025-05-01" \
    --body "$(jq -cn --arg loc "$LOCATION" '{deploymentTypes:["SecurityAdmin"],regions:[$loc]}')" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg loc "$LOCATION" '
    if type == "array" then .
    elif type == "object" and (.skipToken == null or .skipToken == "") and (.value | type == "array")
      then .value
    else error("Incomplete Security Admin deployment status") end |
    [.[] | select(.deploymentType == "SecurityAdmin" and .region == $loc)] |
    if length == 0 then error("Missing Security Admin deployment") else sort_by(.commitTime) | last end |
    .deploymentStatus == "Deployed" and .configurationIds == []
  ' <<< "$status" >/dev/null ||
    { fail "Security Admin undeployment is not complete; do not delete deployed rules."; return 1; }
}

# 임의의 사설 IP가 아니라 지정한 Subnet 안의 IPv4 호스트 주소인지 확인합니다.
# 네트워크/브로드캐스트 주소도 거부합니다. Azure의 모든 주소 예약·할당 규칙을 재현하는 검사는 아닙니다.
assert_ipv4_in_subnet() {
  python3 - "$1" "$2" <<'PY'
import ipaddress
import sys
try:
    address = ipaddress.IPv4Address(sys.argv[1])
    network = ipaddress.IPv4Network(sys.argv[2])
    if address not in network or address in (network.network_address, network.broadcast_address):
        raise ValueError("address outside expected host range")
except ValueError as error:
    sys.exit(f"ERROR: invalid workshop IP: {error}")
PY
}

firewall_ready_ip() {
  local fw ip id law diagnostic collections
  local base="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_HUB/providers"
  # 반환할 IP는 뒤의 UDR next hop에 들어갑니다. 먼저 이번 Firewall과 지정 정책의 연결을 검증합니다.
  assert_owned_rg "$RG_HUB" || return 1
  fw=$(az network firewall show -g "$RG_HUB" -n "fw-lzbegin-$RUN_ID" -o json \
    --subscription "$SUBSCRIPTION_ID") || return 1
  id="$base/Microsoft.Network/azureFirewalls/fw-lzbegin-$RUN_ID"
  jq -e --arg id "$id" --arg policy "$base/Microsoft.Network/firewallPolicies/fwpol-lzbegin-$RUN_ID" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and .provisioningState == "Succeeded" and
    (.firewallPolicy.id | ascii_downcase) == ($policy | ascii_downcase) and
    (.ipConfigurations[0].privateIPAddress | type == "string" and length > 0)
  ' <<< "$fw" >/dev/null || { fail "Firewall is not ready or has an unexpected policy/ID."; return 1; }
  id=$(jq -er '.id' <<< "$fw") || return 1
  ip=$(jq -er '.ipConfigurations[0].privateIPAddress' <<< "$fw") || return 1
  assert_ipv4_in_subnet "$ip" 10.0.2.0/26 || return 1
  law=$(az monitor log-analytics workspace show -g "$RG_HUB" -n "log-lzbegin-$RUN_ID" \
    --query id -o tsv --subscription "$SUBSCRIPTION_ID") || return 1
  assert_resource_id "$law" "$base/Microsoft.OperationalInsights/workspaces/log-lzbegin-$RUN_ID" || return 1
  # Dedicated는 자원별 로그 테이블을 뜻합니다. workspace만 맞아도 필요한 로그가 꺼져 있으면 실패입니다.
  diagnostic=$(az monitor diagnostic-settings show --name workshop --resource "$id" -o json \
    --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "$law" '
    (.workspaceId | ascii_downcase) == ($id | ascii_downcase) and .logAnalyticsDestinationType == "Dedicated" and
    (.logs | type == "array") and
    any(.logs[]; .category == "AZFWNetworkRule" and .enabled == true) and
    any(.logs[]; .category == "AZFWApplicationRule" and .enabled == true)
  ' <<< "$diagnostic" >/dev/null || { fail "Firewall diagnostics are not ready."; return 1; }
  collections=$(az network firewall policy rule-collection-group show -g "$RG_HUB" \
    --policy-name "fwpol-lzbegin-$RUN_ID" -n workshop -o json --subscription "$SUBSCRIPTION_ID") || return 1
  # 전환 후 Run Command에 필요한 관리 규칙은 주소·프로토콜·포트까지 확인합니다.
  # 실습 HTTP와 인터넷 출구의 실제 통신은 모듈 06에서 별도로 검증합니다.
  jq -e '
    .ruleCollections as $rules | ($rules | type == "array") and
    all(["management", "lab-http", "egress-check"][];
      . as $name | [$rules[] | select(.name == $name)] |
      length == 1 and .[0].action.type == "Allow") and
    ([$rules[] | select(.name == "management")] |
      length == 1 and .[0].priority == 100 and
      (.[0].rules | type == "array" and length == 1) and
      (.[0].rules[0] |
        .name == "azure-management" and .ruleType == "NetworkRule" and
        .ipProtocols == ["TCP"] and
        (.sourceAddresses | type == "array" and length == 2 and
          sort == ["10.10.1.0/24", "10.20.1.0/24"]) and
        .destinationAddresses == ["AzureCloud"] and .destinationPorts == ["443"]))
  ' <<< "$collections" >/dev/null || { fail "Required Firewall collections or management rule are not ready."; return 1; }
  # $(firewall_ready_ip)에서 사용할 순수 IP만 stdout으로 반환합니다. 오류 설명은 stderr로 보냅니다.
  printf '%s\n' "$ip"
}

# AVNM 구성과 적용된 Subnet 테이블을 각각 검사합니다. 관리형 테이블의 이름이나 RG는 가정하지 않습니다.
assert_avnm_routes_ready() {
  local ip="${1:-}" config config_id zone rg group remote collection rule prefix data subnet table_id table
  assert_ipv4_in_subnet "$ip" 10.0.2.0/26 || return 1
  assert_owned_rg "$RG_HUB" || return 1
  config_id="$AVNM_ID/routingConfigurations/rc-lzbegin-spokes-$RUN_ID"
  config=$(az network manager routing-config show -g "$RG_HUB" --manager-name "$AVNM" \
    -n "rc-lzbegin-spokes-$RUN_ID" -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "$config_id" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and
    .provisioningState == "Succeeded" and
    (.routeTableUsageMode == null or .routeTableUsageMode == "ManagedOnly")
  ' <<< "$config" >/dev/null || { fail "Unexpected AVNM routing configuration."; return 1; }
  for zone in spokea spokeb; do
    case "$zone" in
      spokea) rg="$RG_SPOKEA"; group="$ROUTE_GROUP_A_ID"; remote=10.20.0.0/16 ;;
      spokeb) rg="$RG_SPOKEB"; group="$ROUTE_GROUP_B_ID"; remote=10.10.0.0/16 ;;
    esac
    assert_owned_rg "$rg" || return 1
    collection=$(az network manager routing-config rule-collection show \
      -g "$RG_HUB" --manager-name "$AVNM" --config-name "rc-lzbegin-spokes-$RUN_ID" \
      -n "$zone" -o json --subscription "$SUBSCRIPTION_ID") || return 1
    jq -e --arg id "$config_id/ruleCollections/$zone" --arg group "$group" '
      (.id | ascii_downcase) == ($id | ascii_downcase) and
      .provisioningState == "Succeeded" and
      (.appliesTo | type == "array" and length == 1) and
      (.appliesTo[0].networkGroupId | ascii_downcase) == ($group | ascii_downcase)
    ' <<< "$collection" >/dev/null || { fail "Unexpected routing target: $zone"; return 1; }
    for rule in to-other-spoke to-internet; do
      if [[ "$rule" == to-other-spoke ]]; then prefix="$remote"; else prefix=0.0.0.0/0; fi
      data=$(az network manager routing-config rule-collection rule show \
        -g "$RG_HUB" --manager-name "$AVNM" --config-name "rc-lzbegin-spokes-$RUN_ID" \
        --collection-name "$zone" -n "$rule" -o json --subscription "$SUBSCRIPTION_ID") || return 1
      jq -e --arg id "$config_id/ruleCollections/$zone/rules/$rule" \
        --arg prefix "$prefix" --arg ip "$ip" '
        (.id | ascii_downcase) == ($id | ascii_downcase) and
        .provisioningState == "Succeeded" and
        .destination.type == "AddressPrefix" and
        .destination.destinationAddress == $prefix and
        .nextHop.nextHopType == "VirtualAppliance" and
        .nextHop.nextHopAddress == $ip
      ' <<< "$data" >/dev/null || { fail "Unexpected AVNM routing rule: $zone/$rule"; return 1; }
    done
    subnet=$(az network vnet subnet show -g "$rg" --vnet-name "vnet-lzbegin-$zone-$RUN_ID" \
      -n snet-workload -o json --subscription "$SUBSCRIPTION_ID") || return 1
    table_id=$(jq -er --arg id "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$rg/providers/Microsoft.Network/virtualNetworks/vnet-lzbegin-$zone-$RUN_ID/subnets/snet-workload" \
      --arg sub "$SUBSCRIPTION_ID" '
      if (.id | ascii_downcase) != ($id | ascii_downcase) then error("Subnet ID mismatch") else . end
      | .routeTable.id
      | select(type == "string")
      | select(ascii_downcase | startswith("/subscriptions/" + ($sub | ascii_downcase) + "/resourcegroups/"))
      | select(ascii_downcase | test("/providers/microsoft.network/routetables/[^/]+$"))
    ' <<< "$subnet") || { fail "No verified AVNM route table association: $zone"; return 1; }
    table=$(az network route-table show --ids "$table_id" -o json \
      --subscription "$SUBSCRIPTION_ID") || return 1
    jq -e --arg id "$table_id" --arg remote "$remote" --arg ip "$ip" '
      (.id | ascii_downcase) == ($id | ascii_downcase) and
      (.routes | type == "array" and length == 2) and
      all(.routes[]; .provisioningState == "Succeeded" and
        .nextHopType == "VirtualAppliance" and .nextHopIpAddress == $ip) and
      ([.routes[].addressPrefix] | sort) == ([$remote, "0.0.0.0/0"] | sort)
    ' <<< "$table" >/dev/null || { fail "Subnet routes are not deployed: $zone"; return 1; }
  done
}

# Spoke에는 실습용뿐 아니라 다른 NAT/PIP도 없어야 합니다. RG와 Subnet의 실제 상태를 대조합니다.
assert_no_spoke_nat() {
  local zone rg subnet nats pips
  for zone in spokea spokeb; do
    if [[ "$zone" == spokea ]]; then rg="$RG_SPOKEA"; else rg="$RG_SPOKEB"; fi
    assert_owned_rg "$rg" || return 1
    subnet=$(az network vnet subnet show -g "$rg" --vnet-name "vnet-lzbegin-$zone-$RUN_ID" \
      -n snet-workload -o json --subscription "$SUBSCRIPTION_ID") || return 1
    jq -e '.natGateway == null' <<< "$subnet" >/dev/null ||
      { fail "Spoke subnet still has a NAT gateway: $zone"; return 1; }
    nats=$(az network nat gateway list -g "$rg" -o json --subscription "$SUBSCRIPTION_ID") || return 1
    pips=$(az network public-ip list -g "$rg" -o json --subscription "$SUBSCRIPTION_ID") || return 1
    jq -e 'type == "array" and length == 0' <<< "$nats" >/dev/null ||
      { fail "Unexpected Spoke NAT gateway: $zone"; return 1; }
    jq -e 'type == "array" and length == 0' <<< "$pips" >/dev/null ||
      { fail "Unexpected Spoke public IP: $zone"; return 1; }
  done
}

# 단일 보안 구성의 대상 Group, 실제 NIC IP와 규칙 우선순위를 매번 재조회합니다.
assert_admin_rules_ready() {
  local hub="$1" a="$2" b="$3" stage="$4" config id zone group collection rule source destination access priority data count rules expected
  [[ "$stage" == baseline || "$stage" == denied || "$stage" == restored ]] ||
    { fail "Unknown Security Admin stage: $stage"; return 1; }
  assert_ipv4_in_subnet "$hub" 10.0.1.0/24 || return 1
  assert_ipv4_in_subnet "$a" 10.10.1.0/24 || return 1
  assert_ipv4_in_subnet "$b" 10.20.1.0/24 || return 1
  id="$AVNM_ID/securityAdminConfigurations/sc-lzbegin-http-$RUN_ID"
  config=$(az network manager security-admin-config show -g "$RG_HUB" \
    --network-manager-name "$AVNM" --configuration-name "sc-lzbegin-http-$RUN_ID" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "$id" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and .provisioningState == "Succeeded"
  ' <<< "$config" >/dev/null || { fail "Unexpected AVNM Security Admin configuration."; return 1; }
  for zone in spokea spokeb; do
    if [[ "$zone" == spokea ]]; then group="$ROUTE_GROUP_A_ID"; else group="$ROUTE_GROUP_B_ID"; fi
    collection=$(az network manager security-admin-config rule-collection show \
      -g "$RG_HUB" --network-manager-name "$AVNM" --configuration-name "sc-lzbegin-http-$RUN_ID" \
      --rule-collection-name "$zone" -o json --subscription "$SUBSCRIPTION_ID") || return 1
    jq -e --arg id "$id/ruleCollections/$zone" --arg group "$group" '
      (.id | ascii_downcase) == ($id | ascii_downcase) and
      .provisioningState == "Succeeded" and
      (.appliesToGroups | type == "array" and length == 1) and
      (.appliesToGroups[0].networkGroupId | ascii_downcase) == ($group | ascii_downcase)
    ' <<< "$collection" >/dev/null || { fail "Unexpected Security Admin target: $zone"; return 1; }
    rules=$(az network manager security-admin-config rule-collection rule list \
      -g "$RG_HUB" --network-manager-name "$AVNM" --configuration-name "sc-lzbegin-http-$RUN_ID" \
      --rule-collection-name "$zone" -o json --subscription "$SUBSCRIPTION_ID") || return 1
    if [[ "$zone" == spokea ]]; then
      expected=$(jq -nc --arg id "$id/ruleCollections/spokea/rules" --arg stage "$stage" '
        [$id + "/hub-to-a"] +
        (if $stage == "denied" then [$id + "/deny-hub-to-a"] else [] end)')
    else
      expected=$(jq -nc --arg id "$id/ruleCollections/spokeb/rules" \
        '[$id + "/hub-to-b", $id + "/a-to-b"]')
    fi
    jq -e --argjson expected "$expected" '
      type == "array" and
      ([.[] | .id | ascii_downcase] | sort) == ([$expected[] | ascii_downcase] | sort)
    ' <<< "$rules" >/dev/null || { fail "Unexpected Security Admin rule set: $zone"; return 1; }
    if [[ "$zone" == spokea ]]; then
      count=0
      for rule in hub-to-a deny-hub-to-a; do
        [[ "$rule" != deny-hub-to-a || "$stage" == denied ]] || continue
        source="$hub"; destination="$a"
        if [[ "$rule" == deny-hub-to-a ]]; then access=Deny; priority=100
        else access=AlwaysAllow; priority=200; fi
        _assert_admin_rule "$id" "$zone" "$rule" "$source" "$destination" "$access" "$priority" || return 1
        count=$((count + 1))
      done
      [[ "$count" == 1 || "$stage" == denied && "$count" == 2 ]] || return 1
    else
      _assert_admin_rule "$id" "$zone" hub-to-b "$hub" "$b" AlwaysAllow 210 || return 1
      _assert_admin_rule "$id" "$zone" a-to-b "$a" "$b" AlwaysAllow 220 || return 1
    fi
  done
}

_assert_admin_rule() {
  local id="$1" zone="$2" rule="$3" source="$4" destination="$5" access="$6" priority="$7" data
  data=$(az network manager security-admin-config rule-collection rule show \
    -g "$RG_HUB" --network-manager-name "$AVNM" --configuration-name "sc-lzbegin-http-$RUN_ID" \
    --rule-collection-name "$zone" --rule-name "$rule" -o json \
    --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "$id/ruleCollections/$zone/rules/$rule" \
    --arg src "$source" --arg dest "$destination" \
    --arg access "$access" --argjson priority "$priority" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and
    .provisioningState == "Succeeded" and
    .kind == "Custom" and
    .access == $access and .priority == $priority and
    .direction == "Inbound" and .protocol == "Tcp" and
    .sourcePortRanges == ["0-65535"] and
    .destinationPortRanges == ["8080"] and
    (.sources | type == "array" and length == 1) and
    .sources[0].addressPrefixType == "IPPrefix" and
    .sources[0].addressPrefix == ($src + "/32") and
    (.destinations | type == "array" and length == 1) and
    .destinations[0].addressPrefixType == "IPPrefix" and
    .destinations[0].addressPrefix == ($dest + "/32")
  ' <<< "$data" >/dev/null || { fail "Unexpected Security Admin rule: $zone/$rule"; return 1; }
}
