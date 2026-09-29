#!/usr/bin/env bash

# 교재와 다른 스크립트가 source로 읽는 공통 함수입니다. 읽는 것만으로 Azure 자원을 만들지 않습니다.
# 호출한 Cloud Shell까지 종료하지 않도록 함수의 실패는 exit 대신 return으로 전달합니다.
fail() {
  # 표준 오류로만 출력해 $(함수)의 결과에 오류 문구가 정상 데이터처럼 섞이지 않게 합니다.
  printf 'ERROR: %s\n' "$*" >&2
  return 1
}

# 지정한 실행 ID의 로컬 복구 파일만 만듭니다. Azure에 이미 있는 실습의 상태 복구에도 사용합니다.
# 함수 본문을 별도 셸 (...)로 실행해 파일 권한 설정과 임시 파일 정리 trap을 바깥 셸과 분리합니다.
create_run() (
  local run_id="${1:-}" subscription="${2:-}" location="${3:-}" tmp path pool_id
  [[ "$run_id" =~ ^[a-z0-9]{6,12}$ ]] || { fail "runId: use 6-12 lowercase letters/digits."; return 1; }
  [[ "$subscription" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] ||
    { fail "subscriptionId must be a UUID."; return 1; }
  [[ "$location" == "koreacentral" ]] || { fail "Invalid Azure location. Use koreacentral."; return 1; }
  pool_id="/subscriptions/${subscription,,}/resourceGroups/rg-lzbegin-ipam/providers/Microsoft.Network/networkManagers/avnm-lzbegin-ipam/ipamPools/ipam-lzbegin-shared"
  # 상태 파일은 본인만 읽고 쓸 수 있게 하며, 기존 파일을 덮어쓰지 않습니다.
  umask 077
  mkdir -p .workshop-state || return 1
  path=".workshop-state/$run_id.json"
  [[ ! -e "$path" ]] || { fail "State exists: $path. Restore it; do not overwrite."; return 1; }
  tmp=$(mktemp .workshop-state/.new.XXXXXX) || return 1
  trap 'rm -f "$tmp"' EXIT
  jq -n --arg id "$run_id" --arg sub "${subscription,,}" --arg loc "$location" --arg pool "$pool_id" '{
    schemaVersion: 3,
    topology: "avnm-hub-spoke",
    runId: $id,
    subscriptionId: $sub,
    ipamPoolId: $pool,
    location: $loc,
    resourceGroups: {
      hub: ("rg-lzbegin-hub-" + $id),
      spokea: ("rg-lzbegin-spokea-" + $id),
      spokeb: ("rg-lzbegin-spokeb-" + $id)
    }
  }' > "$tmp" || return 1
  # 파일 존재 확인 이후 다른 실행이 같은 이름을 만들었더라도 ln이 실패해 덮어쓰기를 막습니다.
  ln "$tmp" "$path" || { fail "State exists or could not be created: $path"; return 1; }
  printf '%s\n' "$path"
)

# 새 실습 전용입니다. 같은 시각에 시작한 참가자의 이름 충돌을 줄이기 위해 난수 ID를 사용합니다.
new_run() (
  [[ $# == 2 ]] || { fail "Usage: new_run SUBSCRIPTION_ID LOCATION"; return 1; }
  local run_id zone rg exists
  SUBSCRIPTION_ID="${1,,}"
  assert_subscription || return 1
  run_id=$(python3 -c 'import secrets; print(secrets.token_hex(6))') ||
    { fail "Cannot generate a random run ID."; return 1; }
  # 세 RG 중 하나라도 이미 있으면 태그와 관계없이 거부합니다. 조회 실패도 부재로 취급하지 않습니다.
  for zone in hub spokea spokeb; do
    rg="rg-lzbegin-$zone-$run_id"
    exists=$(az group exists --name "$rg" -o tsv) ||
      { fail "Cannot inspect group: $rg"; return 1; }
    case "$exists" in
      false) ;;
      true) fail "Group already exists: $rg. Start again with a new random ID."; return 1 ;;
      *) fail "Cannot determine whether $rg exists"; return 1 ;;
    esac
  done
  create_run "$run_id" "$1" "$2"
)

clear_run() {
  unset RUN_ID SUBSCRIPTION_ID LOCATION IPAM_POOL_ID RG_HUB RG_SPOKEA RG_SPOKEB \
    AVNM NETWORK_GROUP CONNECTIVITY_CONFIG \
    AVNM_ID NETWORK_GROUP_ID CONNECTIVITY_CONFIG_ID \
    ROUTE_GROUP_A_ID ROUTE_GROUP_B_ID \
    HUB_VNET_CIDR SPOKEA_VNET_CIDR SPOKEB_VNET_CIDR \
    HUB_SUBNET_CIDR SPOKEA_SUBNET_CIDR SPOKEB_SUBNET_CIDR FIREWALL_SUBNET_CIDR \
    RG SUBNET PREFIX VNET VM NSG ||
    { fail "Cannot clear previous workshop variables."; return 1; }
}

