# 06. AVNM 경로·통신과 Firewall 로그 검증

> 목표 시간 30–45분. AVNM 적용 및 전용 로그 수집에는 추가 시간이 걸릴 수 있습니다.

## 공통 준비

👁️ **설명**

모듈 04에서 **VM보다 먼저** Firewall·전용 진단·AVNM Routing을 배포했고, 모듈 05에서
VM·AVNM Security Admin의 `Always Allow`를 준비했습니다. 이 모듈에서는 경로를 만들거나
NAT를 분리하지 않습니다. Spoke A/B NAT와 해당 Public IP는 처음부터 없어야 합니다.
Hub 관리 VM의 NAT와 Firewall Public IP는 그대로 유지합니다. Azure Firewall과 VM에는
검증 중에도 비용이 발생합니다. 한 블록씩 실행하고 📋 결과가 다르면 **다음 블록으로
넘어가지 마세요**. 재접속 시 [모듈 01의 세션 복구](01-prerequisites.md#세션-재연결-시-변수-복구)를
거쳐 같은 Cloud Shell Bash에서 준비 블록을 다시 실행합니다. 경로를 묻기 전
`ls .workshop-state/`로 기존 파일명을 보여줍니다.
`예:`의 실제 경로를 참고하되 파일이 여러 개라면 현재 실습의 파일을 선택하세요.

🟢 **실행**

<!-- exec:prepare-06 -->
```bash
prepare_validation_session() {
  source scripts/workshop-common.sh || return 1
  source scripts/workshop-safety.sh || return 1
  ensure_state_file || return 1
  load_run "$STATE_FILE" || return 1
  assert_subscription || return 1
  assert_owned_rg "$RG_HUB" || return 1
  assert_owned_rg "$RG_SPOKEA" || return 1
  assert_owned_rg "$RG_SPOKEB"
}
prepare_validation_session
```

📋 **확인**

오류 없이 종료되어야 합니다. 검사는 읽기 전용이며 다른 실습의 구독·RG라면 중단합니다.
`command not found`는 같은 셸에서 이 준비를 다시 실행해야 한다는 뜻입니다.
이 준비에서 Policy 변경 전에 사용하는 경로 검사 함수를 읽습니다.

## 1. 경로·HTTP·Firewall Allow 로그·인터넷 출구 기준 확인

👁️ **설명**

모듈 05의 Security Admin `Always Allow`는 지정한 TCP 8080 흐름에 한해 NSG
평가를 우회합니다. **Hub→A**, **Hub→B**는 Hub 직접 Peering, **A→B**의
요청·반환은 각각의 `/16`을 통해 Firewall을 거칩니다. 세 흐름은 각각 새 HTTP
요청과 예상 서버 응답(`spokea` 또는 `spokeb`)으로 확인합니다. A→B는 성공뿐 아니라
이번 요청 **직전에 기록한 UTC 시각 이후**의 `AZFWNetworkRule` Allow 로그에서
A/B 사설 IP·TCP/8080·이번 Firewall 전체 ID를 대조해야 합니다. 단순 HTTP 성공이나
과거 로그는 Firewall 경유의 증거가 아닙니다. 전용 `AZFWApplicationRule` 진단도
설정되어 있어야 합니다.

이 실행에서 AVNM 구성과 두 Subnet의 `/16`·`/0` 배포, 두 NIC의 Active 유효 경로,
Spoke NAT/Public IP 부재를 함께 검사하므로 같은 항목을 별도 블록에서 반복하지
않습니다. 전파 지연 시 1–2분 기다렸다가 **이 블록 전체**를 다시 실행하세요.
경로가 계속 없으면 모듈 04의 Group·Subnet 연결·Firewall IP 및 모듈 05의
VM/NIC 상태를 확인하고, 수동 경로를 만들어 우회하지 마세요.

Security Admin 구성은 `sc-lzbegin-http-<실행 ID>`, collection은 `spokea`와
`spokeb`입니다. 현재 NIC IP의 `/32`를 대상으로 `spokea/hub-to-a`(200),
`spokeb/hub-to-b`(210), `spokeb/a-to-b`(220)가 `AlwaysAllow`여야 합니다.
모듈 05에서는 임시 Security Admin Deny를 만들지 않습니다. Firewall Deny 실험
중에도 AVNM 규칙은 변경하지 않습니다.

🟢 **실행**

<!-- exec:verify-allowed -->
```bash
bash scripts/verify-extension.sh "$STATE_FILE" allowed
```

📋 **확인**

세 HTTP 흐름과 **새 Allow 로그**, Spoke A/B의 Firewall Public IP egress 및
실제 외부 목적지로의 유효 경로가 함께 PASS여야 합니다.

실제 실행 결과의 **발췌 예시**입니다. 구독·실행 ID와 시각은 실행마다 다릅니다.
반복되는 CLI Preview 경고와 `--ids` 사용 시 구독 옵션 경고는 생략했습니다.

```text
PASS: Enforced Connectivity is effective on both spokes; four forwarded peerings are connected.
PASS: 10.20.1.4 /16 -> VirtualAppliance
PASS: 10.10.1.4 /16 -> VirtualAppliance
PASS: 8.8.8.8 /0 -> VirtualAppliance
PASS: 8.8.8.8 /0 -> VirtualAppliance
PASS: 10.10.1.4 /16 -> VNetPeering
PASS: 10.20.1.4 /16 -> VNetPeering
PASS: effective AVNM rule spokea/hub-to-a (AlwaysAllow)
PASS: effective AVNM rule spokeb/a-to-b (AlwaysAllow)
PASS: HTTP spokea
PASS: HTTP spokeb
PASS: HTTP spokeb
Waiting for current flow logs (1/20).
...
[
  {
    "Action": "Allow",
    "SourceIp": "10.10.1.4",
    "DestinationIp": "10.20.1.4",
    "DestinationPort": "8080",
    "TimeGenerated": "<이번 요청 이후 UTC 시각>",
    "_ResourceId": "<이번 Firewall 전체 resource ID>"
  }
]
PASS: matching Firewall Allow evidence found.
PASS: 104.26.12.205 /0 -> VirtualAppliance
PASS: 172.67.74.152 /0 -> VirtualAppliance
PASS: extension allowed has matching AVNM routes, admin rules, HTTP, Firewall log and egress evidence.
```

`/16`·`/0`의 `VirtualAppliance`는 Spoke 왕복·인터넷 경로가 Firewall을 향함을,
`VNetPeering`은 Hub→Spoke 직접 경로를 뜻합니다. `AlwaysAllow`와 HTTP 응답은
중앙 규칙 적용 및 실제 통신을, 새 `AZFWNetworkRule`의 A→B `Allow`는 Firewall
경유를 증명합니다. `Waiting for current flow logs`는 이번 요청의 로그를
기다리는 정상 동작입니다. 마지막 `/0` 두 줄은 조회한 외부 IP로의 경로이며,
최종 PASS는 egress 검사까지 통과했다는 뜻입니다. 외부 IP 값은 달라질 수 있습니다.

검증 실패는 허용의 증거가 아닙니다. 로그 수집이 늦다면 최대 10분 기다린 뒤
**새 요청을 보내는 검증 전체**를 다시 실행하세요.

## 2. Firewall Policy만 Deny로 바꾸고 복구

👁️ **설명**

AVNM Routing·Security Admin 규칙과 관리/HTTPS egress collection은 그대로 두고
`lab-http` collection의 action만 바꿉니다. 이 워크숍의 유일한 차단·복구 실험입니다.
Firewall Deny는 **A→B**만 차단하며 Hub→A/B는 유지돼야 합니다.
Deny 변경 직전에는 현재 NIC 경로·NAT 부재를 다시 확인합니다. 차단 증거 단계는
이번 흐름의 Firewall 로그와 실제 통신에 집중하고, 복구 후에는 전체 경로·규칙을
다시 검사합니다. Policy 전파 중에는 이전 상태가 잠시 보일 수 있습니다.

### 2-1. `lab-http` Deny

👁️ **설명**

현재 목록에서 정확히 하나의 `lab-http` 위치만 찾습니다. 사전 검사 실패 시 Policy를
바꾸지 마세요. 상태 검사는 Allow인 기준 상태에서 수행합니다.
`validate_effective_nic_routes`는 공통 준비에서 읽으므로, 재접속했다면 **공통 준비만**
다시 실행하세요. 기준 검증의 성공을 변경 허가로 저장하지 않고 현재 NIC 경로를 검사합니다.

🟢 **실행**

<!-- exec:firewall-deny -->
```bash
deny_lab_http() {
  local group index
  validate_effective_nic_routes || return 1
  assert_no_spoke_nat || return 1
  group=$(az network firewall policy rule-collection-group show -g "$RG_HUB" \
    --policy-name "fwpol-lzbegin-$RUN_ID" -n workshop -o json --subscription "$SUBSCRIPTION_ID") || return 1
  index=$(jq -er 'if (.ruleCollections | type) != "array" then error("Expected collection array") else
    [.ruleCollections | to_entries[] | select(.value.name == "lab-http" and .value.action.type == "Allow") | .key] end
    | if length == 1 then .[0] else error("Expected one Allow lab-http collection") end' <<< "$group") || return 1
  az network firewall policy rule-collection-group update -g "$RG_HUB" \
    --policy-name "fwpol-lzbegin-$RUN_ID" -n workshop \
    --set "ruleCollections[$index].action.type=Deny" -o json --subscription "$SUBSCRIPTION_ID"
}
deny_lab_http
```

📋 **확인**

`lab-http.action.type=Deny`이며 다른 collection은 Allow여야 합니다. 실패했거나
변경 응답이 불분명하면 Policy의 현재 상태를 확인하고 **복구 단계로** 이동하세요.

### 2-2. Deny 실제 증거

👁️ **설명**

새 A→B 연결 실패 **및** 방금 시각 이후의 `AZFWNetworkRule` Deny 로그를 함께
요구합니다. Hub→A/B HTTP 및 두 Spoke의 egress는 계속 정상이어야 합니다.
현재 A→B NIC 경로도 확인하지만 기준 단계의 AVNM 구성·Security Admin 규칙 전체
조회는 반복하지 않습니다. 단순 timeout이나 이전 Deny 로그를 방화벽 판정으로 해석하지 마세요.

🟢 **실행**

<!-- exec:verify-denied -->
```bash
bash scripts/verify-extension.sh "$STATE_FILE" denied
```

📋 **확인**

A 사설 IP→B 사설 IP TCP/8080의 **새 Deny**와 정확한 Firewall ID가 일치해야
합니다. 전파·로그 지연 시 최대 10분까지 새 요청으로 재검증합니다. 통과하지
못하더라도 차단 상태로 방치하지 말고 **2-3을 먼저 실행**하세요.

### 2-3. `lab-http` Allow 복구

👁️ **설명**

이전 `index` 변수를 재사용하지 않습니다. 이미 Allow인 경우에도 현재 상태를
조회하여 확인하며, Deny인 경우에만 해당 collection을 되돌립니다. 검증 실패와
무관하게 복구를 수행합니다.

🟢 **실행**

<!-- exec:firewall-restore -->
```bash
restore_lab_http() {
  local group index action
  group=$(az network firewall policy rule-collection-group show -g "$RG_HUB" \
    --policy-name "fwpol-lzbegin-$RUN_ID" -n workshop -o json --subscription "$SUBSCRIPTION_ID") || return 1
  index=$(jq -er 'if (.ruleCollections | type) != "array" then error("Expected collection array") else
    [.ruleCollections | to_entries[] | select(.value.name == "lab-http") | .key] end
    | if length == 1 then .[0] else error("Ambiguous lab-http collection") end' <<< "$group") || return 1
  action=$(jq -er --argjson index "$index" '.ruleCollections[$index].action.type' <<< "$group") || return 1
  if [[ "$action" == Allow ]]; then
    printf 'lab-http is already Allow\n'
  elif [[ "$action" == Deny ]]; then
    az network firewall policy rule-collection-group update -g "$RG_HUB" \
      --policy-name "fwpol-lzbegin-$RUN_ID" -n workshop \
      --set "ruleCollections[$index].action.type=Allow" -o json --subscription "$SUBSCRIPTION_ID"
  else
    fail "Unexpected lab-http action: $action"
  fi
}
restore_lab_http
```

📋 **확인**

`lab-http`가 Allow로 돌아와야 합니다. API 조회/업데이트 실패 시 원인을 해결하고
**이 복구 블록만 다시 실행**하세요. 다른 규칙을 삭제하거나 NSG를 열어 우회하지 않습니다.

### 2-4. 새 Allow 및 전체 복구 증거

🟢 **실행**

<!-- exec:verify-restored -->
```bash
bash scripts/verify-extension.sh "$STATE_FILE" restored
```

📋 **확인**

Hub→A/B와 A→B HTTP, A→B의 **새 Allow 로그**, NIC 왕복 `/16`·`/0`,
두 Spoke의 Firewall egress 및 Spoke NAT 부재가 모두 PASS여야 합니다.
배포/로그 지연이 있다면 기다리고 **새 요청으로** 다시 검증합니다.

| 단계 | Security Admin | AVNM `/16`·`/0` | A→B HTTP | 새 Firewall 로그 |
|---|---|---|---|---|
| allowed | Always Allow | Firewall | 성공 | Allow |
| denied | 기준 단계에서 확인 | A→B 현재 NIC 경로 | 차단 | Deny |
| restored | Always Allow | Firewall | 재성공 | Allow |

## Portal 확인과 트러블슈팅

👁️ **설명**

**Virtual Network Manager → Routing / Deployments**에서 두 Group에 대한 배포와
적용 상태를 확인하고, **Spoke Subnet → Route table**에서 연결을 확인합니다.
**NIC → Effective routes**에서는 실제 Active `/16`·`/0`과 next hop Firewall
사설 IP를 확인합니다. AVNM 관리형 테이블의 이름이나 RG를 미리 정해 검색하지 않습니다.
**Log Analytics → Logs → AZFWNetworkRule**에서는 `TimeGenerated`,
`SourceIp`, `DestinationIp`, `DestinationPort`, `Action`, `_ResourceId`를
검증 직전 UTC 시각과 대조합니다. 전용 로그가 없으면 진단 설정의 workspace,
`Dedicated`, `AZFWNetworkRule`·`AZFWApplicationRule` 범주를 검사합니다.

| 증상 | 조치 |
|---|---|
| Subnet 경로는 있는데 NIC 경로 없음 | AVNM 비동기 적용을 기다리고 두 Routing Group/대상 Subnet과 배포 상태 재확인 |
| 한 방향 `/16` 또는 `/0`만 보임 | 반대 Group·collection·rule 및 next hop IP 확인; HTTP를 성공으로 간주하지 않기 |
| HTTP 성공인데 로그 없음 | 이번 Firewall ID·전용 테이블·시각·진단 범주 확인, 로그 수집 대기 후 새 요청 |
| `api.loganalytics.io` DNS 오류·조회 실패 | Cloud Shell 연결 복구; 빈 결과나 Deny로 오인하지 않기 |
| A→B 차단인데 Hub→A/B도 실패 | AVNM Security Admin 배포/규칙 또는 VM 서비스를 모듈 05에서 재확인 |
| 외부 IP 조회 실패 | DNS·Firewall HTTPS FQDN 허용 규칙·외부 서비스 상태 확인; NAT/경로 임의 변경 금지 |
| Spoke NAT 또는 Public IP 발견 | 계획 밖 자원으로 간주해 중단; 소유권·참조를 확인하고 모듈 07 정리 절차 참조 |

## 완료 체크

- 두 Spoke Subnet의 AVNM 경로와 **실제 NIC의 `/16`·`/0`**이 Firewall을 가리킵니다.
- Spoke NAT/PIP는 없고 Hub NAT는 유지됩니다. Hub→A/B, A→B HTTP와 Allow→Deny→Allow의 새 로그를 확인했습니다.
- 두 Spoke의 인터넷 출구가 Firewall Public IP이며 `lab-http`는 Allow로 복구됐습니다.

## 다음 단계

- [이전: VM과 AVNM Security Admin](05-firewall.md)
- [다음: 전체 정리](07-cleanup-production.md)
