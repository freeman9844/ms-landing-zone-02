#!/usr/bin/env bash
# STATE_FILE ZONE SCRIPT_FILE: 신뢰하는 로컬 스크립트를 실습 VM의 Run Command로 실행합니다.
# VM에 직접 SSH하지 않으며, 게스트 명령은 높은 관리 권한으로 실행되므로 입력 파일을 신뢰해야 합니다.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/workshop-common.sh"
source "$(dirname "${BASH_SOURCE[0]}")/workshop-ipam.sh"
[[ $# == 3 && -f "$3" && -r "$3" ]] || { fail "Usage: run-vm.sh STATE_FILE ZONE READABLE_SCRIPT_FILE"; exit 1; }
load_run "$1"
assert_subscription
case "$2" in
  hub) assert_owned_rg "$RG_HUB" ;;
  spokea) assert_owned_rg "$RG_SPOKEA" ;;
  spokeb) assert_owned_rg "$RG_SPOKEB" ;;
  *) fail "Unknown zone: $2"; exit 1 ;;
esac
load_ipam_cidrs
zone_context "$2"
# 여기의 세 번째 인수는 호스트의 파일 경로입니다. 파일 내용이 VM으로 전달되며 파일명 자체가 게스트 명령은 아닙니다.
# 원본은 바꾸지 않고 전송용 임시 파일에 Bash 지정과 종료 코드 출력 trap을 덧붙입니다.
wrapped=$(mktemp /tmp/lzbegin-run.XXXXXX)
trap 'rm -f "$wrapped"' EXIT
{
  # shebang이 반드시 첫 줄이어야 Linux 실행기가 Bash 전용 문법을 올바르게 처리합니다.
  printf '%s\n' '#!/usr/bin/env bash' 'set -Eeuo pipefail' 'trap '\''rc=$?; printf "\n__LZ_EXIT__:%s\n" "$rc"'\'' EXIT'
  cat "$3"
  printf '\n'
} > "$wrapped"
# 45분 timeout은 로컬 대기를 끝낼 뿐 게스트 실행을 취소하지 않습니다. 재시도 전 실제 상태를 확인합니다.
if ! result=$(timeout 2700 az vm run-command invoke --resource-group "$RG" --name "$VM" \
  --command-id RunShellScript --scripts "@$wrapped" -o json); then
  fail "Run Command API failed/timed out. The guest may still be running; inspect it before retrying."
  exit 1
fi
# Linux의 결합 메시지와 별도 ComponentStatus 형식을 같은 stdout/stderr 구조로 정리합니다.
# 구분자 누락·중복·실패 상태는 추측해서 보정하지 않고 검증 불가로 중단합니다.
if ! streams=$(jq -ce '
  .value
  | if type != "array" then error("Expected result array")
    elif length == 1 and .[0].code == "ProvisioningState/succeeded" then
      .[0].message
      | if type != "string" then error("Missing guest output") else . end
      | "Enable succeeded: \n[stdout]\n" as $header
      | if startswith($header) then ltrimstr($header)
        else error("Missing guest stdout header") end
      | split("\n[stderr]\n")
      | if length == 2 then {stdout: .[0], stderr: .[1]}
        else error("Missing or ambiguous guest stderr delimiter") end
    elif length == 2 and
      ([.[].code] | sort) == ["ComponentStatus/StdErr/succeeded", "ComponentStatus/StdOut/succeeded"] then
      {stdout: (.[] | select(.code == "ComponentStatus/StdOut/succeeded") | .message),
       stderr: (.[] | select(.code == "ComponentStatus/StdErr/succeeded") | .message)}
    else error("Unexpected or failed Run Command status") end
  | if (.stdout | type) == "string" and (.stderr | type) == "string" then .
    else error("Invalid guest output streams") end
' <<< "$result"); then
  fail "Invalid Run Command response; guest completion cannot be verified."
  exit 1
fi
out=$(jq -r .stdout <<< "$streams")
err=$(jq -r .stderr <<< "$streams")
# stderr는 진단용으로 보존합니다. API 성공이나 stderr에 있는 성공 마커는 게스트 성공의 증거가 아닙니다.
[[ -z "$err" ]] || printf '%s\n' "$err" >&2
last=$(printf '%s\n' "$out" | tail -n 1)
# 출력이 잘려 마지막 마커가 사라진 경우도 실패입니다. 본문 중간의 성공 문자열을 찾아 대신 신뢰하지 않습니다.
[[ "$last" == __LZ_EXIT__:0 ]] || { printf '%s\n' "$out" >&2; fail "Unverified or failed guest exit: $last"; exit 1; }
# 검증에 사용한 마지막 마커만 제거해 호출자가 순수한 게스트 응답을 비교할 수 있게 합니다.
printf '%s\n' "$out" | sed '$d'
