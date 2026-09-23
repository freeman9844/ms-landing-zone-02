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
