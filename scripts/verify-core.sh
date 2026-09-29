#!/usr/bin/env bash
# Security Admin 기준 상태를 검증합니다. 임시 차단·복구 모드는 이전 실습 진단용입니다.
# 규칙을 직접 변경하지 않습니다. 교재의 해당 변경을 적용한 뒤 실행합니다.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/verify-common.sh"
source "$(dirname "${BASH_SOURCE[0]}")/workshop-safety.sh"
source "$(dirname "${BASH_SOURCE[0]}")/workshop-ipam.sh"
[[ $# == 2 && "$2" =~ ^(baseline|admin-denied|restored)$ ]] ||
  { fail "Usage: verify-core.sh STATE_FILE baseline|admin-denied|restored"; exit 1; }
load_run "$1"
assert_subscription
for rg in "$RG_HUB" "$RG_SPOKEA" "$RG_SPOKEB"; do assert_owned_rg "$rg"; done
load_ipam_cidrs
assert_enforced_connectivity
# baseline과 restored는 같은 정상 통신을 기대합니다. 인수 자체가 규칙을 변경하지는 않습니다.
# Spoke effective configuration과 Hub↔Spoke Peering 집합이 정확해야 보안·HTTP 증거를 해석할 수 있습니다.
hub_vnet_id="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_HUB/providers/Microsoft.Network/virtualNetworks/vnet-lzbegin-hub-$RUN_ID"
spokea_vnet_id="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_SPOKEA/providers/Microsoft.Network/virtualNetworks/vnet-lzbegin-spokea-$RUN_ID"
spokeb_vnet_id="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_SPOKEB/providers/Microsoft.Network/virtualNetworks/vnet-lzbegin-spokeb-$RUN_ID"
for zone in hub spokea spokeb; do
  local_expected='[]'
  zone_context "$zone"
  assert_owned_rg "$RG"
  current_vnet_id="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG/providers/Microsoft.Network/virtualNetworks/$VNET"
  effective=$(az network manager list-effective-connectivity-config \
    --resource-group "$RG" --virtual-network-name "$VNET" -o json \
    --subscription "$SUBSCRIPTION_ID") || exit 1
  jq -e --arg config "$CONNECTIVITY_CONFIG_ID" --arg hub "$hub_vnet_id" \
    --arg group "$NETWORK_GROUP_ID" --arg target "$current_vnet_id" '
    def falsey: . == false or . == "False";
    (.value | type == "array") and
    ($zone == "hub" and (.value | length == 0) or (.value | length == 1)) and
    ($zone == "hub" and (.value | length == 0) or
    (.value[0] as $cfg |
      ($cfg.id | type == "string") and
      (($cfg.id | ascii_downcase) == ($config | ascii_downcase)) and
      $cfg.connectivityTopology == "HubAndSpoke" and
      $cfg.provisioningState == "Succeeded" and
      ($cfg.deleteExistingPeering | falsey) and
      ($cfg.isGlobal | falsey) and
      (($cfg.hubs // []) | length == 1) and
      ($cfg.hubs[0].resourceId | type == "string") and
      (($cfg.hubs[0].resourceId | ascii_downcase) == ($hub | ascii_downcase)) and
      ($cfg.targetVirtualNetwork.id == null or
        (($cfg.targetVirtualNetwork.id | type == "string") and
         (($cfg.targetVirtualNetwork.id | ascii_downcase) == ($target | ascii_downcase)))) and
      (($cfg.appliesToGroups // []) | length == 1) and
      ($cfg.appliesToGroups[0].networkGroupId | type == "string") and
      (($cfg.appliesToGroups[0].networkGroupId | ascii_downcase) == ($group | ascii_downcase)) and
      $cfg.appliesToGroups[0].groupConnectivity == "None" and
      ($cfg.appliesToGroups[0].isGlobal | falsey) and
      ($cfg.appliesToGroups[0].useHubGateway | falsey)
    ))
  ' --arg zone "$zone" <<< "$effective" >/dev/null || { fail "Unexpected effective AVNM connectivity: $zone"; exit 1; }
  case "$zone" in
    hub) local_expected=$(jq -cn --arg a "$spokea_vnet_id" --arg b "$spokeb_vnet_id" '[$a, $b]') ;;
    spokea|spokeb) local_expected=$(jq -cn --arg hub "$hub_vnet_id" '[$hub]') ;;
  esac
  peerings=$(az network vnet peering list -g "$RG" --vnet-name "$VNET" -o json \
    --subscription "$SUBSCRIPTION_ID") || exit 1
  jq -e --argjson expected "$local_expected" '
    type == "array" and
    length == ($expected | length) and
    all(.[]; . as $peering |
      (($peering.name | type == "string") and ($peering.name | length > 0)) and
      ($peering.remoteVirtualNetwork.id | type == "string") and
      ([ $expected[] | ascii_downcase ] | index($peering.remoteVirtualNetwork.id | ascii_downcase)) != null
    ) and
    ([ $expected[] as $remote |
      [ .[] | select(
        (.remoteVirtualNetwork.id | type == "string") and
        ((.remoteVirtualNetwork.id | ascii_downcase) == ($remote | ascii_downcase))
      ) ] as $matches
      | ($matches | length == 1) and
        (($matches[0].name | type == "string") and ($matches[0].name | length > 0)) and
        ($matches[0].peeringState == "Connected")
    ] | all)
  ' <<< "$peerings" >/dev/null || { fail "Unexpected/disconnected peerings: $zone"; exit 1; }
done
hub=$(vm_ip hub)
a=$(vm_ip spokea)
b=$(vm_ip spokeb)
fw_ip=$(firewall_ready_ip)
assert_avnm_routes_ready "$fw_ip"
assert_no_spoke_nat
if [[ "$2" == admin-denied ]]; then stage=denied; else stage="$2"; fi
assert_admin_rules_ready "$hub" "$a" "$b" "$stage"
# Hub→Spoke는 모든 검증 단계에서 직접 Peering 경로를 유지해야 합니다.
route_proof hub "$a" VNetPeering
route_proof hub "$b" VNetPeering
route_proof spokea "$b" VirtualAppliance "$fw_ip"
route_proof spokeb "$a" VirtualAppliance "$fw_ip"
route_proof spokea 8.8.8.8 VirtualAppliance "$fw_ip"
route_proof spokeb 8.8.8.8 VirtualAppliance "$fw_ip"
if [[ "$2" == admin-denied ]]; then
  # 서버 중단을 정책 차단으로 오인하지 않습니다.
  file=$(mktemp /tmp/lzbegin-local.XXXXXX)
  trap 'rm -f "$file"' EXIT
  printf 'curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8080/\n' > "$file"
  local_body=$(bash "$VERIFY_DIR/run-vm.sh" "$1" spokea "$file")
  [[ "${local_body//$'\n'/}" == spokea ]] || { fail "Spoke A service is not healthy"; exit 1; }
  admin_proof spokea "$a" "$hub" Deny deny-hub-to-a
  http_proof "$1" hub "$a" blocked
else
  admin_proof spokea "$a" "$hub" Allow hub-to-a
  http_proof "$1" hub "$a" spokea
fi
# A만 차단하는 실습이므로 Hub→B는 계속 성공해야 합니다.
admin_proof spokeb "$b" "$hub" Allow hub-to-b
http_proof "$1" hub "$b" spokeb
admin_proof spokeb "$b" "$a" Allow a-to-b
http_proof "$1" spokea "$b" spokeb
printf 'PASS: core %s evidence complete.\n' "$2"
