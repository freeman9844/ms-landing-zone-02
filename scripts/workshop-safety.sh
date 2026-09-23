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
  # 이름별 규칙 모음이 하나씩 있고 모두 Allow인 전환 준비 상태인지 확인합니다. 규칙을 바꾸지는 않습니다.
  # 규칙의 세부 내용과 실제 통신 성공까지 이 함수 하나로 증명하지 않으며 별도 Firewall 검증을 수행합니다.
  jq -e '
    .ruleCollections as $rules | ($rules | type == "array") and
    all(["management", "lab-http", "egress-check"][];
      . as $name | [$rules[] | select(.name == $name)] |
      length == 1 and .[0].action.type == "Allow")
  ' <<< "$collections" >/dev/null || { fail "Required Firewall collections must be uniquely Allow."; return 1; }
  # $(firewall_ready_ip)에서 사용할 순수 IP만 stdout으로 반환합니다. 오류 설명은 stderr로 보냅니다.
  printf '%s\n' "$ip"
}

# 첫 Subnet 전환 전에도 두 테이블의 왕복 /16·기본 /0 및 원격 VNet ID로 찾은 네 방향 전달 허용을 검사합니다.
assert_route_tables_ready() {
  local ip="$1" zone rg remote table data local_zone remote_zone local_rg remote_rg local_vnet remote_id peering_name peering
  assert_ipv4_in_subnet "$ip" 10.0.2.0/26 || return 1
  for zone in spokea spokeb; do
    # 목적지 접두사는 상대 Spoke입니다. next hop IP는 두 방향 모두 같은 Firewall이어야 합니다.
    case "$zone" in
      spokea) rg="$RG_SPOKEA"; remote=10.20.0.0/16 ;;
      spokeb) rg="$RG_SPOKEB"; remote=10.10.0.0/16 ;;
    esac
    assert_owned_rg "$rg" || return 1
    table="rt-lzbegin-$zone-$RUN_ID"
    data=$(az network route-table show -g "$rg" -n "$table" -o json --subscription "$SUBSCRIPTION_ID") || return 1
    # 이 실습의 두 경로만 허용합니다. 운영 경로가 섞인 테이블을 실습 대상으로 간주하지 않습니다.
    jq -e --arg id "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$rg/providers/Microsoft.Network/routeTables/$table" \
      --arg remote "$remote" --arg ip "$ip" '
      (.id | ascii_downcase) == ($id | ascii_downcase) and (.routes | type == "array" and length == 2) and
      any(.routes[]; .name == "to-other-spoke" and .addressPrefix == $remote and
        .nextHopType == "VirtualAppliance" and .nextHopIpAddress == $ip) and
      any(.routes[]; .name == "to-internet" and .addressPrefix == "0.0.0.0/0" and
        .nextHopType == "VirtualAppliance" and .nextHopIpAddress == $ip)
    ' <<< "$data" >/dev/null || { fail "Incomplete or unexpected routes: $table"; return 1; }
    for local_zone in hub "$zone"; do
      if [[ "$local_zone" == hub ]]; then
        local_rg="$RG_HUB"; remote_zone="$zone"; remote_rg="$rg"
      else
        local_rg="$rg"; remote_zone=hub; remote_rg="$RG_HUB"
      fi
      local_vnet="vnet-lzbegin-$local_zone-$RUN_ID"
      remote_id="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$remote_rg/providers/Microsoft.Network/virtualNetworks/vnet-lzbegin-$remote_zone-$RUN_ID"
      peering_name=$(peering_name_for_remote "$local_rg" "$local_vnet" "$remote_id") || return 1
      peering=$(az network vnet peering show -g "$local_rg" --vnet-name "$local_vnet" \
        -n "$peering_name" -o json --subscription "$SUBSCRIPTION_ID") || return 1
      # Connected와 전달 허용뿐 아니라 상대 VNet ID도 대조합니다. Peering만으로 경로가 생기지는 않습니다.
      jq -e --arg remote "$remote_id" '
        .peeringState == "Connected" and .allowForwardedTraffic == true and
        .allowVirtualNetworkAccess == true and
        (.remoteVirtualNetwork.id | ascii_downcase) == ($remote | ascii_downcase)
      ' <<< "$peering" >/dev/null || { fail "Peering is not ready for forwarded traffic."; return 1; }
    done
  done
}

