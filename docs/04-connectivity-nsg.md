# 04. 중앙 Firewall과 AVNM Routing

> 목표 시간 35–50분. Firewall 배포와 AVNM 전파에는 추가 시간이 걸릴 수 있습니다. **VM 생성 전** 완료하는 모듈입니다.

## 공통 준비

👁️ **설명**

모듈 03에서 AVNM의 `Connectivity`·`SecurityAdmin`·`Routing` 범위, Hub↔Spoke
연결 및 서로 겹치지 않는 A/B Routing Group을 준비했습니다. 이 모듈은 Hub에
Firewall Standard·Policy·로그를 먼저 설치하고, 네 Peering의 전달 허용을 확인한 다음
AVNM Peering enforcement와 Spoke A/B의 경로를 배포합니다. **Spoke NAT Gateway/Public IP나 VM은
만들지 않습니다.** Hub 관리 VM의 NAT는 다음 모듈에서 배포하며, 이 모듈에서는
Hub NAT를 만들거나 기존 것을 분리하지 않습니다.

모듈 01의 `STATE_FILE`을 사용합니다. 재접속했다면
[세션 복구](01-prerequisites.md#세션-재연결-시-변수-복구) 후 같은 Cloud Shell
Bash에서 준비 블록을 다시 실행하세요. 경로를 입력해야 한다면
먼저 `ls .workshop-state/`로 파일명을 보여줍니다. 입력할 때는
`.workshop-state/<실행 ID>.json`의 앞 점도 포함합니다. 각 **🟢 실행 → 📋 확인**
후 다음 블록으로 이동하세요. 오류나 다른 ID/상태가 나오면 **다음 단계로 진행하지
마세요**. 함수는 실패를 반환하지만 Cloud Shell 전체를 종료하지 않습니다.
공통 준비에서 안전 검사 함수도 함께 불러옵니다. 재접속하면 준비 블록만 다시
실행한 뒤 이전에 만든 자원을 재생성하지 않고 다음 단계를 계속할 수 있습니다.
2-13과 5절에서 이전 **읽기 전용 검사 함수**가 재접속으로 없어졌다면
각각 2-11과 4-9의 검사 블록을 다시 실행하세요. 생성 블록을
재실행해서 함수를 복구하지 마세요.

🟢 **실행**

<!-- exec:prepare-04 -->
```bash
prepare_routing_session() {
  source scripts/workshop-common.sh || return 1
  source scripts/workshop-safety.sh || return 1
  ensure_state_file || return 1
  load_run "$STATE_FILE" || return 1
  assert_subscription || return 1
  assert_owned_rg "$RG_HUB" || return 1
  assert_owned_rg "$RG_SPOKEA" || return 1
  assert_owned_rg "$RG_SPOKEB"
}
prepare_routing_session
```

📋 **확인**

오류 없이 종료됩니다. `ROUTE_GROUP_A_ID`/`ROUTE_GROUP_B_ID`는 상태에서 파생한
**서로 다른 전체 Group ID**입니다. 이후 블록은 같은 셸에서 실행합니다.

## 1. CLI와 배포 전 점검

👁️ **설명**

Provider는 구독의 자원 종류, 확장은 Cloud Shell의 명령을 준비합니다. 아직 유료
자원을 배포하지 않습니다. AVNM Routing CLI는 `virtual-network-manager` 확장
**3.0.2의 preview**이며, 이 교재의 구문은 해당 버전 기준입니다. 관리자 생성에
사용한 ARM `2025-01-01`은 Routing 범위를 지원합니다.

### 1-1. 로그 Provider 등록

🟢 **실행**

<!-- exec:register-logs -->
```bash
az provider register --namespace Microsoft.OperationalInsights --wait --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

등록에 실패하면 1-5의 사전 점검을 통과할 수 없습니다.

### 1-2. Firewall CLI 확장

🟢 **실행**

<!-- exec:install-firewall-cli -->
```bash
az extension add --name azure-firewall --version 2.2.1 --upgrade --yes
```

📋 **확인**

`azure-firewall 2.2.1`입니다. 다운로드가 제한되면 임의 버전으로 바꾸지 마세요.

### 1-3. 로그 조회 확장

🟢 **실행**

<!-- exec:install-logs-cli -->
```bash
az extension add --name log-analytics --upgrade --yes
```

📋 **확인**

확장이 준비됩니다. 실제 로그 조회는 모듈 06에서 트래픽을 발생시킨 후에 합니다.

### 1-4. AVNM Routing CLI 확장 설치/업그레이드

👁️ **설명**

모듈 03에서 확장을 설치했더라도 Cloud Shell 환경이 바뀌었을 수 있습니다.
Routing Configuration·rule collection·rule 명령을 제공하는 확인된
`virtual-network-manager` **3.0.2**를 명시적으로 준비합니다. CLI 확장만
변경하며 Azure 자원은 만들지 않습니다.

🟢 **실행**

<!-- exec:install-avnm-routing-cli -->
```bash
az extension add --name virtual-network-manager --version 3.0.2 --upgrade --yes
```

📋 **확인**

확장 설치에 실패하면 Routing 명령을 시도하지 마세요. 다음 사전 점검에서
설치된 버전을 다시 확인합니다.

### 1-5. VM 없이 Firewall 사전 점검

👁️ **설명**

`--firewall`은 VM 존재·VM 용량을 요구하지 않고 리전·Provider를 확인합니다.
다음 모듈에서 VM 용량을 별도로 확인합니다.

🟢 **실행**

<!-- exec:firewall-preflight -->
```bash
check_firewall_preflight() {
  [[ "$LOCATION" == koreacentral ]] || { fail "This workshop deploys to koreacentral only."; return 1; }
  [[ "$(az extension show --name virtual-network-manager --query version -o tsv)" == 3.0.2 ]] ||
    { fail "Install the virtual-network-manager CLI extension 3.0.2 before routing."; return 1; }
  bash scripts/preflight.sh "$STATE_FILE" --firewall
}
check_firewall_preflight
```

📋 **확인**

`PASS: Firewall provider preflight`입니다. 사전 점검 실패는 리소스 부재의 증거가
아닙니다. 원인을 해결한 후에만 진행하세요.

## 2. VM보다 먼저 Firewall·Policy·로그 설치

👁️ **설명**

순서는 **workspace → Firewall Public IP → Policy → Firewall → Hub
AzureFirewallSubnet/IP 구성 → Policy 규칙 → 전용 진단**입니다. 여기부터
Firewall Standard·Public IP·Log Analytics에 **배포 중에도 비용**이 발생합니다.
[비용 안내](01-prerequisites.md#1-계정과-비용-확인)를 확인하고, 중단할 때는
[정리 절차](07-cleanup-production.md)를 따르세요. 실패한 생성 명령을 무조건
재실행하지 말고 실제 리소스의 ID/상태를 조회합니다.

### 2-1. Log Analytics workspace

🟢 **실행**

<!-- exec:firewall-workspace -->
```bash
az monitor log-analytics workspace create -g "$RG_HUB" -n "log-lzbegin-$RUN_ID" \
  -l "$LOCATION" --sku PerGB2018 --retention-time 30 \
  --tags workshop=lz-beginner environment=lab "runId=$RUN_ID" managedBy=workshop \
  -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

이번 Hub RG의 workspace이며 보존 기간은 30일입니다. workspace 생성만으로
Firewall 로그가 수집되지는 않습니다.

### 2-2. Firewall 전용 Public IP

🟢 **실행**

<!-- exec:firewall-public-ip -->
```bash
az network public-ip create -g "$RG_HUB" -n "pip-lzbegin-fw-$RUN_ID" \
  -l "$LOCATION" --sku Standard --allocation-method Static --version IPv4 \
  --tags workshop=lz-beginner environment=lab "runId=$RUN_ID" managedBy=workshop \
  -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

Standard·Static IP이며 Spoke VM/NAT용 IP가 아닙니다.

### 2-3. Firewall Policy

🟢 **실행**

<!-- exec:firewall-policy -->
```bash
az network firewall policy create -g "$RG_HUB" -n "fwpol-lzbegin-$RUN_ID" \
  -l "$LOCATION" --sku Standard --threat-intel-mode Alert \
  --tags workshop=lz-beginner environment=lab "runId=$RUN_ID" managedBy=workshop \
  -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

Policy는 `Standard`입니다. `Alert`만으로 통신이 허용되는 것은 아닙니다.

### 2-4. Standard Firewall

👁️ **설명**

Policy를 연결하지만 아직 IP 구성은 없습니다. `timeout 2700`은 CLI 대기만
끝내며 Azure 작업을 취소하지 않습니다.

🟢 **실행**

<!-- exec:firewall-create -->
```bash
timeout 2700 az network firewall create -g "$RG_HUB" -n "fw-lzbegin-$RUN_ID" \
  -l "$LOCATION" --sku AZFW_VNet --tier Standard \
  --firewall-policy "fwpol-lzbegin-$RUN_ID" \
  --tags workshop=lz-beginner environment=lab "runId=$RUN_ID" managedBy=workshop \
  -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

이번 Policy ID를 참조합니다. timeout/`Updating` 시 자원 상태를 조회하고
완료 전에는 다음 쓰기 작업을 하지 마세요.

### 2-5. Hub의 예약 Firewall Subnet과 IP 연결

👁️ **설명**

모듈 02의 `AzureFirewallSubnet`과 방금 만든 Public IP를 `primary`로 묶습니다.
Firewall 사설 IP는 뒤에서 **조회한 실제 값만** next hop으로 사용합니다.
이 작업은 몇 분 이상 걸릴 수 있습니다.

🟢 **실행**

<!-- exec:firewall-ip-config -->
```bash
timeout 2700 az network firewall ip-config create -g "$RG_HUB" \
  --firewall-name "fw-lzbegin-$RUN_ID" -n primary \
  --public-ip-address "pip-lzbegin-fw-$RUN_ID" \
  --vnet-name "vnet-lzbegin-hub-$RUN_ID" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

`primary` IP 구성이 생깁니다. 오류/timeout은 성공으로 취급하지 않습니다.

### 2-6. Firewall·Policy·IP 완료 확인

👁️ **설명**

IP는 Hub의 `10.0.2.0/26` 안이어야 합니다. 상태/정책/전체 ID가 다른 경우
규칙이나 경로 배포를 시작하지 마세요.

🟢 **실행**

<!-- exec:inspect-firewall -->
```bash
inspect_firewall_before_rules() {
  local fw ip
  fw=$(az network firewall show -g "$RG_HUB" -n "fw-lzbegin-$RUN_ID" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_HUB/providers/Microsoft.Network/azureFirewalls/fw-lzbegin-$RUN_ID" \
    --arg policy "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_HUB/providers/Microsoft.Network/firewallPolicies/fwpol-lzbegin-$RUN_ID" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and
    .provisioningState == "Succeeded" and
    (.firewallPolicy.id | ascii_downcase) == ($policy | ascii_downcase) and
    (.ipConfigurations | type == "array" and length == 1) and
    (.ipConfigurations[0].privateIPAddress | type == "string" and length > 0)
  ' <<< "$fw" >/dev/null || { fail "Firewall ID, policy or provisioning is not ready."; return 1; }
  ip=$(jq -er '.ipConfigurations[0].privateIPAddress' <<< "$fw") || return 1
  assert_ipv4_in_subnet "$ip" 10.0.2.0/26 || return 1
  printf 'PASS: Firewall Succeeded; private IP %s\n' "$ip"
}
inspect_firewall_before_rules
```

📋 **확인**

`PASS`와 실제 사설 IP가 나옵니다. 아직 VM이 없어 NIC 유효 경로는 확인할 수 없습니다.

### 2-7. Policy collection group

👁️ **설명**

`workshop` group 우선순위는 200입니다. 하위 collection의 100/200/300은
**group 내부의 별도 우선순위**입니다.

🟢 **실행**

<!-- exec:firewall-rule-group -->
```bash
az network firewall policy rule-collection-group create -g "$RG_HUB" \
  --policy-name "fwpol-lzbegin-$RUN_ID" -n workshop --priority 200 \
  -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

group만 생성되며 세 collection은 다음 단계에서 각각 추가합니다.

### 2-8. VM agent 관리 HTTPS 허용

👁️ **설명**

Spoke의 기본 인터넷 출구를 `/0 → Firewall`로 바꾸기 전에 TCP 443
`AzureCloud`를 허용합니다. 이 서비스 태그는 **이 tenant 전용이 아닙니다**.
운영 정책으로 복사하지 마세요.

🟢 **실행**

<!-- exec:firewall-management-rule -->
```bash
az network firewall policy rule-collection-group collection add-filter-collection \
  -g "$RG_HUB" --policy-name "fwpol-lzbegin-$RUN_ID" --rcg-name workshop -n management \
  --collection-priority 100 --action Allow --rule-name azure-management \
  --rule-type NetworkRule --ip-protocols TCP \
  --source-addresses 10.10.1.0/24 10.20.1.0/24 \
  --destination-addresses AzureCloud --destination-ports 443 \
  -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

두 Spoke workload Subnet에서 AzureCloud TCP/443만 관리 예외로 허용합니다.

### 2-9. A → B HTTP 실험 규칙

👁️ **설명**

아직 VM/NIC가 없으므로 출발지 `10.10.1.0/24`와 목적지
`10.20.1.0/24`의 **TCP/8080만** 최초 허용합니다. 다른 포트·Spoke 전체
주소 공간을 열지 않습니다. 모듈 05에서 VM이 생성된 뒤 실제 NIC IP로
규칙을 좁히려면 현재 collection·규칙을 확인한 후 Policy를 갱신해야 합니다.
기준 검증에서는 이 CIDR 규칙을 유지합니다. Firewall은 상태를 추적하지만,
응답용 B→A의 **네트워크 경로**는 별도로 필요합니다.

🟢 **실행**

<!-- exec:firewall-http-rule -->
```bash
az network firewall policy rule-collection-group collection add-filter-collection \
  -g "$RG_HUB" --policy-name "fwpol-lzbegin-$RUN_ID" --rcg-name workshop -n lab-http \
  --collection-priority 200 --action Allow --rule-name spokea-to-spokeb \
  --rule-type NetworkRule --ip-protocols TCP \
  --source-addresses 10.10.1.0/24 --destination-addresses 10.20.1.0/24 \
  --destination-ports 8080 -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

`lab-http`가 Allow·200·TCP/8080이며 A→B 방향입니다. 모듈 06에서
**이 collection만** Deny/Allow로 전환합니다.

### 2-10. 외부 출구 확인용 FQDN

👁️ **설명**

인터넷 전체를 열지 않고 `api.ipify.org`의 HTTPS만 허용합니다.
Azure Firewall의 FQDN 검사와 기록은 AVNM Routing으로 대체되지 않습니다.

🟢 **실행**

<!-- exec:firewall-egress-rule -->
```bash
az network firewall policy rule-collection-group collection add-filter-collection \
  -g "$RG_HUB" --policy-name "fwpol-lzbegin-$RUN_ID" --rcg-name workshop -n egress-check \
  --collection-priority 300 --action Allow --rule-name public-ip-check \
  --rule-type ApplicationRule --source-addresses 10.10.1.0/24 10.20.1.0/24 \
  --protocols Https=443 --target-fqdns api.ipify.org \
  -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

세 collection은 독립적입니다. 앞선 Policy 변경이 실패했다면 다음
`add-filter-collection`을 실행하지 마세요. 이미 저장된 내용부터 확인합니다.

### 2-11. 저장된 Policy 규칙 조회

🟢 **실행**

<!-- exec:inspect-firewall-rules -->
```bash
check_firewall_policy_rules() {
  local group
  group=$(az network firewall policy rule-collection-group show -g "$RG_HUB" \
    --policy-name "fwpol-lzbegin-$RUN_ID" -n workshop \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_HUB/providers/Microsoft.Network/firewallPolicies/fwpol-lzbegin-$RUN_ID/ruleCollectionGroups/workshop" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and
    .provisioningState == "Succeeded" and .priority == 200 and
    (.ruleCollections | type == "array" and length == 3) and
    ([.ruleCollections[].name] | sort) == (["management","lab-http","egress-check"] | sort) and
    all(.ruleCollections[]; .action.type == "Allow") and
    ([.ruleCollections[] | select(.name == "management")] |
      length == 1 and .[0].priority == 100 and .[0].rules[0].name == "azure-management") and
    ([.ruleCollections[] | select(.name == "lab-http")] |
      length == 1 and .[0].priority == 200 and
      (.[0].rules | type == "array" and length == 1) and
      (.[0].rules[0] |
        .name == "spokea-to-spokeb" and .ruleType == "NetworkRule" and
        .sourceAddresses == ["10.10.1.0/24"] and
        .destinationAddresses == ["10.20.1.0/24"] and
        .destinationPorts == ["8080"] and .ipProtocols == ["TCP"])) and
    ([.ruleCollections[] | select(.name == "egress-check")] |
      length == 1 and .[0].priority == 300 and
      (.[0].rules | type == "array" and length == 1) and
      (.[0].rules[0] |
        .name == "public-ip-check" and .ruleType == "ApplicationRule" and
        .targetFqdns == ["api.ipify.org"]))
  ' <<< "$group" >/dev/null || { fail "Policy collections or HTTP/FQDN rules are incomplete."; return 1; }
  printf 'PASS: Policy workshop group and three Allow collections\n'
}
check_firewall_policy_rules
```

📋 **확인**

group 우선순위 200, `management`·`lab-http`·`egress-check` 각각
100/200/300·Allow, 위 주소·포트·FQDN이 저장돼 있어야 합니다.
오류 후 `already exists`면 이름만 보고 다시 추가하지 말고 실제 규칙을 비교하세요.

### 2-12. 전용 Firewall 진단 활성화

👁️ **설명**

`AZFWNetworkRule`과 `AZFWApplicationRule` category를 확인한 뒤 이번
workspace로 전송합니다. `Dedicated`는 `AzureDiagnostics` 대신 전용
로그 테이블을 사용하는 옵션입니다.

🟢 **실행**

<!-- exec:firewall-diagnostics -->
```bash
fw_id=$(az network firewall show -g "$RG_HUB" -n "fw-lzbegin-$RUN_ID" \
  --query id -o tsv --subscription "$SUBSCRIPTION_ID") &&
law_id=$(az monitor log-analytics workspace show -g "$RG_HUB" -n "log-lzbegin-$RUN_ID" \
  --query id -o tsv --subscription "$SUBSCRIPTION_ID") &&
assert_resource_id "$fw_id" \
  "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_HUB/providers/Microsoft.Network/azureFirewalls/fw-lzbegin-$RUN_ID" &&
assert_resource_id "$law_id" \
  "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_HUB/providers/Microsoft.OperationalInsights/workspaces/log-lzbegin-$RUN_ID" &&
categories=$(az monitor diagnostic-settings categories list --resource "$fw_id" \
  -o json --subscription "$SUBSCRIPTION_ID") &&
jq -e '(.value | type == "array") and
  ([.value[].name] | index("AZFWNetworkRule") != null and index("AZFWApplicationRule") != null)' \
  <<< "$categories" >/dev/null &&
az monitor diagnostic-settings create --name workshop --resource "$fw_id" \
  --workspace "$law_id" --export-to-resource-specific true \
  --logs '[{"category":"AZFWNetworkRule","enabled":true},{"category":"AZFWApplicationRule","enabled":true}]' \
  -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

두 category가 활성화됩니다. 설정 성공은 아직 실제 패킷/로그의 증거가 아닙니다.

### 2-13. 경로 배포 전 Firewall 최종 검사

👁️ **설명**

읽기 전용 안전 함수가 Firewall의 전체 ID, 완료 상태, Policy, 사설 IP,
이번 workspace와 전용 진단, 세 Allow collection과 관리 규칙을 다시 검사합니다.

🟢 **실행**

<!-- exec:firewall-ready -->
```bash
check_firewall_ready() {
  local fw_ip policy workspace public_ip base
  base="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_HUB/providers"
  policy=$(az network firewall policy show -g "$RG_HUB" -n "fwpol-lzbegin-$RUN_ID" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "$base/Microsoft.Network/firewallPolicies/fwpol-lzbegin-$RUN_ID" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and
    .provisioningState == "Succeeded"
  ' <<< "$policy" >/dev/null || { fail "Firewall Policy ID/state not ready."; return 1; }
  workspace=$(az monitor log-analytics workspace show -g "$RG_HUB" -n "log-lzbegin-$RUN_ID" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "$base/Microsoft.OperationalInsights/workspaces/log-lzbegin-$RUN_ID" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and
    .provisioningState == "Succeeded" and .location == "koreacentral"
  ' <<< "$workspace" >/dev/null || { fail "Log workspace ID/state not ready."; return 1; }
  public_ip=$(az network public-ip show -g "$RG_HUB" -n "pip-lzbegin-fw-$RUN_ID" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "$base/Microsoft.Network/publicIPAddresses/pip-lzbegin-fw-$RUN_ID" '
    (.id | ascii_downcase) == ($id | ascii_downcase) and
    .provisioningState == "Succeeded" and .publicIPAllocationMethod == "Static" and
    .sku.name == "Standard"
  ' <<< "$public_ip" >/dev/null || { fail "Firewall Public IP ID/state not ready."; return 1; }
  check_firewall_policy_rules || return 1
  fw_ip=$(firewall_ready_ip) || return 1
  printf 'PASS: Firewall Policy, diagnostics, private IP %s\n' "$fw_ip"
}
check_firewall_ready
```

📋 **확인**

`PASS`가 아니면 Peering·Routing을 변경하지 마세요. 특히 `Updating`/
`FirewallPolicyUpdateFailed`는 규칙 저장 상태와 Activity Log를 확인한 뒤 복구합니다.

## 3. 네 방향 Hub↔Spoke Peering 전달 허용

👁️ **설명**

AVNM은 Connectivity Peering을 만들지만 Firewall로 들어온 패킷을
다른 VNet으로 전달하려면 **기존 네 방향**의 `allowForwardedTraffic`도
켜야 합니다. AVNM 이름을 추측하지 않고 **remote VNet의 전체 ID**로 정확히
한 Peering을 찾습니다. 직접 A↔B Peering, Gateway 공유 및 새 Peering은
만들지 않습니다. 이 설정만으로 경로나 Firewall Allow가 생기지 않습니다.

### 3-1. Hub → Spoke A

🟢 **실행**

<!-- exec:forward-hub-to-spokea -->
```bash
peering_name=$(peering_for_forwarding "$RG_HUB" "vnet-lzbegin-hub-$RUN_ID" \
  "$RG_SPOKEA" "vnet-lzbegin-spokea-$RUN_ID") &&
az network vnet peering update -g "$RG_HUB" --vnet-name "vnet-lzbegin-hub-$RUN_ID" \
  -n "$peering_name" --set allowForwardedTraffic=true -o json --subscription "$SUBSCRIPTION_ID" &&
assert_peering_forwarded "$RG_HUB" "vnet-lzbegin-hub-$RUN_ID" \
  "$RG_SPOKEA" "vnet-lzbegin-spokea-$RUN_ID" "$peering_name"
```

📋 **확인**

Hub에서 A를 향한 Connected Peering 하나만 수정하고 PASS가 나옵니다.

### 3-2. Spoke A → Hub

🟢 **실행**

<!-- exec:forward-spokea-to-hub -->
```bash
peering_name=$(peering_for_forwarding "$RG_SPOKEA" "vnet-lzbegin-spokea-$RUN_ID" \
  "$RG_HUB" "vnet-lzbegin-hub-$RUN_ID") &&
az network vnet peering update -g "$RG_SPOKEA" --vnet-name "vnet-lzbegin-spokea-$RUN_ID" \
  -n "$peering_name" --set allowForwardedTraffic=true -o json --subscription "$SUBSCRIPTION_ID" &&
assert_peering_forwarded "$RG_SPOKEA" "vnet-lzbegin-spokea-$RUN_ID" \
  "$RG_HUB" "vnet-lzbegin-hub-$RUN_ID" "$peering_name"
```

📋 **확인**

A에서 Hub 방향도 `allowForwardedTraffic=true`입니다.

### 3-3. Hub → Spoke B

🟢 **실행**

<!-- exec:forward-hub-to-spokeb -->
```bash
peering_name=$(peering_for_forwarding "$RG_HUB" "vnet-lzbegin-hub-$RUN_ID" \
  "$RG_SPOKEB" "vnet-lzbegin-spokeb-$RUN_ID") &&
az network vnet peering update -g "$RG_HUB" --vnet-name "vnet-lzbegin-hub-$RUN_ID" \
  -n "$peering_name" --set allowForwardedTraffic=true -o json --subscription "$SUBSCRIPTION_ID" &&
assert_peering_forwarded "$RG_HUB" "vnet-lzbegin-hub-$RUN_ID" \
  "$RG_SPOKEB" "vnet-lzbegin-spokeb-$RUN_ID" "$peering_name"
```

📋 **확인**

Hub에서 B 방향도 true입니다.

### 3-4. Spoke B → Hub

🟢 **실행**

<!-- exec:forward-spokeb-to-hub -->
```bash
peering_name=$(peering_for_forwarding "$RG_SPOKEB" "vnet-lzbegin-spokeb-$RUN_ID" \
  "$RG_HUB" "vnet-lzbegin-hub-$RUN_ID") &&
az network vnet peering update -g "$RG_SPOKEB" --vnet-name "vnet-lzbegin-spokeb-$RUN_ID" \
  -n "$peering_name" --set allowForwardedTraffic=true -o json --subscription "$SUBSCRIPTION_ID" &&
assert_peering_forwarded "$RG_SPOKEB" "vnet-lzbegin-spokeb-$RUN_ID" \
  "$RG_HUB" "vnet-lzbegin-hub-$RUN_ID" "$peering_name"
```

📋 **확인**

네 방향이 모두 Connected/forwarding=true여야 합니다.

### 3-5. 네 방향 확인 후 피어링 강제 설정

👁️ **설명**

모듈 03에서는 피어링을 수정할 수 있게 Connectivity를 배포했습니다. 이제 네 방향
`allowForwardedTraffic=true`를 확인한 다음에만 AVNM 피어링 강제를 설정합니다.
강제 구성을 재배포하면 AVNM이 관리하는 피어링을 Portal이나 CLI에서 직접 변경·삭제할
수 없습니다. 다시 수정해야 한다면 `Unenforced`로 변경하고 재배포한 뒤 작업하세요.

🟢 **실행**

<!-- exec:enforce-peering -->
```bash
assert_forwarded_peerings &&
current=$(az network manager connect-config show -g "$RG_HUB" \
  --network-manager-name "$AVNM" --configuration-name "$CONNECTIVITY_CONFIG" \
  -o json --subscription "$SUBSCRIPTION_ID") &&
jq -e --arg id "$CONNECTIVITY_CONFIG_ID" '
  (.id | ascii_downcase) == ($id | ascii_downcase) and
  .provisioningState == "Succeeded" and .connectivityTopology == "HubAndSpoke"
' <<< "$current" >/dev/null &&
updated=$(az network manager connect-config update -g "$RG_HUB" \
    --network-manager-name "$AVNM" --configuration-name "$CONNECTIVITY_CONFIG" \
    --connect-capabilities '{"connectedGroupAddressOverlap":"Allowed","connectedGroupPrivateEndpointsScale":"Standard","peeringEnforcement":"Enforced"}' \
    -o json --subscription "$SUBSCRIPTION_ID") &&
jq -e --arg id "$CONNECTIVITY_CONFIG_ID" '
  (.id | ascii_downcase) == ($id | ascii_downcase) and
  .provisioningState == "Succeeded" and
  .connectivityCapabilities.connectedGroupAddressOverlap == "Allowed" and
  .connectivityCapabilities.connectedGroupPrivateEndpointsScale == "Standard" and
  .connectivityCapabilities.peeringEnforcement == "Enforced"
' <<< "$updated" >/dev/null &&
printf 'PASS: peeringEnforcement=Enforced saved; redeploy Connectivity next\n'
```

📋 **확인**

`peeringEnforcement=Enforced`가 저장됐습니다. 아직 **설정만 변경**했으므로
다음 단계에서 반드시 Connectivity를 재배포합니다.

### 3-6. 강제 설정 재배포

🟢 **실행**

<!-- exec:commit-enforced-connectivity -->
```bash
assert_forwarded_peerings &&
current=$(az network manager connect-config show -g "$RG_HUB" \
  --network-manager-name "$AVNM" --configuration-name "$CONNECTIVITY_CONFIG" \
  -o json --subscription "$SUBSCRIPTION_ID") &&
jq -e --arg id "$CONNECTIVITY_CONFIG_ID" '
  (.id | ascii_downcase) == ($id | ascii_downcase) and
  .provisioningState == "Succeeded" and
  .connectivityCapabilities.peeringEnforcement == "Enforced"
' <<< "$current" >/dev/null &&
az network manager post-commit -g "$RG_HUB" --network-manager-name "$AVNM" \
  --commit-type Connectivity --configuration-ids "$CONNECTIVITY_CONFIG_ID" \
  --target-locations "$LOCATION" --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

재배포 요청이 접수됐습니다. 기존 배포와 구성 ID가 같으므로 `Deployed`만으로
이번 변경의 적용을 판단하지 않습니다.

### 3-7. Spoke 적용과 피어링 유지 확인

🟢 **실행**

<!-- exec:inspect-enforced-connectivity -->
```bash
assert_enforced_connectivity
```

📋 **확인**

`PASS`가 나오면 최신 Connectivity 배포가 `Deployed`이고 양쪽 Spoke effective 구성에서
`peeringEnforcement=Enforced`가 확인됩니다. 네 방향 피어링은 모두 예상 remote ID,
`Connected`, `Forwarded=True`를 유지합니다. 적용 중이면 이 **읽기 전용 블록**만
잠시 후 다시 실행하세요. 실패한 상태로 Routing에 진입하지 않습니다.

## 4. Spoke별 AVNM Routing 구성

👁️ **설명**

한 Routing Configuration 안의 **서로 다른 A/B collection**을 각각
`ROUTE_GROUP_A_ID`/`ROUTE_GROUP_B_ID`에 적용합니다. 같은 Group에 양쪽
`/16`이나 충돌하는 `/0`을 넣지 않습니다. AVNM이 배포 시 관리형 route
table을 만들어 Subnet에 연결하므로 수동 route table을 생성하지 않습니다.
기존 테이블을 자동 채택하지 않고 AVNM 기본 관리 방식만 사용합니다.
`/16`은 상대 Spoke 요청/반환, `/0`은 Spoke의 인터넷 출구를 담당하며
모든 next hop은 **현재 Firewall 사설 IP**입니다.

| 대상 collection / Group | 목적지 1 | 목적지 2 | 두 next hop |
|---|---|---|---|
| `spokea` / A 전용 | `10.20.0.0/16` | `0.0.0.0/0` | Firewall 사설 IP |
| `spokeb` / B 전용 | `10.10.0.0/16` | `0.0.0.0/0` | Firewall 사설 IP |

### 4-1. Routing Configuration 최초 생성

👁️ **설명**

모듈 03의 manager 세 범위와 A/B Group의 **정확한 멤버**를 다시 읽고,
기존 Routing Configuration이 없을 때만 만듭니다. 예상 밖의 자원을
덮어쓰지 않습니다.

🟢 **실행**

<!-- exec:routing-config-create -->
```bash
assert_routing_creation_ready &&
created=$(az network manager routing-config create -g "$RG_HUB" --manager-name "$AVNM" \
  -n "rc-lzbegin-spokes-$RUN_ID" --description "Spoke routes via Hub Firewall" \
  -o json --subscription "$SUBSCRIPTION_ID") &&
assert_routing_creation_result "$created" &&
printf '%s\n' "$created"
```

📋 **확인**

출력된 전체 ID가 `.../routingConfigurations/rc-lzbegin-spokes-<실행 ID>`인지 확인합니다.
생성 응답의 전체 ID를 검증하며, 배포 후 5절에서 실제 저장된 구성·경로를 다시 확인합니다.
`Updating`이면 다음 생성 대신 조회·대기하세요.

### 4-2. A 전용 rule collection

👁️ **설명**

`--applies-to`는 A의 Group **전체 ID** 한 개만 전달합니다.
이 실습에는 VNet Gateway/BGP가 없으며, BGP 경로 전파는 비활성화합니다.

🟢 **실행**

<!-- exec:routing-collection-spokea -->
```bash
applies_to=$(jq -cn --arg id "$ROUTE_GROUP_A_ID" '[{networkGroupId:$id}]') &&
created=$(az network manager routing-config rule-collection create \
  -g "$RG_HUB" --manager-name "$AVNM" --config-name "rc-lzbegin-spokes-$RUN_ID" \
  -n spokea --applies-to "$applies_to" --disable-bgp-route true \
  -o json --subscription "$SUBSCRIPTION_ID") &&
assert_routing_collection_result "$created" spokea "$ROUTE_GROUP_A_ID" &&
printf '%s\n' "$created"
```

📋 **확인**

A collection의 유일한 대상은 A Group입니다. 연결용 A+B Group을 사용하지 않습니다.

### 4-3. B 전용 rule collection

🟢 **실행**

<!-- exec:routing-collection-spokeb -->
```bash
applies_to=$(jq -cn --arg id "$ROUTE_GROUP_B_ID" '[{networkGroupId:$id}]') &&
created=$(az network manager routing-config rule-collection create \
  -g "$RG_HUB" --manager-name "$AVNM" --config-name "rc-lzbegin-spokes-$RUN_ID" \
  -n spokeb --applies-to "$applies_to" --disable-bgp-route true \
  -o json --subscription "$SUBSCRIPTION_ID") &&
assert_routing_collection_result "$created" spokeb "$ROUTE_GROUP_B_ID" &&
printf '%s\n' "$created"
```

📋 **확인**

B collection은 B Group만 대상으로 합니다.

### 4-4. A → B `/16` rule

👁️ **설명**

각 규칙을 만들 때마다 `firewall_ready_ip`가 **현재** Firewall 상태·Policy·진단을
확인합니다. 안전 검사가 실패하면 뒤의 `az ... create`를 실행하지 않습니다.
각 생성 응답의 전체 ID·목적지·next hop을 즉시 확인하고,
배포 후 5절에서 실제 적용된 구성·대상을 다시 검사합니다.

🟢 **실행**

<!-- exec:routing-rule-spokea-other -->
```bash
fw_ip=$(firewall_ready_ip) &&
next_hop=$(jq -cn --arg ip "$fw_ip" '{nextHopType:"VirtualAppliance",nextHopAddress:$ip}') &&
created=$(az network manager routing-config rule-collection rule create \
  -g "$RG_HUB" --manager-name "$AVNM" --config-name "rc-lzbegin-spokes-$RUN_ID" \
  --collection-name spokea -n to-other-spoke \
  --destination '{"type":"AddressPrefix","destinationAddress":"10.20.0.0/16"}' \
  --next-hop "$next_hop" -o json --subscription "$SUBSCRIPTION_ID") &&
assert_routing_rule_result "$created" spokea to-other-spoke 10.20.0.0/16 "$fw_ip" &&
printf '%s\n' "$created"
```

📋 **확인**

A의 `10.20.0.0/16 → VirtualAppliance (Firewall 사설 IP)`입니다.

### 4-5. A → 인터넷 `/0` rule

🟢 **실행**

<!-- exec:routing-rule-spokea-internet -->
```bash
fw_ip=$(firewall_ready_ip) &&
next_hop=$(jq -cn --arg ip "$fw_ip" '{nextHopType:"VirtualAppliance",nextHopAddress:$ip}') &&
created=$(az network manager routing-config rule-collection rule create \
  -g "$RG_HUB" --manager-name "$AVNM" --config-name "rc-lzbegin-spokes-$RUN_ID" \
  --collection-name spokea -n to-internet \
  --destination '{"type":"AddressPrefix","destinationAddress":"0.0.0.0/0"}' \
  --next-hop "$next_hop" -o json --subscription "$SUBSCRIPTION_ID") &&
assert_routing_rule_result "$created" spokea to-internet 0.0.0.0/0 "$fw_ip" &&
printf '%s\n' "$created"
```

📋 **확인**

A의 default route는 같은 Firewall 사설 IP입니다.

### 4-6. B → A `/16` rule

🟢 **실행**

<!-- exec:routing-rule-spokeb-other -->
```bash
fw_ip=$(firewall_ready_ip) &&
next_hop=$(jq -cn --arg ip "$fw_ip" '{nextHopType:"VirtualAppliance",nextHopAddress:$ip}') &&
created=$(az network manager routing-config rule-collection rule create \
  -g "$RG_HUB" --manager-name "$AVNM" --config-name "rc-lzbegin-spokes-$RUN_ID" \
  --collection-name spokeb -n to-other-spoke \
  --destination '{"type":"AddressPrefix","destinationAddress":"10.10.0.0/16"}' \
  --next-hop "$next_hop" -o json --subscription "$SUBSCRIPTION_ID") &&
assert_routing_rule_result "$created" spokeb to-other-spoke 10.10.0.0/16 "$fw_ip" &&
printf '%s\n' "$created"
```

📋 **확인**

B의 `10.10.0.0/16 → VirtualAppliance`는 A→B의 **응답 경로**입니다.

### 4-7. B → 인터넷 `/0` rule

🟢 **실행**

<!-- exec:routing-rule-spokeb-internet -->
```bash
fw_ip=$(firewall_ready_ip) &&
next_hop=$(jq -cn --arg ip "$fw_ip" '{nextHopType:"VirtualAppliance",nextHopAddress:$ip}') &&
created=$(az network manager routing-config rule-collection rule create \
  -g "$RG_HUB" --manager-name "$AVNM" --config-name "rc-lzbegin-spokes-$RUN_ID" \
  --collection-name spokeb -n to-internet \
  --destination '{"type":"AddressPrefix","destinationAddress":"0.0.0.0/0"}' \
  --next-hop "$next_hop" -o json --subscription "$SUBSCRIPTION_ID") &&
assert_routing_rule_result "$created" spokeb to-internet 0.0.0.0/0 "$fw_ip" &&
printf '%s\n' "$created"
```

📋 **확인**

B의 default route도 같은 Firewall 사설 IP입니다.

### 4-8. koreacentral에 Routing 배포

👁️ **설명**

AVNM의 **Routing만** commit합니다. 이 manager/리전에는 한 번에 하나의
Routing Configuration만 배포할 수 있으므로 A/B collection 둘을 **한 구성**
안에서 함께 적용합니다. 중복된 규칙 검사는 반복하지 않지만, 기존 route table이나
NAT가 붙은 Subnet은 배포 직전에 거부합니다. 배포 요청 성공만으로 Subnet 적용을
가정하지 않습니다.

🟢 **실행**

<!-- exec:routing-commit -->
```bash
assert_unattached_workload_subnets &&
az network manager post-commit --network-manager-name "$AVNM" \
  --commit-type Routing \
  --configuration-ids "$AVNM_ID/routingConfigurations/rc-lzbegin-spokes-$RUN_ID" \
  --target-locations "$LOCATION" --resource-group "$RG_HUB" \
  -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

Routing commit 요청이 성공해야 합니다. timeout/오류는 배포 취소나 성공을
뜻하지 않습니다. 배포가 비동기이므로 다음 읽기 전용 조회를 1–2분 간격으로
재실행할 수 있습니다.

### 4-9. koreacentral Routing 배포 상태 확인

👁️ **설명**

Routing을 지원하는 REST `listDeploymentStatus`의 **이번 구성 ID·Routing·koreacentral**의 가장 최근
commit이 `Deployed`여야 합니다. 전체 배포 성공은 개별 Subnet의 경로가
준비됐다는 뜻이 아니므로 5절을 이어서 검사합니다.

🟢 **실행**

<!-- exec:routing-deploy-status -->
```bash
inspect_routing_deployment() {
  local result
  result=$(az rest --method post \
    --url "$AVNM_ID/listDeploymentStatus?api-version=2025-05-01" \
    --body "$(jq -cn --arg loc "$LOCATION" '{deploymentTypes:["Routing"],regions:[$loc]}')" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg id "$AVNM_ID/routingConfigurations/rc-lzbegin-spokes-$RUN_ID" \
    --arg region "$LOCATION" '
    if type == "array" then .
    elif type == "object" and (.skipToken == null or .skipToken == "") and (.value | type == "array") then .value
    else error("Invalid or incomplete deployment status page") end
    | [.[] | select(.deploymentType == "Routing" and .region == $region)] |
      if length == 0 then error("No Routing deployment in the target region")
      else sort_by(.commitTime) | last end |
    .deploymentStatus == "Deployed" and
    (.configurationIds | type == "array" and length == 1) and
    (.configurationIds[0] | ascii_downcase) == ($id | ascii_downcase)
  ' <<< "$result" >/dev/null ||
    { fail "Routing deployment has not reached Deployed in koreacentral."; return 1; }
  printf 'PASS: latest Routing deployment in %s is Deployed\n' "$LOCATION"
}
inspect_routing_deployment
```

📋 **확인**

PASS가 나와야 합니다. `Deploying`/`Failed` 또는 다른 구성 ID라면 **VM을
만들지 마세요**. 실패 원인을 AVNM Deployments에서 확인합니다.

## 5. VM 생성 전 실제 적용 확인

👁️ **설명**

관리형 route table의 **이름·RG·태그를 추측하지 않습니다**. 양쪽
`snet-workload.routeTable.id`를 조회한 뒤 그 **반환된 전체 ID**로 테이블의
두 경로·next hop을 검증합니다. `assert_avnm_routes_ready`는 구성/대상
Group/규칙과 Subnet 연결을 함께 검사하고, `assert_no_spoke_nat`는
Spoke NAT 연결/리소스 및 Public IP 부재를 확인합니다. AVNM 배포 페이지의
성공 상태만으로 특정 Subnet의 적용을 대신하지 않습니다.

🟢 **실행**

<!-- exec:inspect-avnm-routing-subnets -->
```bash
inspect_avnm_routing_subnets() {
  local fw_ip
  inspect_routing_deployment || return 1
  fw_ip=$(firewall_ready_ip) || return 1
  assert_avnm_routes_ready "$fw_ip" || return 1
  assert_no_spoke_nat || return 1
  printf 'PASS: A /16 + /0 and B /16 + /0 use Firewall %s; no Spoke NAT\n' "$fw_ip"
}
inspect_avnm_routing_subnets
```

📋 **확인**

**두 Spoke 모두** PASS여야 다음 모듈의 VM/Hub NAT를 배포할 수 있습니다.
검사 실패/한쪽만 반영/CLI 조회 오류는 성공이 아닙니다. 수동 테이블을 만들어
우회하지 마세요. 아직 VM/NIC가 없어 NIC 유효 경로 또는 HTTP 로그는
증명할 수 없으며 모듈 05·06에서 별도 검증합니다. 기본 암묵적 outbound
access에 Spoke VM agent의 인터넷 접속을 맡기지 않습니다.

## Portal 확인과 트러블슈팅

👁️ **설명**

**Azure Firewall → Overview**에서 이번 Hub RG의 Standard Firewall,
실제 사설 IP, 이번 Policy와 Firewall Public IP를 확인합니다.
**Firewall Policy → Rule collections**에서 `workshop`의 관리/HTTP/FQDN
세 collection을 확인하고 **Firewall → Diagnostic settings**에서
이번 workspace와 `AZFWNetworkRule`·`AZFWApplicationRule`의 활성화를
확인합니다. **Virtual Network Manager → Routing configurations →
`rc-lzbegin-spokes-<실행 ID>`**에서 A/B rule collection과 각각의
대상 Group·두 규칙을 확인합니다. **Deployments**에서
`koreacentral`의 Routing 결과를 보고, 마지막으로 두
**Virtual network → Subnets → snet-workload → Route table** 연결을
확인하세요. 스크린샷의 이전 VM/NAT 구성은 새 실습의 증거가 아닙니다.

| 증상 | 조치 |
|---|---|
| Firewall IP 없음/`Updating` | 생성·IP 구성의 실제 상태와 Activity Log 확인; 사설 IP 확보 전 Routing 금지 |
| `FirewallPolicyUpdateFailed` | Firewall·Policy·group의 현재 상태 및 이미 저장된 collection 확인; 중복 생성 금지 |
| 진단 category 없음 | Firewall SKU/지원 category 확인; 검사를 생략하지 않기 |
| Peering 변경 실패/비연결 | 실제 remote VNet ID·Connected·AVNM Connectivity 배포/Peering enforcement 확인; 직접 A↔B 연결 금지 |
| Routing 구성 또는 규칙 `Updating` | 읽기 전용 조회로 완료까지 대기; 잘못된 Group/next hop은 commit 금지 |
| commit 성공인데 Subnet에 table 없음 | 배포/전파 대기 후 5절 재검사; A/B 그룹의 멤버·대상 리전·배포 실패 사유 확인 |
| 한쪽 `/16` 또는 `/0`만 존재 | 해당 collection/규칙·Firewall IP와 양쪽 Subnet 연결 확인; VM 생성 금지 |
| 기존 table/NAT 발견 | 다른 작업 소유인지 확인하고 중단; 기존 자원을 강제로 덮어쓰지 않기 |

## 완료 체크

- 이번 Hub의 Firewall Standard·Policy·세 Allow collection·전용 진단이 완료됐습니다.
- AVNM Connectivity 네 Peering이 전달 트래픽을 허용하며, A/B Routing Group은 겹치지 않습니다.
- Routing 구성 하나의 네 규칙이 `koreacentral`의 **두 실제 Subnet**에 적용됐습니다.
- Spoke NAT/PIP와 VM은 없으며 Hub NAT는 다음 모듈에서만 만듭니다.

## 다음 단계

- [이전: AVNM 연결과 Group](03-avnm-connectivity.md)
- [다음: VM과 AVNM Security Admin](05-firewall.md)

참고: [AVNM UDR 관리](https://learn.microsoft.com/azure/virtual-network-manager/concept-user-defined-route),
[AVNM 배포/전파](https://learn.microsoft.com/azure/virtual-network-manager/concept-deployments),
[ARM 2025-01-01 Routing Configuration](https://learn.microsoft.com/azure/templates/microsoft.network/2025-01-01/networkmanagers/routingconfigurations),
[ARM 2025-01-01 Rule Collection](https://learn.microsoft.com/azure/templates/microsoft.network/2025-01-01/networkmanagers/routingconfigurations/rulecollections),
[ARM 2025-01-01 Routing Rule](https://learn.microsoft.com/azure/templates/microsoft.network/2025-01-01/networkmanagers/routingconfigurations/rulecollections/rules).
