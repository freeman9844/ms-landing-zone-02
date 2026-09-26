#!/usr/bin/env bash
# STATE_FILE에 기록된 정확한 세 실습 RG와 그 안의 자원을 삭제합니다. 정상 완료·중도 실패 모두 사용합니다.
# 공유 Network Watcher와 Cloud Shell 저장소는 대상에 넣지 않습니다. RG에 보관한 로그도 함께 삭제됩니다.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/workshop-common.sh"
[[ $# == 1 ]] || { fail "Usage: cleanup.sh STATE_FILE"; exit 1; }
load_run "$1"
assert_subscription
# 삭제 전 모든 대상의 존재와 소유를 먼저 확인합니다. 하나라도 확인할 수 없으면 삭제를 시작하지 않습니다.
# RG 소유 태그를 확인하는 것이지 내부 자원별 태그로 삭제를 선별하는 것은 아닙니다. 운영 자원을 섞지 마세요.
present=()
for rg in "$RG_HUB" "$RG_SPOKEA" "$RG_SPOKEB"; do
  exists=$(az group exists --name "$rg" -o tsv)
  case "$exists" in
    true) assert_owned_rg "$rg"; present+=("$rg") ;;
    false) printf 'Already absent: %s\n' "$rg" ;;
    *) fail "Unverified group existence: $rg"; exit 1 ;;
  esac
