# 05. VM과 AVNM 중앙 보안

> 목표 시간 35–50분. Firewall·AVNM Routing이 준비된 뒤에만 VM을 배포하고, Security Admin 규칙으로 HTTP를 허용·차단·복구합니다. VM 배포와 정책 전파에는 시간이 더 걸릴 수 있습니다.

## 공통 준비

👁️ **설명**

[모듈 04](04-connectivity-nsg.md)의 Firewall·진단·AVNM Routing 배포가 먼저 완료되어야 합니다.
모듈 01의 `STATE_FILE`을 사용하며, 같은 Cloud Shell에서 **한 블록 실행 → 결과 확인 → 다음 블록** 순서로 진행합니다.
재접속 후 원래 구독이 활성 상태라면 아래 준비를 다시 실행하세요. `STATE_FILE`이 비어 있으면
`ls .workshop-state/`로 파일명을 보여준 뒤 `.workshop-state/<실행 ID>.json`
경로를 입력받습니다. 구독을 바꿨다면 먼저
[세션 복구](01-prerequisites.md#세션-재연결-시-변수-복구)를 실행하세요.
실패한 블록 뒤의 자원 변경으로 넘어가지 마세요. 준비 함수는 검사 실패를 반환하지만 셸을 종료하지 않습니다.

🟢 **실행**

<!-- exec:prepare-05 -->
```bash
prepare_vm_session() {
  source scripts/workshop-common.sh || return 1
  source scripts/workshop-safety.sh || return 1
  source scripts/verify-common.sh || return 1
  ensure_state_file || return 1
  load_run "$STATE_FILE" || return 1
  assert_subscription || return 1
  assert_owned_rg "$RG_HUB" || return 1
  assert_owned_rg "$RG_SPOKEA" || return 1
  assert_owned_rg "$RG_SPOKEB"
}
prepare_vm_session
```

📋 **확인**

구독과 세 실습 RG의 소유권을 확인했습니다. 아직 VM이나 보안 규칙을 만들지 않았습니다.
`firewall_ready_ip`, `assert_avnm_routes_ready`, `assert_no_spoke_nat`는 현재 Azure 상태를 읽는 안전 검사입니다.
세션을 다시 열면 준비 블록부터 재실행하세요.

## 1. VM 배포 전 경로·용량 확인

👁️ **설명**

Spoke의 기본 outbound는 꺼져 있으며 **Spoke NAT나 Public IP는 만들지 않습니다**.
VM Agent의 HTTPS 관리 통신을 위해 모듈 04에서 Firewall 정책과 두 Spoke의
상대편 `/16`·기본 `/0` AVNM 경로가 이미 배포·적용되어 있어야 합니다.
Subnet의 유효 경로까지 확인한 뒤에만 VM을 배포합니다. Firewall은 NAT의 주소 변환과
달리 FQDN 규칙·로그도 제공합니다. Hub 관리 VM에만 별도 Hub NAT를 사용합니다.

### 1-1. VM 할당량 사전 점검

🟢 **실행**

<!-- exec:vm-preflight -->
```bash
bash scripts/preflight.sh "$STATE_FILE"
```

📋 **확인**

`PASS: read-only preflight`. 옵션 없이 실행해 새 VM 3대의
`Standard_B2als_v2` 계열 및 지역 전체
vCPU 여유(총 6개)를 확인합니다. 기존 VM이 있으면 실행 상태와 크기를 확인합니다.

### 1-2. 현재 Firewall·AVNM 경로 재검사

🟢 **실행**

<!-- exec:vm-route-gate -->
```bash
check_vm_network() {
  assert_enforced_connectivity || return 1
  firewall_ip=$(firewall_ready_ip) || return 1
  assert_avnm_routes_ready "$firewall_ip" || return 1
  assert_no_spoke_nat
}
check_vm_network
```

📋 **확인**

AVNM 피어링 강제 구성이 두 Spoke에 적용되고 네 방향 전달 허용이 유지됩니다.
Firewall 사설 IP가 `AzureFirewallSubnet` 범위이고, **두 Spoke 워크로드 Subnet 모두**
해당 IP를 next hop으로 하는 상대 Spoke `/16`과 `/0` AVNM 경로가 적용됐습니다.
Spoke Subnet에 NAT가 없고 Spoke NAT/Public IP도 없습니다.
검사가 실패했다면 모듈 04에서 배포·전파·Subnet 유효 경로를 먼저 확인합니다.
**VM 배포 직전**에도 같은 검사를 반복합니다. 명령 한 번의 성공을 나중 작업의 승인으로 저장하지 않습니다.

## 2. VM 3대와 Hub NAT만 배포

👁️ **설명**

반복되는 VM·NIC·디스크와 **Hub NAT Gateway·Hub NAT 전용 Public IP 하나씩**은
[`infra/lab-support.bicep`](../infra/lab-support.bicep)으로 배포합니다.
세 기존 RG를 대상으로 `az deployment sub`를 사용하며, 기존 VNet·Subnet·NSG는
만들거나 덮어쓰지 않습니다. VM NIC에는 Public IP가 없습니다.
Hub NAT를 생성한 뒤 관리 Subnet에 연결하는 일은 별도 단계입니다.

### 2-1. 공개 SSH 키 준비

👁️ **설명**

VM에는 공개 키만 등록하며 SSH 인바운드는 열지 않습니다. 개인 키를 Git에 올리지 마세요.
키가 일부만 존재한다면 덮어쓰지 않고 원인을 확인합니다.

🟢 **실행**

<!-- exec:support-key -->
```bash
prepare_support_key() {
  mkdir -p -m 700 ".workshop-keys/$RUN_ID" || return 1
  chmod 700 ".workshop-keys/$RUN_ID" || return 1
  if [[ -e ".workshop-keys/$RUN_ID/id_ed25519" ]]; then
    test -s ".workshop-keys/$RUN_ID/id_ed25519" || return 1
    test -s ".workshop-keys/$RUN_ID/id_ed25519.pub"
  elif [[ -e ".workshop-keys/$RUN_ID/id_ed25519.pub" ]]; then
    fail "SSH public key exists without its private key"
    return 1
  else
    ssh-keygen -t ed25519 -N '' -f ".workshop-keys/$RUN_ID/id_ed25519" -C "lz-beginner-$RUN_ID"
  fi
}
prepare_support_key
```

📋 **확인**

새 키 fingerprint가 나오거나 기존 키 쌍이 유지됩니다. 개인 키를 배포 인수에 넣지 않습니다.

### 2-2. 유료 배포 미리 보기

🟢 **실행**

<!-- exec:support-preview -->
```bash
preview_support() {
  public_key=$(cat ".workshop-keys/$RUN_ID/id_ed25519.pub") || return 1
  [[ -n "$public_key" ]] || return 1
  check_vm_network || return 1
  az deployment sub what-if --name "support-$RUN_ID" --location "$LOCATION" \
    --template-file infra/lab-support.bicep \
    --parameters runId="$RUN_ID" location="$LOCATION" \
      hubResourceGroup="$RG_HUB" spokeaResourceGroup="$RG_SPOKEA" spokebResourceGroup="$RG_SPOKEB" \
      sshPublicKey="$public_key" --subscription "$SUBSCRIPTION_ID"
}
preview_support
```

📋 **확인**

Hub NAT·Hub Public IP **각 1개**, Hub/Spoke A/Spoke B VM·NIC·디스크가 추가됩니다.
Spoke NAT/Public IP, VNet/Subnet 삭제 또는 다른 실행의 자원 변경이 보이면 배포하지 마세요.
미리 보기는 자원을 생성하지 않습니다.

### 2-3. 비용 확인 후 배포

👁️ **설명**

유료 VM 3대와 Hub NAT 하나의 배포에 동의할 때만 `CREATE`를 입력합니다.
45분 timeout은 로컬 대기만 끝냅니다. 시간 초과 시 Azure Portal의 배포 상태를 먼저 확인하세요.

🟢 **실행**

<!-- exec:support-deploy -->
```bash
deploy_support() {
  local public_key confirm
  public_key=$(cat ".workshop-keys/$RUN_ID/id_ed25519.pub") || return 1
  [[ -n "$public_key" ]] || return 1
  check_vm_network || return 1
  read -rp "유료 VM 3대와 Hub NAT 1개를 배포합니다. CREATE 입력: " confirm || return 1
  [[ "$confirm" == CREATE ]] || { fail "Cancelled"; return 1; }
  timeout 2700 az deployment sub create --name "support-$RUN_ID" --location "$LOCATION" \
    --template-file infra/lab-support.bicep \
    --parameters runId="$RUN_ID" location="$LOCATION" \
      hubResourceGroup="$RG_HUB" spokeaResourceGroup="$RG_SPOKEA" spokebResourceGroup="$RG_SPOKEB" \
      sshPublicKey="$public_key" -o json --subscription "$SUBSCRIPTION_ID"
}
deploy_support
```

📋 **확인**

배포 `provisioningState=Succeeded`. 결과의 `support.hub`에만 `natGatewayId`와
`publicIpId`가 있습니다. `support.spokea`와 `support.spokeb`에는 VM·NIC·사설 IP만 있습니다.
NAT는 아직 관리 Subnet에 붙지 않았습니다.

### 2-4. Hub 관리 Subnet에 NAT 연결

🟢 **실행**

<!-- exec:attach-nat-hub -->
```bash
az network vnet subnet update -g "$RG_HUB" --vnet-name "vnet-lzbegin-hub-$RUN_ID" -n snet-management \
  --nat-gateway "nat-lzbegin-hub-$RUN_ID" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

Hub 관리 Subnet의 `natGateway.id`가 이번 Hub NAT입니다. Spoke Subnet에는 연결하지 않습니다.

### 2-5. Hub NAT와 Spoke NAT 부재 조회

🟢 **실행**

<!-- exec:inspect-nat-hub -->
```bash
az network vnet subnet show -g "$RG_HUB" --vnet-name "vnet-lzbegin-hub-$RUN_ID" -n snet-management \
  --query '{Subnet:name,NatGateway:natGateway.id,NSG:networkSecurityGroup.id,DefaultOutbound:defaultOutboundAccess}' \
  -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

`Subnet=snet-management`, NAT 이름은 `nat-lzbegin-hub-<실행 ID>`,
NSG 이름은 `nsg-lzbegin-hub-<실행 ID>`, `DefaultOutbound=false`입니다.

🟢 **실행**

<!-- exec:inspect-no-spoke-nat -->
```bash
assert_no_spoke_nat
```

📋 **확인**

두 Spoke Subnet 모두 NAT 연결이 없으며 이번 실행의 Spoke NAT/Public IP도 없습니다.
공유 리전 Network Watcher를 삭제하거나 태그를 바꾸지 않습니다.

## 3. NIC에 실제 적용된 경로와 진단 도구 확인

👁️ **설명**

Subnet 경로 검사만으로 새 VM의 경로를 증명할 수 없습니다. 다음 검사는 두 NIC의
**Active** 유효 경로에서 상대 Spoke `/16`과 기본 `/0`이 모두 실제 Firewall IP로
향하는지 확인합니다. Hub→Spoke의 직접 Peering 경로는 계속 유지됩니다.

🟢 **실행**

<!-- exec:effective-vm-routes -->
```bash
check_vm_effective_routes() {
  local zone rg remote routes
  firewall_ip=$(firewall_ready_ip) || return 1
  for zone in spokea spokeb; do
    if [[ "$zone" == spokea ]]; then
      rg="$RG_SPOKEA"
      remote=10.20.0.0/16
    else
      rg="$RG_SPOKEB"
      remote=10.10.0.0/16
    fi
    routes=$(az network nic show-effective-route-table -g "$rg" \
      -n "nic-lzbegin-$zone-$RUN_ID" -o json --subscription "$SUBSCRIPTION_ID") || return 1
    jq -e --arg remote "$remote" --arg ip "$firewall_ip" '
      .value as $routes |
      ($routes | type == "array") and
      all([$remote, "0.0.0.0/0"][]; . as $prefix |
        any($routes[]; .state == "Active" and
          (.addressPrefix | index($prefix)) != null and
          .nextHopType == "VirtualAppliance" and
          (.nextHopIpAddress | index($ip)) != null))
    ' <<<"$routes" >/dev/null || return 1
    printf 'PASS: %s NIC /16 and /0 -> Firewall %s\n' "$zone" "$firewall_ip"
  done
}
check_vm_effective_routes
```

📋 **확인**

Spoke A에는 `10.20.0.0/16`, Spoke B에는 `10.10.0.0/16`, 양쪽에는
`0.0.0.0/0`이 `Active`·`VirtualAppliance`·동일 Firewall 사설 IP입니다.
다른 next hop이나 비활성 경로를 통과로 해석하지 않습니다.

### 3-1. 공유 Network Watcher 재사용·필요한 경우에만 활성화

👁️ **설명**

[IP Flow Verify](https://learn.microsoft.com/azure/network-watcher/ip-flow-verify-overview)는
NSG 진단에 유용하지만 이 환경에서 AVNM `AlwaysAllow`의 실제 판정과 달리 NSG
`Deny`를 반환할 수 있습니다. 따라서 이 모듈의 허용·차단 증거로 단독 사용하지
않습니다. 리전 Network Watcher는 VNet 생성 시 자동 활성화됐을 수 있습니다.
기존 Watcher와 공유 `NetworkWatcherRG`의 태그를 변경하거나 실습 종료 시 삭제하지 않습니다.

🟢 **실행**

<!-- exec:inspect-watcher -->
```bash
az network watcher list --query "[?location=='$LOCATION'].id" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

ID가 있으면 재사용합니다. `[]`일 때만 다음 활성화 블록이 공유 RG를 만들 수 있습니다.
조회 오류를 빈 배열로 해석하지 않습니다.

🟢 **실행**

<!-- exec:watcher-enable -->
```bash
ensure_region_watcher() {
  local watchers exists
  watchers=$(az network watcher list --query "[?location=='$LOCATION'].id" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e 'type == "array" and all(.[]; type == "string" and length > 0)' <<<"$watchers" >/dev/null || return 1
  if [[ $(jq length <<<"$watchers") == 0 ]]; then
    exists=$(az group exists --name NetworkWatcherRG -o tsv --subscription "$SUBSCRIPTION_ID") || return 1
    case "$exists" in
      true) printf '기존 공유 RG를 그대로 사용합니다.\n' ;;
      false) az group create --name NetworkWatcherRG --location "$LOCATION" -o json \
        --subscription "$SUBSCRIPTION_ID" || return 1 ;;
      *) fail "Cannot determine whether NetworkWatcherRG exists"; return 1 ;;
    esac
    az network watcher configure --locations "$LOCATION" --enabled true \
      --resource-group NetworkWatcherRG -o json --subscription "$SUBSCRIPTION_ID" || return 1
  else
    printf '기존 리전 Watcher를 사용합니다.\n'
  fi
  watchers=$(az network watcher list --query "[?location=='$LOCATION'].id" \
    -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e 'type == "array" and length > 0 and all(.[]; type == "string" and length > 0)' \
    <<<"$watchers" >/dev/null || return 1
}
ensure_region_watcher
```

📋 **확인**

기존 watcher 사용 메시지 또는 활성화 응답 뒤 리전 Watcher ID를 다시 확인합니다.
공유 RG에는 이번 실행의 소유 태그를 붙이지 않습니다.

## 4. 응답 서비스와 VM 사설 IP

👁️ **설명**

Spoke VM에서만 Python HTTP 8080 서비스를 실행합니다. Cloud Shell이 VM 사설 IP에 SSH하는
방식이 아닙니다. `run-vm.sh`가 신뢰하는 `guest-server.sh`를 VM Agent로 전달하고
게스트의 종료 코드를 검사합니다. NSG·경로·Firewall은 이 스크립트로 변경하지 않습니다.
Run Command가 실패하면 Firewall의 관리용 Azure HTTPS 규칙과 두 NIC의 `/0`을 먼저 확인하세요.

🟢 **실행**

<!-- exec:service-spokea -->
```bash
bash scripts/run-vm.sh "$STATE_FILE" spokea scripts/guest-server.sh
```

📋 **확인**

`PASS: local service spokea`. A 내부 서비스 성공이지 Hub→A 통신 성공은 아닙니다.

🟢 **실행**

<!-- exec:service-spokeb -->
```bash
bash scripts/run-vm.sh "$STATE_FILE" spokeb scripts/guest-server.sh
```

📋 **확인**

`PASS: local service spokeb`. 각 응답은 비민감 문자열이며 운영 HTTP 보안을 대신하지 않습니다.

🟢 **실행**

<!-- exec:read-vm-ips -->
```bash
read_vm_ips() {
  hub_ip=$(az network nic show -g "$RG_HUB" -n "nic-lzbegin-hub-$RUN_ID" \
    --query 'ipConfigurations[0].privateIPAddress' -o tsv --subscription "$SUBSCRIPTION_ID") || return 1
  a_ip=$(az network nic show -g "$RG_SPOKEA" -n "nic-lzbegin-spokea-$RUN_ID" \
    --query 'ipConfigurations[0].privateIPAddress' -o tsv --subscription "$SUBSCRIPTION_ID") || return 1
  b_ip=$(az network nic show -g "$RG_SPOKEB" -n "nic-lzbegin-spokeb-$RUN_ID" \
    --query 'ipConfigurations[0].privateIPAddress' -o tsv --subscription "$SUBSCRIPTION_ID") || return 1
  assert_ipv4_in_subnet "$hub_ip" 10.0.1.0/24 || return 1
  assert_ipv4_in_subnet "$a_ip" 10.10.1.0/24 || return 1
  assert_ipv4_in_subnet "$b_ip" 10.20.1.0/24 || return 1
  printf 'Hub=%s A=%s B=%s\n' "$hub_ip" "$a_ip" "$b_ip"
}
read_vm_ips
```

📋 **확인**

세 NIC의 **현재** 사설 IP를 확인했습니다. `.4`와 같은 고정 주소를 가정하지 않습니다.
VM NIC를 재생성해 IP가 바뀌었다면 이전 규칙을 그대로 배포하지 말고 새 실행으로 시작하세요.

## 5. AVNM Security Admin으로 필요한 TCP 8080만 허용

👁️ **설명**

모듈 03에서 만든 AVNM은 이미 `SecurityAdmin` 범위를 갖습니다. 새 Manager를 만들지 않습니다.
이번 실행의 Spoke A/B Network Group(모듈 03의 Routing용 두 Group)에만 각각의
규칙 컬렉션을 적용합니다. A 컬렉션에는 Hub→A, B 컬렉션에는 Hub→B와 A→B를 둡니다.
Hub→A, Hub→B, A→B 각각 **실제 NIC IP의 `/32`·TCP 8080·Inbound**만 지정합니다.
출발지 포트는 임시 포트를 포함하는 `0-65535`입니다. [Security Admin 동작](https://learn.microsoft.com/azure/virtual-network-manager/concept-security-admins)에
따라 `AlwaysAllow`는 Spoke NSG의 `deny-other-vnet-inbound`(4000)보다 먼저
평가되고 **NSG 평가 자체를 건너뜁니다**. `Allow`는 NSG까지 계속 평가되므로 이 실습에 맞지 않습니다.
Firewall을 통과하는 A→B에는 별도로 모듈 04의 Firewall Policy 허용 규칙이 필요합니다.
기존 NSG 규칙을 변경하거나 제거하지 않습니다.

### 5-1. 이번 실행의 Security Admin 구성 생성

🟢 **실행**

<!-- exec:security-config -->
```bash
az network manager security-admin-config create -g "$RG_HUB" --network-manager-name "$AVNM" \
  --configuration-name "sc-lzbegin-http-$RUN_ID" --description "Workshop TCP 8080 on spoke VMs" \
  --apply-on None -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

`securityAdminConfigurations/sc-lzbegin-http-<실행 ID>`가 생성됩니다. 같은 리전에 다른 Security Admin
구성이 이미 배포됐다면 바꿔치기하지 말고 중단합니다. 한 리전에 배포할 수 있는 구성은 하나입니다.

### 5-2. Spoke A Group 대상 컬렉션

🟢 **실행**

<!-- exec:security-collection -->
```bash
az network manager security-admin-config rule-collection create -g "$RG_HUB" \
  --network-manager-name "$AVNM" --configuration-name "sc-lzbegin-http-$RUN_ID" \
  --rule-collection-name spokea \
  --applies-to-groups network-group-id="$ROUTE_GROUP_A_ID" \
  -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

`appliesToGroups[0].networkGroupId`가 모듈 03의 **전체** `$ROUTE_GROUP_A_ID`입니다.
이 Group에는 Spoke A VNet만 속해야 합니다.

🟢 **실행**

<!-- exec:security-collection-b -->
```bash
az network manager security-admin-config rule-collection create -g "$RG_HUB" \
  --network-manager-name "$AVNM" --configuration-name "sc-lzbegin-http-$RUN_ID" \
  --rule-collection-name spokeb \
  --applies-to-groups network-group-id="$ROUTE_GROUP_B_ID" \
  -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

B 컬렉션의 전체 Group ID가 `$ROUTE_GROUP_B_ID`입니다. 두 컬렉션 모두 Spoke VM이
속한 VNet만 대상으로 하며 Hub VNet에는 규칙을 배포하지 않습니다.

### 5-3. Hub → Spoke A AlwaysAllow

🟢 **실행**

<!-- exec:allow-hub-spokea -->
```bash
az network manager security-admin-config rule-collection rule create -g "$RG_HUB" \
  --network-manager-name "$AVNM" --configuration-name "sc-lzbegin-http-$RUN_ID" \
  --rule-collection-name spokea --rule-name hub-to-a \
  --priority 200 --direction Inbound --access AlwaysAllow --protocol Tcp \
  --sources address-prefix="$hub_ip/32" address-prefix-type=IPPrefix \
  --source-port-ranges 0-65535 --destinations address-prefix="$a_ip/32" address-prefix-type=IPPrefix \
  --dest-port-ranges 8080 -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

우선순위 `200`, 출발지는 Hub NIC 한 대, 목적지는 A NIC 한 대입니다. 아직 배포 전입니다.

### 5-4. Hub → Spoke B AlwaysAllow

🟢 **실행**

<!-- exec:allow-hub-spokeb -->
```bash
az network manager security-admin-config rule-collection rule create -g "$RG_HUB" \
  --network-manager-name "$AVNM" --configuration-name "sc-lzbegin-http-$RUN_ID" \
  --rule-collection-name spokeb --rule-name hub-to-b \
  --priority 210 --direction Inbound --access AlwaysAllow --protocol Tcp \
  --sources address-prefix="$hub_ip/32" address-prefix-type=IPPrefix \
  --source-port-ranges 0-65535 --destinations address-prefix="$b_ip/32" address-prefix-type=IPPrefix \
  --dest-port-ranges 8080 -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

우선순위 `210`, Hub NIC → B NIC만 지정됐습니다.

### 5-5. Spoke A → Spoke B AlwaysAllow

🟢 **실행**

<!-- exec:allow-spokea-spokeb -->
```bash
az network manager security-admin-config rule-collection rule create -g "$RG_HUB" \
  --network-manager-name "$AVNM" --configuration-name "sc-lzbegin-http-$RUN_ID" \
  --rule-collection-name spokeb --rule-name a-to-b \
  --priority 220 --direction Inbound --access AlwaysAllow --protocol Tcp \
  --sources address-prefix="$a_ip/32" address-prefix-type=IPPrefix \
  --source-port-ranges 0-65535 --destinations address-prefix="$b_ip/32" address-prefix-type=IPPrefix \
  --dest-port-ranges 8080 -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

우선순위 `220`, A NIC → B NIC만 지정됐습니다. 더 낮은 번호의 Deny가 생기면 우선합니다.

### 5-6. 현재 규칙 읽기와 리전 배포

🟢 **실행**

<!-- exec:inspect-security-rules -->
```bash
assert_admin_rules_ready "$hub_ip" "$a_ip" "$b_ip" baseline
```

📋 **확인**

두 컬렉션의 Group·세 `AlwaysAllow`·우선순위·출발지/목적지 `/32`를
현재 Azure 응답으로 검사합니다. 예상 밖의 규칙은 고치기 전까지 배포하지 마세요.
규칙을 만드는 것만으로 패킷에 적용되지 않습니다.

🟢 **실행**

<!-- exec:security-deploy -->
```bash
az network manager post-commit -g "$RG_HUB" --network-manager-name "$AVNM" \
  --commit-type SecurityAdmin --configuration-ids "$AVNM_ID/securityAdminConfigurations/sc-lzbegin-http-$RUN_ID" \
  --target-locations "$LOCATION" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

이번 구성 ID와 리전의 SecurityAdmin 배포가 접수됩니다. 완료 응답과 실제 VM 적용은
다릅니다. 아래 effective Security Admin 규칙과 실제 HTTP로 적용 여부를 확인합니다.

### 5-7. 적용된 규칙과 새 HTTP 연결

👁️ **설명**

대상 Spoke의 **effective Security Admin 규칙**에서 이번 AVNM의 전체 규칙 ID·동작·
주소·포트가 적용됐는지 확인합니다. 새 연결마다 출발지 포트가 달라도 규칙의
출발지 포트 범위 `0-65535`가 적용됩니다. 전파 중에는 이전 규칙이 보일 수 있어
최대 약 3분 기다립니다. 실제 HTTP 연결은 별도로 확인합니다.
이 리허설에서는 Network Watcher IP Flow Verify가 effective `AlwaysAllow`와 실제
HTTP 성공에도 NSG의 `Deny`를 반환했으므로, 단독으로 AVNM 허용 여부의 근거로
사용하지 않습니다.

🟢 **실행**

<!-- exec:admin-flow-check -->
```bash
check_admin_flow() {
  local zone="$1" destination="$2" source="$3" expected="$4" rule="$5" attempt
  for attempt in {1..12}; do
    if admin_proof "$zone" "$destination" "$source" "$expected" "$rule"; then return 0; fi
    if (( attempt < 12 )); then sleep 15; fi
  done
  fail "Admin rule not effective on $zone: $rule/$expected"
  return 1
}
```

📋 **확인**

검사 함수만 정의했습니다. 아래 각 블록이 **현재 effective 규칙**을 개별 검증합니다.
조회 오류가 계속되면 권한과 AVNM 배포 상태를 점검합니다.

🟢 **실행**

<!-- exec:verify-admin-allow-a -->
```bash
check_admin_flow spokea "$a_ip" "$hub_ip" Allow hub-to-a
```

📋 **확인**

Hub→A의 `AlwaysAllow`와 이번 AVNM 전체 규칙 ID가 일치합니다. NSG의 4000 Deny는 그대로입니다.

🟢 **실행**

<!-- exec:verify-admin-allow-b -->
```bash
check_admin_flow spokeb "$b_ip" "$hub_ip" Allow hub-to-b
```

📋 **확인**

Hub→B에도 중앙 `AlwaysAllow` 규칙이 적용됐습니다.

🟢 **실행**

<!-- exec:verify-admin-allow-ab -->
```bash
check_admin_flow spokeb "$b_ip" "$a_ip" Allow a-to-b
```

📋 **확인**

A→B도 중앙 규칙이 허용합니다. effective 규칙만으로 실제 왕복 경로나 Firewall
허용을 증명하지는 않으므로 아래 HTTP 요청도 실행합니다.

🟢 **실행**

<!-- exec:verify-admin-http-baseline -->
```bash
check_baseline_http() {
  http_proof "$STATE_FILE" hub "$a_ip" spokea || return 1
  http_proof "$STATE_FILE" hub "$b_ip" spokeb || return 1
  http_proof "$STATE_FILE" spokea "$b_ip" spokeb
}
check_baseline_http
```

📋 **확인**

Hub→A=`spokea`, Hub→B=`spokeb`, A→B=`spokeb`의 **새 HTTP 연결** 세 건이 성공합니다.
A→B는 모듈 04의 AVNM `/16` 왕복 경로로 Firewall을 통과하며 Firewall Policy도
허용해야 합니다. Hub→Spoke는 직접 Peering을 사용하므로 Firewall 로그가 없을 수 있습니다.

## 6. 더 높은 우선순위 Deny와 복구

👁️ **설명**

Spoke A 컬렉션에 우선순위 `100`인 **Hub NIC→A NIC TCP 8080 한 건**을 Deny로
추가합니다. `100`은 `200`보다 먼저 평가되므로 A 연결만 막고 Hub→B는 그대로 둡니다.
규칙 추가/삭제 후에는 **각각 리전에 다시 배포**해야 반영됩니다. Deny 실험이 실패해도
아래 복구(삭제·재배포)를 실행하세요. 이 실험은 Firewall의 FQDN 규칙이나 기존 NSG를 변경하지 않습니다.

### 6-1. 임시 Hub → A Deny

🟢 **실행**

<!-- exec:deny-hub -->
```bash
az network manager security-admin-config rule-collection rule create -g "$RG_HUB" \
  --network-manager-name "$AVNM" --configuration-name "sc-lzbegin-http-$RUN_ID" \
  --rule-collection-name spokea --rule-name deny-hub-to-a \
  --priority 100 --direction Inbound --access Deny --protocol Tcp \
  --sources address-prefix="$hub_ip/32" address-prefix-type=IPPrefix \
  --source-port-ranges 0-65535 --destinations address-prefix="$a_ip/32" address-prefix-type=IPPrefix \
  --dest-port-ranges 8080 -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

`deny-hub-to-a`의 주소·포트와 priority `100`을 확인합니다. 아직 적용 전입니다.

🟢 **실행**

<!-- exec:inspect-admin-deny -->
```bash
assert_admin_rules_ready "$hub_ip" "$a_ip" "$b_ip" denied
```

📋 **확인**

두 Group의 적용 범위와 `Deny`, `Inbound`, `Tcp`, `8080`, Hub/A 각각 `/32`,
우선순위 `100`을 현재 규칙 응답에서 검사합니다.

🟢 **실행**

<!-- exec:security-deploy-deny -->
```bash
az network manager post-commit -g "$RG_HUB" --network-manager-name "$AVNM" \
  --commit-type SecurityAdmin --configuration-ids "$AVNM_ID/securityAdminConfigurations/sc-lzbegin-http-$RUN_ID" \
  --target-locations "$LOCATION" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

변경된 동일 구성을 리전에 재배포했습니다. 전파 판정은 다음 블록에서 확인합니다.

🟢 **실행**

<!-- exec:verify-admin-deny -->
```bash
check_admin_flow spokea "$a_ip" "$hub_ip" Deny deny-hub-to-a
```

📋 **확인**

Spoke A의 effective 규칙에 `Deny`와 **이번 임시 규칙의 전체 ID**가 표시됩니다.
우연한 NSG Deny가 아님은 다음 HTTP 차단과 구성 상태를 함께 대조합니다.

🟢 **실행**

<!-- exec:verify-admin-http-denied -->
```bash
check_denied_http() {
  http_proof "$STATE_FILE" hub "$a_ip" blocked || return 1
  http_proof "$STATE_FILE" hub "$b_ip" spokeb || return 1
  bash scripts/run-vm.sh "$STATE_FILE" spokea scripts/guest-server.sh
}
check_denied_http
```

📋 **확인**

새 Hub→A 연결은 실패하지만 Hub→B는 성공하고 A 로컬 HTTP 서비스는 살아 있습니다.
HTTP 실패 단독으로 보안 규칙의 원인을 판단하지 않습니다.

### 6-2. 임시 규칙 제거와 리전 재배포

⚠️ **주의**

차단 증거 수집이 실패했더라도 **복구를 진행합니다**. AVNM은 배포 중인
Security Admin 구성의 규칙 삭제를 거부하므로 먼저 이 구성만 리전에서 배포 해제하고,
상태 확인 후 임시 Deny를 삭제·재배포합니다. 해제 중에는 세 `AlwaysAllow`도
잠시 적용되지 않아 통신이 끊길 수 있습니다. NSG·Firewall 구성은 변경하지 않습니다.

🟢 **실행**

<!-- exec:security-undeploy-for-restore -->
```bash
undeploy_security_for_restore() {
  az network manager post-commit -g "$RG_HUB" --network-manager-name "$AVNM" \
    --commit-type SecurityAdmin --configuration-ids '[]' \
    --target-locations "$LOCATION" -o json --subscription "$SUBSCRIPTION_ID" || return 1
  assert_security_admin_undeployed
}
undeploy_security_for_restore
```

📋 **확인**

최신 `SecurityAdmin` 배포가 구성 ID 없는 `Deployed` 상태여야 합니다.
아직 적용 중이라면 잠시 기다렸다가 **아래 삭제 블록은 실행하지 말고**
배포 상태를 다시 확인하세요.

🟢 **실행**

<!-- exec:restore-hub -->
```bash
restore_hub_admin_rule() {
  assert_security_admin_undeployed || return 1
  az network manager security-admin-config rule-collection rule delete -g "$RG_HUB" \
    --network-manager-name "$AVNM" --configuration-name "sc-lzbegin-http-$RUN_ID" \
    --rule-collection-name spokea --rule-name deny-hub-to-a \
    --yes --subscription "$SUBSCRIPTION_ID"
}
restore_hub_admin_rule
```

📋 **확인**

임시 Deny만 삭제됐습니다. 삭제 응답만으로 적용된 규칙이 사라졌다고 가정하지 않습니다.

🟢 **실행**

<!-- exec:inspect-admin-restored -->
```bash
assert_admin_rules_ready "$hub_ip" "$a_ip" "$b_ip" restored
```

📋 **확인**

두 컬렉션의 세 AlwaysAllow가 올바릅니다. 임시 Deny의 **부재**도 다음 조회에서
확인한 뒤 재배포합니다.

🟢 **실행**

<!-- exec:inspect-deny-absent -->
```bash
check_deny_absent() {
  local rules
  rules=$(az network manager security-admin-config rule-collection rule list -g "$RG_HUB" \
    --network-manager-name "$AVNM" --configuration-name "sc-lzbegin-http-$RUN_ID" \
    --rule-collection-name spokea -o json --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e 'type == "array" and length == 1 and
    .[0].name == "hub-to-a"' <<<"$rules" >/dev/null || return 1
  printf 'PASS: temporary Deny absent\n'
}
check_deny_absent
```

📋 **확인**

Spoke A 컬렉션에 `hub-to-a`만 남았습니다. 누락되거나 다른 규칙이 있으면 재배포 전에 바로잡습니다.

🟢 **실행**

<!-- exec:security-deploy-restore -->
```bash
az network manager post-commit -g "$RG_HUB" --network-manager-name "$AVNM" \
  --commit-type SecurityAdmin --configuration-ids "$AVNM_ID/securityAdminConfigurations/sc-lzbegin-http-$RUN_ID" \
  --target-locations "$LOCATION" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

복구 구성을 **같은 리전**에 다시 배포했습니다. 최종 판정과 통신 증거를 확인합니다.

🟢 **실행**

<!-- exec:verify-admin-restored -->
```bash
check_admin_flow spokea "$a_ip" "$hub_ip" Allow hub-to-a
```

📋 **확인**

Hub→A에 다시 AlwaysAllow가 적용되고 임시 Deny는 더 이상 우선하지 않습니다.

🟢 **실행**

<!-- exec:verify-admin-http-restored -->
```bash
check_baseline_http
```

📋 **확인**

Hub→A/B와 A→B의 새 HTTP 세 건이 다시 성공합니다. CLI 배포 응답과 **실제 통신 복구**를 구분하세요.

## Portal 확인·트러블슈팅

👁️ **설명**

**Virtual Network Manager → 이번 AVNM → Configurations → Security admin configurations**에서
Spoke Group 대상 컬렉션, 세 AlwaysAllow와 Deny 부재를 확인하세요.
**VM → Networking → Effective security rules**에서 중앙 규칙과 Subnet NSG의
`deny-other-vnet-inbound`(4000)를 함께 확인합니다. AlwaysAllow는 NSG Deny를 **우회**하지
NSG 규칙을 삭제하지 않습니다. **NIC → Effective routes**에서 `/16`과 `/0`의
VirtualAppliance IP를 확인하세요.

| 증상 | 먼저 확인할 것 |
|---|---|
| VM Run Command 실패 | Spoke NIC의 `/0` → Firewall, Firewall 관리 HTTPS 규칙, VM Agent 상태 |
| IP Flow Verify가 NSG Deny 반환 | 단독 판정하지 않고 effective Admin 규칙·실제 HTTP를 대조 |
| effective Admin 규칙은 허용, HTTP는 실패 | 서비스, 양방향 `/16` 경로, Firewall TCP 8080 정책 |
| 복구 후 Hub→A가 계속 Deny | 임시 규칙 삭제 읽기와 SecurityAdmin **재배포**·전파 확인 |

## 완료 체크

- VM보다 먼저 Firewall·AVNM 경로를 확인했고 Spoke NAT/Public IP를 만들지 않았습니다.
- Hub NAT만 연결하고 양쪽 Spoke NIC의 실제 `/16`·`/0` 경로를 확인했습니다.
- 좁은 세 AlwaysAllow의 effective 규칙·HTTP 증거와 한 Deny의 차단·복구 증거를 확인했습니다.
- 임시 Deny를 제거하고 같은 리전에 복구 구성을 재배포했습니다.

## 다음 단계

- [이전: Firewall·AVNM Routing](04-connectivity-nsg.md)
- [다음: Firewall 로그와 통신 검증](06-routing-validation.md)
