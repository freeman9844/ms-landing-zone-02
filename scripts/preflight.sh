#!/usr/bin/env bash
# Cloud Shell/로컬 CLI의 읽기 전용 사전 점검입니다. Provider 등록이나 자원 배포를 대신하지 않습니다.
# STATE_FILE [--extension]: 초기 배포 용량 또는 Firewall 단계에서 재사용할 VM의 준비 상태를 확인합니다.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/workshop-common.sh"
[[ $# -ge 1 && $# -le 2 ]] || { fail "Usage: preflight.sh STATE_FILE [--extension]"; exit 1; }
[[ $# == 1 || "$2" == --extension ]] || { fail "Unknown option: $2"; exit 1; }
# 저장된 리전·구독과 현재 로그인 대상을 먼저 대조해 잘못된 환경의 quota를 검사하지 않습니다.
load_run "$1"
assert_subscription
locations=$(az account list-locations --query '[].name' -o json)
jq -e --arg loc "$LOCATION" 'index($loc) != null' <<< "$locations" >/dev/null ||
  { fail "Location is not available to this subscription: $LOCATION"; exit 1; }
# Firewall 단계에서는 로그 저장소용 Provider도 필요합니다. 미등록이면 자동 등록하지 않고 중단합니다.
providers=(Microsoft.Network Microsoft.Compute)
[[ "${2:-}" != --extension ]] || providers+=(Microsoft.OperationalInsights)
for provider in "${providers[@]}"; do
  status=$(az provider show --namespace "$provider" --query registrationState -o tsv)
  [[ "$status" == Registered ]] ||
    { fail "$provider is $status. Register it explicitly, wait, then repeat preflight."; exit 1; }
done
# 이미 실행 중인 실습 VM의 용량은 다시 요구하지 않습니다. 없는 VM 한 대당 2 vCPU만 합산합니다.
needed_vcpus=0
# 이 내부 반복은 세 VM의 상태를 빠짐없이 검사하기 위한 것입니다. 참가자 대신 자원을 생성하지 않습니다.
for zone in hub spokea spokeb; do
  zone_context "$zone"
  exists=$(az group exists --name "$RG" -o tsv)
  vms='[]'
  case "$exists" in
    true)
      # 다른 실습의 VM으로 필요 용량을 줄이지 않도록 RG 소유 확인 후 정확한 VM 이름만 선택합니다.
      assert_owned_rg "$RG"
      vms=$(az vm list --resource-group "$RG" --show-details -o json)
      vms=$(jq -ce --arg name "$VM" '
        if type == "array" then [.[] | select(.name == $name)]
        else error("Expected a VM array") end
      ' <<< "$vms") ;;
    false) ;;
    *) fail "Cannot determine whether $RG exists"; exit 1 ;;
  esac
  if [[ $(jq length <<< "$vms") == 0 ]]; then
    # Firewall 단계는 새 VM을 만들지 않으므로 모듈 04의 VM이 없으면 다음 단계로 진행할 수 없습니다.
    [[ "${2:-}" != --extension ]] ||
      { fail "Missing VM: $VM. Complete the core deployment before the extension."; exit 1; }
    needed_vcpus=$((needed_vcpus + 2))
  else
    # 중지·배포 실패·잘못된 크기의 VM은 단순히 "존재한다"는 이유로 준비 완료 처리하지 않습니다.
    jq -e --arg loc "$LOCATION" '
      length == 1 and .[0].location == $loc and
      .[0].hardwareProfile.vmSize == "Standard_B2als_v2" and
      .[0].provisioningState == "Succeeded" and .[0].powerState == "VM running"
    ' <<< "$vms" >/dev/null ||
      { fail "Existing VM is not ready: $VM. Check its region, size, provisioning and running state."; exit 1; }
  fi
done
if (( needed_vcpus > 0 )); then
  # 이미 세 VM이 모두 정상 실행 중이면 신규 할당 검사를 건너뜁니다. 기존 사용량을 free quota로 다시 요구하지 않습니다.
  # SKU 이름만 아니라 구독·리전 제한과 실제 vCPU 수를 확인하고, 응답에서 quota family를 얻습니다.
  skus=$(az vm list-skus --location "$LOCATION" --size Standard_B2als_v2 --all -o json)
  family=$(jq -er '
    [.[] | select(.name == "Standard_B2als_v2" and (.restrictions | length) == 0)
     | select(any(.capabilities[]; .name == "vCPUs" and .value == "2"))]
    | if length == 1 then .[0].family else error("Unavailable/ambiguous Standard_B2als_v2") end
  ' <<< "$skus")
  usage=$(az vm list-usage --location "$LOCATION" -o json)
  # cores는 리전 전체의 vCPU 한도이고 family는 선택 SKU 계열의 한도입니다. 둘 중 하나만 넉넉해도 부족합니다.
  # 지역 전체와 해당 VM family 모두 여유가 있어야 합니다. CLI의 숫자 문자열도 엄격하게 검사합니다.
  for quota in cores "$family"; do
    jq -e --arg name "$quota" --argjson needed "$needed_vcpus" '
      def quota_number:
        (if type == "number" then .
         elif type == "string" and test("^[0-9]+$") then tonumber
         else error("Invalid quota value") end)
        | if . >= 0 and floor == . then . else error("Invalid quota count") end;
      [.[] | select((.name.value | ascii_downcase) == ($name | ascii_downcase))]
      | length == 1 and
        ((.[0].limit | quota_number) - (.[0].currentValue | quota_number) >= $needed)
    ' <<< "$usage" >/dev/null ||
      { fail "Insufficient or unknown quota: $quota (need $needed_vcpus free vCPUs)."; exit 1; }
  done
fi
# 사전 점검 성공은 용량 예약이 아닙니다. 실제 배포 시점의 정책·지역 용량 때문에 실패할 수 있습니다.
printf 'PASS: read-only preflight. Capacity is not reserved; RG creation and service deployment may still fail.\n'
