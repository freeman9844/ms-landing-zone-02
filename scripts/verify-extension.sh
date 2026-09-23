#!/usr/bin/env bash
# 모듈 06의 Firewall allowed/denied/restored 상태를 경로·NSG·HTTP·로그·인터넷 출구로 교차 검증합니다.
# 정책·UDR·NAT는 변경하지 않습니다. 교재에서 변경한 현재 상태를 실제 요청과 조회로 확인합니다.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/verify-common.sh"
[[ $# == 2 && "$2" =~ ^(allowed|denied|restored)$ ]] ||
  { fail "Usage: verify-extension.sh STATE_FILE allowed|denied|restored"; exit 1; }
load_run "$1"
assert_subscription
for rg in "$RG_HUB" "$RG_SPOKEA" "$RG_SPOKEB"; do assert_owned_rg "$rg"; done
# 배포 완료, 실습 SKU, 단일 IP 구성과 사설 IP를 확인한 뒤 그 IP를 경로의 비교 기준으로 사용합니다.
fw=$(az network firewall show -g "$RG_HUB" -n "fw-lzbegin-$RUN_ID" -o json)
jq -e '.provisioningState == "Succeeded" and .sku.name == "AZFW_VNet" and .sku.tier == "Standard"
  and (.ipConfigurations | length) == 1
  and (.ipConfigurations[0].privateIPAddress | type == "string" and length > 0)' \
  <<< "$fw" >/dev/null || { fail "Firewall is not ready"; exit 1; }
fw_ip=$(jq -r '.ipConfigurations[0].privateIPAddress' <<< "$fw")
fw_id=$(jq -er .id <<< "$fw")
law_id="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_HUB/providers/Microsoft.OperationalInsights/workspaces/log-lzbegin-$RUN_ID"
# 다른 workspace나 공용 로그 테이블을 조회해 잘못된 증거를 얻지 않도록 진단 설정부터 대조합니다.
# Dedicated는 AZFWNetworkRule/AZFWApplicationRule 자원별 테이블로 보내는 설정이며, Activity Log와 구분합니다.
diagnostics=$(az monitor diagnostic-settings show --name workshop --resource "$fw_id" -o json)
jq -e --arg law "$law_id" '(.workspaceId | ascii_downcase) == ($law | ascii_downcase) and
  .logAnalyticsDestinationType == "Dedicated" and
  any(.logs[]; .category == "AZFWNetworkRule" and .enabled) and
  any(.logs[]; .category == "AZFWApplicationRule" and .enabled)' <<< "$diagnostics" >/dev/null ||
  { fail "Firewall diagnostics are not ready"; exit 1; }
public_ip=$(az network public-ip show -g "$RG_HUB" -n "pip-lzbegin-fw-$RUN_ID" --query ipAddress -o tsv)
hub=$(vm_ip hub)
a=$(vm_ip spokea)
b=$(vm_ip spokeb)
# 요청 A→B와 응답 B→A가 같은 Firewall을 지나야 합니다. Hub→B의 직접 Peering은 그대로 유지합니다.
route_proof spokea "$b" VirtualAppliance "$fw_ip"
route_proof spokeb "$a" VirtualAppliance "$fw_ip"
route_proof hub "$b" VNetPeering
nsg_proof spokeb "$b" "$a" Allow
http_proof "$1" hub "$b" spokeb
# 새 A→B 요청 직전에 시각을 기록해 이전 실습의 Allow/Deny 로그를 성공 증거로 재사용하지 않습니다.
start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if [[ "$2" == denied ]]; then
  http_proof "$1" spokea "$b" blocked
  action=Deny
else
  # allowed와 restored는 같은 Allow 증거를 요구합니다. 이 분기에서 Firewall 정책을 변경하지는 않습니다.
  http_proof "$1" spokea "$b" spokeb
  action=Allow
fi
# timeout만으로 Firewall 차단을 확정하지 않고 같은 흐름과 처리 결과의 로그까지 요구합니다.
bash "$VERIFY_DIR/firewall-logs.sh" "$1" "$start" "$a" "$b" 8080 "$action"
guest=$(mktemp /tmp/lzbegin-egress.XXXXXX)
trap 'rm -f "$guest"' EXIT
# denied 단계도 A→B HTTP만 막는 실습입니다. 별도 규칙의 HTTPS 출구와 관리 경로는 계속 정상이어야 합니다.
# 게스트에서 DNS를 한 번 조회한 뒤 curl에도 그 주소를 지정해, 접속한 목적지와 경로 검사 대상을 맞춥니다.
# --resolve는 원래 HTTPS 호스트 이름을 유지하므로 인증서 검증을 끄지 않습니다.
cat > "$guest" <<'GUEST'
command -v curl >/dev/null
resolved=$(python3 -c 'import socket; print(socket.getaddrinfo("api.ipify.org", 443, socket.AF_INET, socket.SOCK_STREAM)[0][4][0])')
public=$(curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
  --resolve "api.ipify.org:443:$resolved" https://api.ipify.org)
printf 'EGRESS %s %s\n' "$resolved" "$public"
GUEST
# 두 Spoke 각각에서 외부 서비스가 보는 출발지 공인 IP와 실제 목적지의 유효 경로를 함께 확인합니다.
for zone in spokea spokeb; do
  response=$(bash "$VERIFY_DIR/run-vm.sh" "$1" "$zone" "$guest")
  read -r marker destination actual extra <<< "$response"
  [[ "$marker" == EGRESS && -z "$extra" && -n "$public_ip" && "$actual" == "$public_ip" ]] ||
    { fail "Egress IP mismatch/unverified: $response"; exit 1; }
  route_proof "$zone" "$destination" VirtualAppliance "$fw_ip"
done
printf 'PASS: extension %s has matching route, NSG, HTTP, Firewall log and egress evidence.\n' "$2"