# detach → nat → pip의 현재 참조 관계를 검사합니다. 삭제나 확인 입력은 교재의 개별 블록에 남깁니다.
assert_spoke_nat_removal() {
  local zone="${1:-}" stage="${2:-}" rg base nat_id pip_id subnet_id subnet nat pip nats
  # stage는 교재에서 실행할 다음 변경입니다: detach=Subnet 분리, nat=NAT 삭제, pip=Public IP 삭제.
  # Hub를 허용하지 않아 관리 VM의 NAT나 Firewall Public IP를 이 절차로 제거하지 못하게 합니다.
  case "$zone" in
    spokea) rg="$RG_SPOKEA" ;;
    spokeb) rg="$RG_SPOKEB" ;;
    *) fail "Only an exact Spoke may lose its NAT."; return 1 ;;
  esac
  [[ "$stage" == detach || "$stage" == nat || "$stage" == pip ]] ||
    { fail "Unknown NAT removal stage."; return 1; }
  assert_owned_rg "$rg" || return 1
  base="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$rg/providers/Microsoft.Network"
  nat_id="$base/natGateways/nat-lzbegin-$zone-$RUN_ID"
  pip_id="$base/publicIPAddresses/pip-lzbegin-$zone-$RUN_ID"
  subnet_id="$base/virtualNetworks/vnet-lzbegin-$zone-$RUN_ID/subnets/snet-workload"
  subnet=$(az network vnet subnet show -g "$rg" --vnet-name "vnet-lzbegin-$zone-$RUN_ID" \
    -n snet-workload -o json --subscription "$SUBSCRIPTION_ID") || return 1
  # 모든 단계에서 Firewall 경로 연결은 남아 있어야 합니다. NAT 삭제 단계부터는 Subnet이 분리된 상태여야 합니다.
  jq -e --arg id "$subnet_id" --arg nat "$nat_id" --arg stage "$stage" \
    --arg rt "$base/routeTables/rt-lzbegin-$zone-$RUN_ID" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and
    (.routeTable.id | ascii_downcase) == ($rt | ascii_downcase) and
    (if $stage == "detach" then (.natGateway.id | ascii_downcase) == ($nat | ascii_downcase)
     else .natGateway == null end)
  ' <<< "$subnet" >/dev/null || { fail "Unexpected subnet/NAT/route-table association."; return 1; }
  if [[ "$stage" == pip ]]; then
    # list 응답이 실제 배열인 경우만 부재로 인정합니다. show의 404/권한 오류를 서로 혼동하지 않습니다.
    nats=$(az network nat gateway list -g "$rg" -o json --subscription "$SUBSCRIPTION_ID") || return 1
    jq -e --arg id "$nat_id" --arg name "nat-lzbegin-$zone-$RUN_ID" '
      type == "array" and all(.[];
        (.id | type == "string" and length > 0) and (.name | type == "string" and length > 0) and
        (.id | ascii_downcase) != ($id | ascii_downcase) and
        (.name | ascii_downcase) != ($name | ascii_downcase))
    ' <<< "$nats" >/dev/null || { fail "NAT deletion has not been confirmed."; return 1; }
  else
    nat=$(az network nat gateway show -g "$rg" -n "nat-lzbegin-$zone-$RUN_ID" -o json \
      --subscription "$SUBSCRIPTION_ID") || return 1
    # 실습용 IP 하나와 예상 Subnet만 참조해야 합니다. 다른 연결이 있으면 함께 끊지 않도록 중단합니다.
    jq -e --arg id "$nat_id" --arg pip "$pip_id" --arg subnet "$subnet_id" --arg stage "$stage" --arg run "$RUN_ID" '
      (.id | ascii_downcase) == ($id | ascii_downcase) and .tags.runId == $run and .tags.workshop == "lz-beginner" and
      .tags.environment == "lab" and .tags.managedBy == "workshop" and
      (.publicIpAddresses | type == "array" and length == 1) and
      (.publicIpAddresses[0].id | ascii_downcase) == ($pip | ascii_downcase) and
      (if $stage == "detach" then (.subnets | type == "array" and length == 1) and
         (.subnets[0].id | ascii_downcase) == ($subnet | ascii_downcase)
       else (.subnets == null or (.subnets | type == "array" and length == 0)) end)
    ' <<< "$nat" >/dev/null || { fail "Unexpected NAT ownership or references."; return 1; }
  fi
  pip=$(az network public-ip show -g "$rg" -n "pip-lzbegin-$zone-$RUN_ID" -o json \
    --subscription "$SUBSCRIPTION_ID") || return 1
  # 마지막 Public IP 삭제 전에는 NAT와 NIC 어느 쪽에서도 참조하지 않는지 확인합니다.
  # 통신 검증과 사용자 확인 입력은 호출하는 교재 블록의 책임이며, 이 함수는 삭제를 수행하지 않습니다.
  jq -e --arg id "$pip_id" --arg run "$RUN_ID" --arg stage "$stage" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and .tags.runId == $run and .tags.workshop == "lz-beginner" and
    .tags.environment == "lab" and .tags.managedBy == "workshop" and
    ($stage != "pip" or (.natGateway == null and .ipConfiguration == null))
  ' <<< "$pip" >/dev/null || { fail "Unexpected public IP ownership or references."; return 1; }
}
