#!/usr/bin/env bash
# 모듈 04의 기준 상태(baseline), NSG 차단(nsg-denied), 복구(restored)를 검증합니다.
# NSG 규칙을 직접 바꾸지 않습니다. 교재의 해당 변경을 적용한 뒤 Cloud Shell/로컬 CLI에서 실행합니다.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/verify-common.sh"
[[ $# == 2 && "$2" =~ ^(baseline|nsg-denied|restored)$ ]] ||
  { fail "Usage: verify-core.sh STATE_FILE baseline|nsg-denied|restored"; exit 1; }
load_run "$1"
assert_subscription
# baseline과 restored는 같은 정상 통신을 기대합니다. restored 인수 자체가 NSG 규칙을 복구하지는 않습니다.
# Hub 두 개, 각 Spoke 한 개의 연결이 모두 Connected여야 합니다. 추가 Peering도 학습 전제를 바꿉니다.
for zone in hub spokea spokeb; do
  zone_context "$zone"
  assert_owned_rg "$RG"
  peerings=$(az network vnet peering list -g "$RG" --vnet-name "$VNET" -o json)
  expected=1
  [[ "$zone" != hub ]] || expected=2
  jq -e --argjson n "$expected" 'length == $n and all(.[]; .peeringState == "Connected")' \
    <<< "$peerings" >/dev/null || { fail "Unexpected/disconnected peerings: $zone"; exit 1; }
done
hub=$(vm_ip hub)
a=$(vm_ip spokea)
b=$(vm_ip spokeb)
# Hub→Spoke는 모든 검증 단계에서 직접 Peering 경로를 유지해야 합니다.
route_proof hub "$a" VNetPeering
route_proof hub "$b" VNetPeering
if [[ "$2" == nsg-denied ]]; then
  # A 내부의 서비스가 정상인지 먼저 확인해 서버 중단을 의도적인 NSG 차단으로 오인하지 않습니다.
  file=$(mktemp /tmp/lzbegin-local.XXXXXX)
  trap 'rm -f "$file"' EXIT
  printf 'curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8080/\n' > "$file"
  local_body=$(bash "$VERIFY_DIR/run-vm.sh" "$1" spokea "$file")
  [[ "${local_body//$'\n'/}" == spokea ]] || { fail "Spoke A service is not healthy"; exit 1; }
  nsg_proof spokea "$a" "$hub" Deny
  http_proof "$1" hub "$a" blocked
else
  # 허용 구간도 NSG 판정과 실제 응답을 모두 요구합니다. 잘못된 서버가 200을 응답해도 성공이 아닙니다.
  nsg_proof spokea "$a" "$hub" Allow
  http_proof "$1" hub "$a" spokea
fi
# A만 차단하는 실습이므로 Hub→B는 계속 성공해야 합니다.
nsg_proof spokeb "$b" "$hub" Allow
http_proof "$1" hub "$b" spokeb
# A→B는 NSG에서 허용해도 경로가 None이어서 실패해야 합니다. 이 조합으로 Peering 비전이성을 증명합니다.
nsg_proof spokeb "$b" "$a" Allow
route_proof spokea "$b" None
http_proof "$1" spokea "$b" blocked
printf 'PASS: core %s evidence complete.\n' "$2"