done
if [[ ${#present[@]} == 0 ]]; then
  # 이미 정리가 끝난 상태는 재실행해도 성공합니다. 조회 오류를 "이미 없음"으로 바꾸지는 않습니다.
  printf 'PASS: all three workshop groups are already absent.\n'
  exit 0
fi
printf 'Subscription: %s\nDelete ONLY:\n' "$SUBSCRIPTION_ID"
printf '  %s\n' "${present[@]}"
# 단순 yes 대신 실행 ID와 구독이 들어간 문구 전체를 입력받아 삭제 범위를 사용자가 다시 확인하게 합니다.
phrase="DELETE $RUN_ID FROM $SUBSCRIPTION_ID"
printf 'Type exactly: %s\n' "$phrase"
read -r answer || { fail "Cleanup cancelled (no confirmation)."; exit 1; }
[[ "$answer" == "$phrase" ]] || { fail "Cleanup cancelled; nothing deleted."; exit 1; }
# 사용자가 문구를 읽는 동안 상태가 바뀌었을 가능성을 줄이기 위해 실제 삭제 직전에 다시 확인합니다.
assert_subscription
for rg in "${present[@]}"; do
  assert_owned_rg "$rg"
done
# 관리형 테이블 ID를 해제 전 실제 Subnet에서 수집합니다. 이름·RG·태그를 추측하지 않습니다.
associated_tables=()
for zone in spokea spokeb; do
  if [[ "$zone" == spokea ]]; then rg="$RG_SPOKEA"; else rg="$RG_SPOKEB"; fi
  [[ " ${present[*]} " == *" $rg "* ]] || continue
  vnets=$(az network vnet list -g "$rg" -o json --subscription "$SUBSCRIPTION_ID")
  jq -e --arg name "vnet-lzbegin-$zone-$RUN_ID" '
    type == "array" and length <= 1 and all(.[]; .name == $name)
  ' <<< "$vnets" >/dev/null || { fail "Unexpected VNet in Spoke RG: $rg"; exit 1; }
  if [[ $(jq 'length' <<< "$vnets") == 1 ]]; then
    subnets=$(az network vnet subnet list -g "$rg" --vnet-name "vnet-lzbegin-$zone-$RUN_ID" \
      -o json --subscription "$SUBSCRIPTION_ID")
    table_id=$(jq -er '
      if type != "array" then error("Invalid subnet listing") else . end |
      [.[] | select(.name == "snet-workload")] |
      if length > 1 then error("Duplicate workload subnet") else .[0].routeTable.id // "" end
    ' <<< "$subnets") || { fail "Cannot inspect existing Spoke route tables."; exit 1; }
    if [[ -n "$table_id" ]]; then
      jq -ne --arg id "$table_id" --arg sub "$SUBSCRIPTION_ID" '
        $id | ascii_downcase |
        test("^/subscriptions/" + ($sub | ascii_downcase) +
             "/resourcegroups/[^/]+/providers/microsoft.network/routetables/[^/]+$")
      ' >/dev/null || { fail "Unexpected associated route table ID: $table_id"; exit 1; }
      associated_tables+=("$table_id")
    fi
  fi
done
# None 배포로 목표 상태를 먼저 제거합니다. 관리형 경로 테이블 RG는 이 스크립트의 삭제 대상이 아닙니다.
if [[ " ${present[*]} " == *" $RG_HUB "* ]]; then
  managers=$(az network manager list -g "$RG_HUB" -o json --subscription "$SUBSCRIPTION_ID")
  jq -e --arg id "$AVNM_ID" '
    type == "array" and length <= 1 and all(.[]; (.id | ascii_downcase) == ($id | ascii_downcase))
  ' <<< "$managers" >/dev/null || { fail "Unexpected AVNM in Hub RG; cleanup stopped."; exit 1; }
  if [[ $(jq 'length' <<< "$managers") == 1 ]]; then
    for kind in Routing SecurityAdmin Connectivity; do
      case "$kind" in
        Routing) resource=routingConfigurations/rc-lzbegin-spokes-"$RUN_ID"; command=routing-config ;;
        SecurityAdmin) resource=securityAdminConfigurations/sc-lzbegin-http-"$RUN_ID"; command=security-admin-config ;;
        Connectivity) resource=connectivityConfigurations/cc-lzbegin-hub-spoke-"$RUN_ID"; command=connect-config ;;
      esac
      configurations=$(az network manager "$command" list -g "$RG_HUB" \
        --manager-name "$AVNM" -o json --subscription "$SUBSCRIPTION_ID")
      jq -e --arg id "$AVNM_ID/$resource" '
        type == "array" and length <= 1 and
        all(.[]; (.id | ascii_downcase) == ($id | ascii_downcase))
      ' <<< "$configurations" >/dev/null ||
        { fail "Unexpected $kind configuration; refusing to overwrite its deployment."; exit 1; }
    done
    for kind in Routing SecurityAdmin Connectivity; do
      az network manager post-commit -g "$RG_HUB" -n "$AVNM" \
        --commit-type "$kind" --configuration-ids '[]' --target-locations "$LOCATION" \
        -o none --subscription "$SUBSCRIPTION_ID"
      deployed=false
      for ((attempt=0; attempt<40; attempt++)); do
        status=$(az network manager list-deploy-status -g "$RG_HUB" -n "$AVNM" \
          --deployment-types "$kind" --regions "$LOCATION" -o json \
          --subscription "$SUBSCRIPTION_ID")
        result=$(jq -cer --arg kind "$kind" --arg region "$LOCATION" '
          if type == "array" then .
          elif type == "object" and (.skipToken == null) and (.value | type == "array") then .value
          else error("Invalid deployment status response") end
          | [.[] | select(.deploymentType == $kind and .region == $region)] |
            if length == 0 then "Pending"
            else (sort_by(.commitTime) | last) |
              if .configurationIds == [] and .deploymentStatus == "Failed" then error("AVNM undeployment failed")
              elif .configurationIds == [] and .deploymentStatus == "Deployed" then "Deployed"
              else "Pending" end end
        ' <<< "$status") || { fail "Cannot verify $kind undeployment."; exit 1; }
        if [[ "$result" == Deployed ]]; then deployed=true; break; fi
        sleep 15
      done
      [[ "$deployed" == true ]] ||
        { fail "$kind undeployment did not complete within 10 minutes; rerun cleanup."; exit 1; }
      printf 'Undeployed AVNM %s from %s.\n' "$kind" "$LOCATION"
    done
  fi
fi
# None 배포 성공 뒤 Subnet 반영도 비동기입니다. 만료 전까지 실제 연결이 없어졌는지 다시 조회합니다.
for ((attempt=0; attempt<40; attempt++)); do
  pending=false
  for zone in spokea spokeb; do
    if [[ "$zone" == spokea ]]; then rg="$RG_SPOKEA"; else rg="$RG_SPOKEB"; fi
    [[ " ${present[*]} " == *" $rg "* ]] || continue
    vnets=$(az network vnet list -g "$rg" -o json --subscription "$SUBSCRIPTION_ID")
    jq -e --arg name "vnet-lzbegin-$zone-$RUN_ID" '
      type == "array" and length <= 1 and all(.[]; .name == $name)
    ' <<< "$vnets" >/dev/null || { fail "Unexpected VNet in Spoke RG: $rg"; exit 1; }
    if [[ $(jq 'length' <<< "$vnets") == 1 ]]; then
      subnets=$(az network vnet subnet list -g "$rg" --vnet-name "vnet-lzbegin-$zone-$RUN_ID" \
        -o json --subscription "$SUBSCRIPTION_ID")
      jq -e 'type == "array" and all(.[]; .name == "snet-workload")' <<< "$subnets" >/dev/null ||
        { fail "Unexpected subnet listing: $zone"; exit 1; }
      if ! jq -e 'all(.[]; .routeTable == null)' <<< "$subnets" >/dev/null; then pending=true; fi
    fi
  done
  [[ "$pending" == false ]] && break
  sleep 15
done
[[ "$pending" == false ]] ||
  { fail "AVNM route-table associations did not clear within 10 minutes; inspect deployment and rerun cleanup."; exit 1; }
if [[ ${#associated_tables[@]} -gt 0 ]]; then
  expected=$(printf '%s\n' "${associated_tables[@]}" | jq -Rs 'split("\n") | map(select(length > 0) | ascii_downcase)')
  cleared=false
  for ((attempt=0; attempt<40; attempt++)); do
    tables=$(az resource list --resource-type Microsoft.Network/routeTables -o json \
      --subscription "$SUBSCRIPTION_ID")
    jq -e 'type == "array" and all(.[]; .id | type == "string")' <<< "$tables" >/dev/null ||
      { fail "Cannot inspect route-table inventory."; exit 1; }
    if jq -e --argjson ids "$expected" '
      all(.[]; (.id | ascii_downcase) as $id | ($ids | index($id)) == null)
    ' <<< "$tables" >/dev/null; then cleared=true; break; fi
    sleep 15
  done
  [[ "$cleared" == true ]] ||
    { fail "Previously associated AVNM route tables still exist. Inspect their managed RG; do not delete it blindly."; exit 1; }
fi
# --no-wait는 삭제 요청만 보냅니다. 요청 접수를 완료로 오인하지 않도록 아래에서 실제 부재를 기다립니다.
# 세 RG 삭제는 하나의 원자적 작업이 아닙니다. 중간 실패 후 재실행하면 남아 있는 그룹부터 다시 확인합니다.
for rg in "${present[@]}"; do
  az group delete --name "$rg" --yes --no-wait
done
# 최대 45분, 30초 간격으로 남은 그룹만 조회합니다. 개별 API 호출도 남은 대기 시간으로 제한합니다.
deadline=$((SECONDS + 2700))
for ((attempt=0; attempt<90; attempt++)); do
  remaining=()
  for rg in "${present[@]}"; do
    seconds_left=$((deadline - SECONDS))
    (( seconds_left > 0 )) || { fail "Deletion wait timed out; inspect $rg and rerun cleanup."; exit 1; }
    exists=$(timeout "$seconds_left" az group exists --name "$rg" -o tsv) ||
      { fail "Cannot verify deletion: $rg"; exit 1; }
    case "$exists" in
      true) remaining+=("$rg") ;;
      false) printf 'Deleted: %s\n' "$rg" ;;
      *) fail "Cannot verify deletion: $rg"; exit 1 ;;
    esac
  done
  if [[ ${#remaining[@]} == 0 ]]; then
    printf 'PASS: workshop group deletion complete. Shared resources were not deleted.\n'
    exit 0
  fi
  # 삭제가 확인된 그룹은 다음 반복에서 제외하되, 아직 남은 그룹은 사용자에게 계속 표시합니다.
  present=("${remaining[@]}")
  printf 'Waiting for deletion: %s\n' "${present[*]}"
  seconds_left=$((deadline - SECONDS))
  (( seconds_left > 0 )) || break
  sleep "$((seconds_left < 30 ? seconds_left : 30))"
done
fail "Deletion still pending after 45 minutes: ${present[*]}. Inspect locks/deployments and rerun cleanup."
