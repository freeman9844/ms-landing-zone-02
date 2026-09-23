#!/usr/bin/env bash
# STATE START_UTC SOURCE_IP DEST_IP PORT Allow|Deny: 이번 검증 흐름의 Firewall 로그 도착을 기다립니다.
# 로그를 만드는 스크립트가 아닙니다. verify-extension.sh가 먼저 게스트에서 통신을 시도한 뒤 호출합니다.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/workshop-common.sh"
[[ $# == 6 ]] || { fail "Usage: firewall-logs.sh STATE START_UTC SOURCE_IP DEST_IP PORT Allow|Deny"; exit 1; }
# KQL에 넣기 전에 시각·IPv4·포트·동작 값을 제한해 잘못된 필터나 임의 쿼리 구성이 들어가지 않게 합니다.
python3 - "$2" "$3" "$4" "$5" "$6" <<'PY'
import datetime
import ipaddress
import sys
try:
    datetime.datetime.strptime(sys.argv[1], "%Y-%m-%dT%H:%M:%SZ")
    ipaddress.IPv4Address(sys.argv[2])
    ipaddress.IPv4Address(sys.argv[3])
    if not sys.argv[4].isdigit() or not 1 <= int(sys.argv[4]) <= 65535:
        raise ValueError("Invalid port")
    if sys.argv[5] not in ("Allow", "Deny"):
        raise ValueError("Invalid action")
except ValueError as error:
    sys.exit(f"ERROR: invalid log filter: {error}")
PY
load_run "$1"
assert_subscription
assert_owned_rg "$RG_HUB"
# 이번 실습의 정확한 Firewall ID와 workspace 조회용 UUID(customerId)를 사용합니다.
fw_id=$(az network firewall show -g "$RG_HUB" -n "fw-lzbegin-$RUN_ID" --query id -o tsv)
expected="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_HUB/providers/Microsoft.Network/azureFirewalls/fw-lzbegin-$RUN_ID"
[[ "${fw_id,,}" == "${expected,,}" ]] || { fail "Unexpected Firewall ID"; exit 1; }
workspace=$(az monitor log-analytics workspace show -g "$RG_HUB" -n "log-lzbegin-$RUN_ID" --query customerId -o tsv)
[[ "$workspace" =~ ^[0-9a-fA-F-]{36}$ ]] || { fail "Invalid workspace customer ID"; exit 1; }
# 새 시작 시각·출발지·목적지·포트·Allow/Deny·Firewall ID가 모두 같은 로그만 조회합니다.
# _ResourceId의 =~는 대소문자 표기 차이만 허용합니다. 다른 Firewall의 로그까지 허용하지 않습니다.
query="AZFWNetworkRule
| where TimeGenerated >= datetime($2)
| where SourceIp == '$3' and DestinationIp == '$4'
| where DestinationPort == $5 and Action == '$6'
| where _ResourceId =~ '$fw_id'
| project TimeGenerated, SourceIp, DestinationIp, DestinationPort, Action, _ResourceId"
# 로그 수집 지연은 최대 20회/10분까지 기다립니다. 조회 한 번도 남은 전체 대기 시간을 넘기지 않습니다.
deadline=$((SECONDS + 600))
# --timespan PT1H는 조회 시간 범위이고, KQL의 시작 시각 조건은 그 안에서 이번 요청 이후로 더 좁힙니다.
for ((attempt=0; attempt<20; attempt++)); do
  remaining=$((deadline - SECONDS))
  (( remaining > 0 )) || break
  # DNS·권한·API 오류는 "아직 로그가 없음"과 구분해 즉시 실패로 알립니다.
  rows=$(timeout "$remaining" az monitor log-analytics query --workspace "$workspace" \
    --analytics-query "$query" --timespan PT1H -o json) ||
    { fail "Log query failed or timed out; evidence is incomplete."; exit 1; }
  # KQL 응답도 다시 검증합니다. 응답 형태나 시각이 잘못되면 성공으로 처리하지 않습니다.
  count=$(printf '%s' "$rows" | python3 -c '
import datetime, json, sys
rows = json.load(sys.stdin)
if not isinstance(rows, list):
    sys.exit("ERROR: unexpected Log Analytics response shape")
start = datetime.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
matches = []
for row in rows:
    if (row.get("SourceIp") != sys.argv[2] or row.get("DestinationIp") != sys.argv[3]
        or str(row.get("DestinationPort")) != sys.argv[4] or row.get("Action") != sys.argv[5]
        or str(row.get("_ResourceId", "")).lower() != sys.argv[6].lower()):
        continue
    try:
        stamp = datetime.datetime.fromisoformat(row["TimeGenerated"].replace("Z", "+00:00"))
        if stamp >= start:
            matches.append(row)
    except (ValueError, KeyError, TypeError) as error:
        sys.exit(f"ERROR: invalid log timestamp: {error}")
print(len(matches))
' "$2" "$3" "$4" "$5" "$6" "$fw_id")
  if [[ "$count" -gt 0 ]]; then
    printf '%s\nPASS: matching Firewall %s evidence found.\n' "$rows" "$6"
    exit 0
  fi
  # 정상 조회에서 일치 행이 없을 때만 재시도합니다. 대기 종료까지 없으면 검증 미완료로 남깁니다.
  printf 'Waiting for current flow logs (%s/20).\n' "$((attempt+1))" >&2
  remaining=$((deadline - SECONDS))
  (( remaining > 0 )) || break
  sleep "$((remaining < 30 ? remaining : 30))"
done
fail "No matching Firewall evidence within 10 minutes. Verification is incomplete."
