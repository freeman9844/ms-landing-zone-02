#!/usr/bin/env bash
# 보안 정책·Firewall 검증기가 source로 공유하는 증거 수집 함수입니다. Azure 설정은 변경하지 않습니다.
# HTTP 확인은 Run Command로 게스트에서 실행하며, Azure API 조회 결과와 함께 판정해야 합니다.
source "$(dirname "${BASH_SOURCE[0]}")/workshop-common.sh"
VERIFY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# IP를 .4로 가정하지 않고 NIC에서 조회합니다. 비어 있거나 사설 IPv4가 아니면 검증을 중단합니다.
# vm_ip ZONE의 stdout은 IP 한 개입니다. 호출자가 $(vm_ip spokea)로 받으므로 진행 문구를 섞지 않습니다.
vm_ip() {
  local ip
  zone_context "$1" || return 1
  ip=$(az network nic show -g "$RG" -n "nic-lzbegin-$1-$RUN_ID" \
    --query 'ipConfigurations[0].privateIPAddress' -o tsv) || return 1
  python3 - "$ip" <<'PY'
import ipaddress
import sys
try:
    address = ipaddress.IPv4Address(sys.argv[1])
except ipaddress.AddressValueError as error:
    sys.exit(f"ERROR: invalid VM IP: {error}")
if not address.is_private:
    sys.exit("ERROR: expected private VM address")
print(address)
PY
}

# Network Watcher의 IP flow 판정은 Admin Rule 증거입니다. 실제 HTTP 연결 성공이나 경로 존재를 보장하지 않습니다.
# local은 대상 VM의 8080, remote는 출발지 IP와 판정용 클라이언트 포트입니다.
# 50000은 NSG 판정용 예시 출발지 포트입니다. 실제 curl이 그 포트를 사용했다는 뜻은 아닙니다.
admin_proof() {
  local zone="$1" destination="$2" source="$3" expected="$4" rule="$5" result
  zone_context "$zone" || return 1
  result=$(az network watcher test-ip-flow -g "$RG" --vm "$VM" --direction Inbound \
    --protocol TCP --local "$destination:8080" --remote "$source:50000" -o json) || return 1
  jq -e --arg expected "$expected" --arg rule "$rule" '
    .access == $expected and
    (.ruleName | type == "string") and
    (.ruleName == $rule or
      ((.ruleName | ascii_downcase) ==
        ("/subscriptions/" + ($sub | ascii_downcase) + "/resourcegroups/" + ($rg | ascii_downcase) +
         "/providers/microsoft.network/networkmanagers/" + ($manager | ascii_downcase) +
         "/securityadminconfigurations/" + ($config | ascii_downcase) +
         "/rulecollections/" + ($zone | ascii_downcase) + "/rules/" + ($rule | ascii_downcase))))
  ' --arg sub "$SUBSCRIPTION_ID" --arg rg "$RG_HUB" --arg manager "$AVNM" \
    --arg config "sc-lzbegin-http-$RUN_ID" --arg zone "$zone" \
    <<< "$result" >/dev/null || { fail "Admin rule evidence does not show $rule/$expected: $result"; return 1; }
  printf 'Admin rule: %s\n' "$result"
}

# 설정한 route table이 아니라 NIC의 유효 경로를 검사합니다. Firewall 경유 시 사설 next-hop IP도 비교합니다.
# route_proof ZONE DEST_IP NEXT_HOP [FIREWALL_IP]: 기대 경로와 다르거나 조회에 실패하면 0이 아닌 상태를 반환합니다.
route_proof() {
  local zone="$1" destination="$2" hop="$3" next_ip="${4:-}" file rc=0
  zone_context "$zone" || return 1
  file=$(mktemp /tmp/lzbegin-route.XXXXXX) || return 1
  if az network nic show-effective-route-table -g "$RG" -n "nic-lzbegin-$zone-$RUN_ID" -o json > "$file"; then
    if [[ -n "$next_ip" ]]; then
      python3 "$VERIFY_DIR/assert-route.py" "$file" "$destination" "$hop" "$next_ip" || rc=$?
    else
      python3 "$VERIFY_DIR/assert-route.py" "$file" "$destination" "$hop" || rc=$?
    fi
  else
    rc=1
  fi
  # 임시 파일 삭제의 성공으로 원래 검증 실패가 덮이지 않도록 종료 코드를 보존합니다.
  rm -f "$file"
  return "$rc"
}

# 성공 시 정확한 Spoke 이름을, 차단 예상 시 연결 실패(7) 또는 timeout(28)을 요구합니다.
# DNS 오류·HTTP 오류·잘못된 서버 응답을 "의도한 네트워크 차단"으로 오인하지 않습니다.
# http_proof STATE ZONE DEST_IP EXPECTED: ZONE의 VM에서 요청을 보내며 EXPECTED는 spokea/spokeb/blocked 중 하나입니다.
# blocked 결과만으로 차단 장비를 특정하지 않습니다. 호출자가 NSG·경로·Firewall 로그와 함께 판단합니다.
http_proof() {
  local state="$1" zone="$2" destination="$3" expected="$4" file rc=0
  [[ "$destination" =~ ^[0-9.]+$ && "$expected" =~ ^(spokea|spokeb|blocked)$ ]] ||
    { fail "Invalid HTTP proof arguments"; return 1; }
  file=$(mktemp /tmp/lzbegin-http.XXXXXX) || return 1
  {
    # 게스트용 변수는 셸 인용으로 안전하게 전달합니다. 본문은 매번 새 연결로 검사해 기존 연결의 영향을 줄입니다.
    printf 'destination=%q\nexpected=%q\n' "$destination" "$expected"
    cat <<'GUEST'
command -v curl >/dev/null
if body=$(curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
  -H 'Connection: close' "http://$destination:8080/"); then
  [[ "$body" == "$expected" ]] || { printf 'ERROR: unexpected successful response: %s\n' "$body" >&2; exit 1; }
  printf 'PASS: HTTP %s\n' "$body"
else
  code=$?
  [[ "$expected" == blocked && ( "$code" == 7 || "$code" == 28 ) ]] ||
    { printf 'ERROR: unexpected curl failure: %s\n' "$code" >&2; exit 1; }
  printf 'PASS: connection blocked (curl %s); correlate NSG/route/firewall evidence.\n' "$code"
fi
GUEST
  } > "$file"
  # 호출한 VM에서 검사를 실행하고 종료 코드·출력을 돌려받습니다. 임시 게스트 파일은 결과와 관계없이 지웁니다.
  bash "$VERIFY_DIR/run-vm.sh" "$state" "$zone" "$file" || rc=$?
  rm -f "$file"
  return "$rc"
}