show_workshop_state_files() {
  if [[ -d .workshop-state ]]; then
    ls .workshop-state/ || { fail "Cannot list workshop state files."; return 1; }
  fi
}

workshop_state_example() {
  local state_file
  for state_file in .workshop-state/*.json; do
    [[ -f "$state_file" && "$state_file" =~ ^\.workshop-state/[a-z0-9]{6,12}\.json$ ]] || continue
    printf '%s\n' "$state_file"
    return
  done
  printf '%s\n' '.workshop-state/<실행 ID>.json'
}

# 새 Cloud Shell 세션에서 경로가 없을 때만 기존 상태 파일을 묻습니다. 파일은 자동 선택하지 않습니다.
ensure_state_file() {
  if [[ -z "${STATE_FILE:-}" ]]; then
    local example
    clear_run || return 1
    show_workshop_state_files || return 1
    example=$(workshop_state_example) || return 1
    read -rp "기존 상태 파일 경로 (예: $example): " STATE_FILE ||
      { unset STATE_FILE; fail "State file path input cancelled."; return 1; }
    [[ -n "$STATE_FILE" ]] ||
      { unset STATE_FILE; fail "State file path is empty."; return 1; }
  fi
  export STATE_FILE
}

# JSON을 셸 코드로 실행하지 않고 구조·값·이름 규칙을 검사한 뒤 필요한 변수만 복구합니다.
load_run() {
  local data
  # 복구 실패 후 별도 실행 블록이 이전 실습을 대상으로 삼지 않도록 파생 구역 변수도 비웁니다.
  clear_run || return 1
  if jq -se 'length == 1 and (.[0] | type == "object" and .schemaVersion == 2)' "${1:-}" >/dev/null 2>&1; then
    fail "Schema 2 run: resume with git tag workshop-pre-ipam-8d4781f"
    return 1
  fi
  # jq -e는 조건에 맞는 JSON이 없을 때도 실패합니다. JSON을 읽었다는 사실만으로 성공 처리하지 않습니다.
  # 실패 시 대상 변수는 미설정 상태입니다. 호출자는 &&/오류 처리로 후속 Azure 명령을 중단해야 합니다.
  data=$(jq -cse '
    if length == 1 then .[0] else empty end
    |
    select(type == "object" and .schemaVersion == 3 and .topology == "avnm-hub-spoke")
    | select(.runId | type == "string" and test("^[a-z0-9]{6,12}$"))
    | select(.subscriptionId | type == "string" and test("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"))
    | select(.ipamPoolId | type == "string")
    | select(.ipamPoolId == ("/subscriptions/" + .subscriptionId + "/resourceGroups/rg-lzbegin-ipam/providers/Microsoft.Network/networkManagers/avnm-lzbegin-ipam/ipamPools/ipam-lzbegin-shared"))
    | select(.location == "koreacentral")
    | select((.resourceGroups | keys) == ["hub", "spokea", "spokeb"])
    | select(.resourceGroups.hub == ("rg-lzbegin-hub-" + .runId))
    | select(.resourceGroups.spokea == ("rg-lzbegin-spokea-" + .runId))
    | select(.resourceGroups.spokeb == ("rg-lzbegin-spokeb-" + .runId))
  ' "${1:-}") || { fail "Invalid or unreadable state file: ${1:-missing}"; return 1; }
  # 검증된 동일 JSON에서 값을 추출합니다. 복구는 환경 변수만 준비하며 Azure 자원을 생성하지 않습니다.
  RUN_ID=$(jq -r .runId <<< "$data")
  SUBSCRIPTION_ID=$(jq -r .subscriptionId <<< "$data")
  IPAM_POOL_ID=$(jq -r .ipamPoolId <<< "$data")
  LOCATION=$(jq -r .location <<< "$data")
  RG_HUB=$(jq -r .resourceGroups.hub <<< "$data")
  RG_SPOKEA=$(jq -r .resourceGroups.spokea <<< "$data")
  RG_SPOKEB=$(jq -r .resourceGroups.spokeb <<< "$data")
  AVNM="avnm-lzbegin-$RUN_ID"
  NETWORK_GROUP="ng-lzbegin-spokes-$RUN_ID"
  CONNECTIVITY_CONFIG="cc-lzbegin-hub-spoke-$RUN_ID"
  AVNM_ID="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_HUB/providers/Microsoft.Network/networkManagers/$AVNM"
  NETWORK_GROUP_ID="$AVNM_ID/networkGroups/$NETWORK_GROUP"
  CONNECTIVITY_CONFIG_ID="$AVNM_ID/connectivityConfigurations/$CONNECTIVITY_CONFIG"
  ROUTE_GROUP_A_ID="$AVNM_ID/networkGroups/ng-lzbegin-route-spokea-$RUN_ID"
  ROUTE_GROUP_B_ID="$AVNM_ID/networkGroups/ng-lzbegin-route-spokeb-$RUN_ID"
  # 하위 스크립트도 같은 실습 정보를 사용하도록 환경 변수로 전달합니다.
  export RUN_ID SUBSCRIPTION_ID LOCATION IPAM_POOL_ID RG_HUB RG_SPOKEA RG_SPOKEB \
    AVNM NETWORK_GROUP CONNECTIVITY_CONFIG \
    AVNM_ID NETWORK_GROUP_ID CONNECTIVITY_CONFIG_ID ROUTE_GROUP_A_ID ROUTE_GROUP_B_ID
}

# 구독을 자동 변경하지 않습니다. 불일치하면 사용자가 올바른 구독을 명시적으로 선택해야 합니다.
assert_subscription() {
  local active
  active=$(az account show --query id -o tsv) || { fail "Cannot read active subscription. Sign in first."; return 1; }
  [[ "${active,,}" == "${SUBSCRIPTION_ID:-}" ]] ||
    { fail "Subscription mismatch: active=$active expected=${SUBSCRIPTION_ID:-missing}. Select it explicitly."; return 1; }
}

# 정확한 이름·구독·네 가지 태그로 실수에 의한 재사용/삭제를 막습니다. RBAC를 대신하는 검사는 아닙니다.
assert_owned_rg() {
  local rg="${1:-}" data
  # 이름 접두사가 비슷한 RG까지 허용하지 않습니다. 상태 파일의 정확한 세 이름만 허용합니다.
  [[ -n "${RUN_ID:-}" && ( "$rg" == "$RG_HUB" || "$rg" == "$RG_SPOKEA" || "$rg" == "$RG_SPOKEB" ) ]] ||
    { fail "Not an exact workshop resource group: $rg"; return 1; }
  data=$(az group show --name "$rg" -o json) || { fail "Cannot inspect group: $rg"; return 1; }
  # Azure ID의 표기 대소문자는 무시하지만, 네 소유 태그의 값은 교재와 정확히 일치해야 합니다.
  jq -e --arg rg "$rg" --arg id "$RUN_ID" --arg sub "$SUBSCRIPTION_ID" '
    .name == $rg and
    (.id | ascii_downcase) == ("/subscriptions/" + $sub + "/resourcegroups/" + $rg) and
    .tags.workshop == "lz-beginner" and .tags.environment == "lab" and
    .tags.runId == $id and .tags.managedBy == "workshop"
  ' <<< "$data" >/dev/null || { fail "Ownership mismatch: $rg. Do not reuse/delete it."; return 1; }
}

# zone은 가용 영역이 아니라 실습 구역(hub/spokea/spokeb)입니다. 자원을 만들지 않고 대상 변수만 바꿉니다.
zone_context() {
  local zone="${1:-}" resolved rg subnet
  unset RG SUBNET PREFIX VNET VM NSG
  case "$zone" in
    hub) resolved="${HUB_VNET_CIDR:-}"; rg="${RG_HUB:-}"; subnet=snet-management ;;
    spokea) resolved="${SPOKEA_VNET_CIDR:-}"; rg="${RG_SPOKEA:-}"; subnet=snet-workload ;;
    spokeb) resolved="${SPOKEB_VNET_CIDR:-}"; rg="${RG_SPOKEB:-}"; subnet=snet-workload ;;
    *) fail "Unknown zone: $zone"; return 1 ;;
  esac
  [[ -n "$resolved" && -n "$rg" && -n "${RUN_ID:-}" ]] ||
    { fail "Resolve live IPAM CIDRs before using zone $zone."; return 1; }
  RG="$rg"
  SUBNET="$subnet"
  PREFIX="$resolved"
  VNET="vnet-lzbegin-$zone-$RUN_ID"
  VM="vm-lzbegin-$zone-$RUN_ID"
  NSG="nsg-lzbegin-$zone-$RUN_ID"
  export RG SUBNET PREFIX VNET VM NSG
}
