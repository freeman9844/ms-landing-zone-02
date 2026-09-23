# 06. 경로와 중앙 보안 검증

> 목표 시간 30–45분. 왕복 UDR과 Firewall 허용·차단 증거를 확인합니다.
> 로그 수집 대기와 NAT 삭제 단계별 재검증을 포함하면 더 오래 걸릴 수 있습니다.

## 공통 준비

👁️ **설명**

모듈 05의 Firewall·세 Allow collection·진단 수집이 모두 필요합니다.
이번 모듈에서는 **Spoke A → Firewall → Spoke B**의 왕복 통신을 만들고,
두 Spoke의 인터넷 출구도 Firewall로 옮깁니다. Hub VM → Spoke HTTP는 기존
직접 Peering 경로를 유지하므로 모든 통신이 Firewall을 통과한다고 해석하지 마세요.
모듈 01의 `STATE_FILE`로 아래 준비를 한 번 실행하고 같은 Cloud Shell 세션을 사용합니다.
새 세션에서 `STATE_FILE`이 비어 있으면 기존 `.workshop-state/<실행 ID>.json` 경로를
묻고, 설정돼 있으면 다시 묻지 않습니다. 다른 실습/구독으로 전환할 때는
[상태 복구](01-prerequisites.md#세션-재연결-시-변수-복구)를 실행합니다.
**한 블록 실행 → 확인 → 다음 단계** 순서를 지키세요.
검사/조회 실패 시 `&&` 뒤의 변경은 실행되지 않습니다. 다음 블록으로 넘어가지 말고 원인을 해결합니다.
구독과 세 RG의 소유권은 여기서 한 번 확인합니다. 일반 생성·조회·규칙 변경의 중복 검사는 생략하되,
실제 경로 전환과 NAT 삭제 직전에는 현재 상태와 대상 소유권을 다시 확인합니다.

🟢 **실행**

<!-- exec:prepare-06 -->
```bash
source scripts/workshop-common.sh &&
source scripts/workshop-safety.sh &&
ensure_state_file &&
load_run "$STATE_FILE" &&
assert_subscription &&
assert_owned_rg "$RG_HUB" &&
assert_owned_rg "$RG_SPOKEA" &&
assert_owned_rg "$RG_SPOKEB"
```

📋 **확인**

오류 없이 프롬프트로 돌아옵니다. 아직 경로는 바꾸지 않았습니다.
`firewall_ready_ip`는 위 준비에서 `workshop-safety.sh`를 읽어 **현재 Cloud Shell 세션에
등록된 함수**입니다. `command not found`가 나오면 재접속했거나 공통 준비를 건너뛴
상태이므로 같은 셸에서 이 준비 블록을 다시 실행한 뒤 실패한 경로 단계로 돌아가세요.
해당 `&&` 뒤의 경로 생성 명령은 실행되지 않았습니다.

`workshop-safety.sh`의 세 함수는 **읽기 전용 선행 검사**입니다. 실제 변경 CLI는 아래에 그대로 보입니다.

| 함수 | 매 호출 시 실제로 확인하는 것 |
|---|---|
| `firewall_ready_ip` | Hub 소유권, Firewall 완료·정확한 ID/Policy·유효 사설 IP, 정확한 workspace/전용 진단/두 category, 세 collection의 Allow |
| `assert_route_tables_ready` | 두 Spoke 소유권, 양쪽 `/16`·`/0`과 next hop, 네 방향 Connected/전달 허용 |
| `assert_spoke_nat_removal` | 삭제 단계에 맞는 현재 Subnet 연결·정확한 NAT/Public IP ID·네 소유 태그·참조 관계 |

검사 성공을 파일이나 전역 승인 플래그로 저장하지 않습니다. 중간에 상태가 바뀌면 다음 작업에서 다시 거부합니다.
준비와 달리 이 **작업별 안전 검사**는 생략하면 안 됩니다.

## 1. 경로 원리

👁️ **설명**

UDR(User Defined Route)는 목적지별 다음 홉을 지정합니다. A→B 요청뿐 아니라
B→A 응답도 같은 Firewall을 지나야 합니다. 경로는 **가장 길게 일치하는 접두사**를 선택합니다.
`10.20.1.x` 목적지에는 `/16`이 `/8`이나 `/0`보다 구체적입니다.
인터넷용 `/0`만 넣으면 시스템의 `10.0.0.0/8 → None` 버림 경로를 이기지 못합니다.
예를 들어 A의 `10.10.1.x`에서 B의 `10.20.1.x`로 보내는 요청에는 A 테이블의
`10.20.0.0/16`을, B의 응답에는 B 테이블의 `10.10.0.0/16`을 적용합니다.
한쪽만 있으면 요청이 도착해도 응답이 다른 길로 돌아갈 수 있습니다.

| 적용 Subnet | 목적지 | next hop |
|---|---|---|
| Spoke A | `10.20.0.0/16` | Firewall 사설 IP |
| Spoke B | `10.10.0.0/16` | Firewall 사설 IP |
| 두 Spoke | `0.0.0.0/0` | Firewall 사설 IP |

`VirtualAppliance`는 여기서 Azure Firewall을 뜻합니다. `/0`은 더 구체적인 경로가 없는 목적지에
적용하므로 Hub와 직접 통신하는 Peering 경로는 유지됩니다.
UDR이 Firewall 규칙을 허용으로 바꾸지는 않습니다. 테이블을 생성만 해도 VM 경로는 바뀌지 않습니다.
**경로 테이블 생성 → 경로 추가 → Subnet 연결**을 분리하는 이유는, 양쪽 경로가 준비되기 전에
실제 VM 트래픽을 바꾸지 않기 위해서입니다. 연결 후에는 NIC의 유효 경로로 결과를 확인합니다.
[Microsoft Learn의 경로 선택 설명](https://learn.microsoft.com/azure/virtual-network/virtual-networks-udr-overview#how-azure-selects-routes-for-traffic-routing)도 참고하세요.

## 2. Peering에서 전달 트래픽 허용

👁️ **설명**

기존 네 연결의 속성만 변경합니다. 새 A↔B 직접 Peering을 만들지 않습니다.
방화벽이 A에서 받은 패킷을 B로 전달하면 B에는 **A VM이 시작한 트래픽이
Hub Peering을 거쳐 들어옵니다.** 각 VNet의 Peering은 별도 자원이므로
Hub→A, A→Hub, Hub→B, B→Hub 네 방향에서 전달 허용을 설정합니다.
이 옵션은 패킷 전달을 허용할 뿐 경로를 만들거나 Firewall 규칙을 대신하지 않습니다.

### 2-1. Hub → A

👁️ **설명**

Hub 쪽 `hub-to-spokea` Peering의 전달 트래픽 허용을 켭니다.
직접 연결만 사용하던 설정을 Firewall이 중계하는 경로에 맞춰 준비합니다.

🟢 **실행**

<!-- exec:forward-hub-to-spokea -->
```bash
az network vnet peering update -g "$RG_HUB" --vnet-name "vnet-lzbegin-hub-$RUN_ID" \
  -n hub-to-spokea --set allowForwardedTraffic=true -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

`hub-to-spokea`의 `allowForwardedTraffic=true`. 이 옵션만으로 UDR이 생기지는 않습니다.

### 2-2. A → Hub

👁️ **설명**

A 쪽에서도 Hub Peering의 전달 트래픽을 허용합니다.
Hub에서 Firewall을 거쳐 전달되는 패킷을 받을 수 있도록 반대 방향 설정도 변경합니다.
두 방향의 설정을 혼동하지 않도록 명령의 RG·VNet·Peering 이름이 모두 A를 가리키는지 확인하세요.

🟢 **실행**

<!-- exec:forward-spokea-to-hub -->
```bash
az network vnet peering update -g "$RG_SPOKEA" --vnet-name "vnet-lzbegin-spokea-$RUN_ID" \
  -n spokea-to-hub --set allowForwardedTraffic=true -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

A의 역방향 연결도 전달을 허용합니다.

### 2-3. Hub → B

👁️ **설명**

Hub와 B 사이의 Peering에도 같은 전달 허용을 적용합니다.
A 연결을 수정한 것만으로 B 연결의 속성이 바뀌지는 않습니다.

🟢 **실행**

<!-- exec:forward-hub-to-spokeb -->
```bash
az network vnet peering update -g "$RG_HUB" --vnet-name "vnet-lzbegin-hub-$RUN_ID" \
  -n hub-to-spokeb --set allowForwardedTraffic=true -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

이번 대상은 `hub-to-spokeb`입니다.

### 2-4. B → Hub

👁️ **설명**

B 쪽의 Hub Peering을 수정하여 네 방향 설정을 마칩니다.
직접 A↔B Peering을 추가하지 않고 기존 Hub 경유 구조를 유지합니다.

🟢 **실행**

<!-- exec:forward-spokeb-to-hub -->
```bash
az network vnet peering update -g "$RG_SPOKEB" --vnet-name "vnet-lzbegin-spokeb-$RUN_ID" \
  -n spokeb-to-hub --set allowForwardedTraffic=true -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

네 방향 모두 전달 허용입니다. 게이트웨이 공유 설정은 바꾸지 않았습니다.

## 3. Spoke A의 경로 테이블과 두 경로

👁️ **설명**

**두 Spoke의 테이블을 모두 완성한 후** 5절에서 Subnet에 연결합니다.
각 경로 생성은 현재 Firewall IP를 조회하므로 앞 작업의 임시 변수에 의존하지 않습니다.
`firewall_ready_ip`는 IP만 출력하기 전에 Firewall·Policy의 Allow 규칙과 진단 연결까지
검사합니다. 준비가 덜 된 상태라면 경로를 만드는 대신 여기서 멈춥니다.

### 3-1. A 테이블

👁️ **설명**

A Subnet에서 사용할 경로 테이블을 먼저 만듭니다.
아직 Subnet에 연결하지 않으므로 이 명령만으로 현재 통신 경로가 바뀌지는 않습니다.

🟢 **실행**

<!-- exec:route-table-spokea -->
```bash
az network route-table create -g "$RG_SPOKEA" -n "rt-lzbegin-spokea-$RUN_ID" -l "$LOCATION" \
  --tags workshop=lz-beginner environment=lab "runId=$RUN_ID" managedBy=workshop -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

A RG 안에 `rt-lzbegin-spokea-<실행 ID>`가 생깁니다. 아직 Subnet에는 연결하지 않습니다.

### 3-2. A → B `/16`

👁️ **설명**

B 주소 공간으로 가는 트래픽의 next hop을 Firewall 사설 IP로 지정합니다.
`/16` 경로가 시스템의 더 넓은 버림 경로보다 우선하도록 준비합니다.
next hop에는 **Firewall Public IP가 아닌** Hub `AzureFirewallSubnet`의 사설 IP를 넣습니다.

🟢 **실행**

<!-- exec:route-spokea-other -->
```bash
fw_ip=$(firewall_ready_ip) &&
az network route-table route create -g "$RG_SPOKEA" --route-table-name "rt-lzbegin-spokea-$RUN_ID" \
  -n to-other-spoke --address-prefix 10.20.0.0/16 \
  --next-hop-type VirtualAppliance --next-hop-ip-address "$fw_ip" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

목적지는 A 자신이 아닌 B의 `10.20.0.0/16`, next hop은 Firewall 사설 IP입니다.

### 3-3. A의 인터넷 `/0`

👁️ **설명**

A에서 더 구체적인 경로가 없는 목적지로 나갈 때도 Firewall을 사용하도록 기본 경로를 추가합니다.
앞의 B 전용 `/16` 경로를 대신하는 것이 아니라 함께 사용합니다.
예를 들어 외부 IP 확인 서비스는 B의 `/16`에 속하지 않아 이 `/0` 경로를 사용합니다.

🟢 **실행**

<!-- exec:route-spokea-internet -->
```bash
fw_ip=$(firewall_ready_ip) &&
az network route-table route create -g "$RG_SPOKEA" --route-table-name "rt-lzbegin-spokea-$RUN_ID" \
  -n to-internet --address-prefix 0.0.0.0/0 \
  --next-hop-type VirtualAppliance --next-hop-ip-address "$fw_ip" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

`to-internet`은 `0.0.0.0/0`, 앞 경로와 같은 Firewall next hop입니다.

## 4. Spoke B의 반환 경로

👁️ **설명**

A의 테이블을 그대로 B에 연결하지 않습니다. B에서 A로 향하는 목적지는
`10.10.0.0/16`이므로 반대 주소를 가진 별도 테이블이 필요합니다.
이 테이블도 **경로 두 개를 모두 채운 뒤** 5절에서 B Subnet에 연결합니다.

### 4-1. B 테이블

👁️ **설명**

B Subnet 전용 경로 테이블을 만듭니다.
요청 방향만 바꾸면 왕복 경로가 불일치할 수 있으므로 B의 반환 경로도 따로 준비합니다.

🟢 **실행**

<!-- exec:route-table-spokeb -->
```bash
az network route-table create -g "$RG_SPOKEB" -n "rt-lzbegin-spokeb-$RUN_ID" -l "$LOCATION" \
  --tags workshop=lz-beginner environment=lab "runId=$RUN_ID" managedBy=workshop -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

B의 RG 안에 B 테이블이 생깁니다.

### 4-2. B → A `/16`

👁️ **설명**

B에서 A로 돌아가는 응답이 같은 Firewall을 거치도록 A 주소 공간의 경로를 추가합니다.
A 테이블과 목적지 주소가 반대라는 점을 확인하세요.
`to-other-spoke`는 두 테이블에서 이름은 같지만 **목적지 주소는 서로 다릅니다.**

🟢 **실행**

<!-- exec:route-spokeb-other -->
```bash
fw_ip=$(firewall_ready_ip) &&
az network route-table route create -g "$RG_SPOKEB" --route-table-name "rt-lzbegin-spokeb-$RUN_ID" \
  -n to-other-spoke --address-prefix 10.10.0.0/16 \
  --next-hop-type VirtualAppliance --next-hop-ip-address "$fw_ip" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

A와 반대로 목적지가 `10.10.0.0/16`입니다. 응답이 Firewall을 우회하지 않게 합니다.

### 4-3. B의 인터넷 `/0`

👁️ **설명**

B의 기본 인터넷 경로도 Firewall로 지정합니다.
두 Spoke의 `/16`·`/0` 경로를 모두 만든 뒤에 Subnet 연결로 진행합니다.

🟢 **실행**

<!-- exec:route-spokeb-internet -->
```bash
fw_ip=$(firewall_ready_ip) &&
az network route-table route create -g "$RG_SPOKEB" --route-table-name "rt-lzbegin-spokeb-$RUN_ID" \
  -n to-internet --address-prefix 0.0.0.0/0 \
  --next-hop-type VirtualAppliance --next-hop-ip-address "$fw_ip" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

B에도 `/16`과 `/0` 두 경로가 준비되었습니다.

## 5. Subnet에 연결한 뒤 실제 경로 검증

👁️ **설명**

각 연결 직전에 Firewall·진단·Allow 규칙과 **양쪽 테이블·네 Peering**을 다시 검사합니다.
반대쪽 테이블 생성이나 전달 허용을 빠뜨리면 연결을 거부합니다.
Subnet에 UDR을 연결해야 VM의 유효 경로가 바뀝니다. 테이블이 만들어졌다는 출력만으로
트래픽이 Firewall로 향한다고 판단하지 마세요. NAT는 아직 유지한 채 경로만 전환합니다.

⚠️ **주의**

A만 연결된 짧은 구간은 왕복 경로가 완성되지 않은 상태입니다.
**A 연결 확인 → B 연결 확인 → 전체 검증** 순서이며, 중간 실패 시 아래 복구 지침을 사용합니다.
아직 NAT를 삭제하지 마세요.

### 5-1. A Subnet 연결

👁️ **설명**

현재 Firewall과 양쪽 경로 테이블·Peering을 점검한 뒤 A 테이블을 A Subnet에 연결합니다.
이때부터 A의 경로가 실제로 바뀌며, B 연결까지 완료해야 왕복 구성이 완성됩니다.
`assert_route_tables_ready`는 A/B 테이블 각각의 `/16`·`/0`과 네 Peering의
Connected·전달 허용을 확인합니다. 검사 실패를 무시하고 Subnet만 연결하지 마세요.

🟢 **실행**

<!-- exec:attach-routes-spokea -->
```bash
fw_ip=$(firewall_ready_ip) &&
assert_route_tables_ready "$fw_ip" &&
az network vnet subnet update -g "$RG_SPOKEA" --vnet-name "vnet-lzbegin-spokea-$RUN_ID" -n snet-workload \
  --route-table "rt-lzbegin-spokea-$RUN_ID" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

A Subnet의 `routeTable.id`는 A 테이블입니다. `natGateway`는 그대로 있습니다.

### 5-2. B Subnet 연결

👁️ **설명**

B Subnet에도 B 테이블을 연결하여 왕복 경로를 완성합니다.
A 연결 이후 상태가 달라졌을 수 있으므로 연결 직전 준비 상태를 다시 검사합니다.
이제 A→B 요청과 B→A 응답의 next hop이 모두 같은 Firewall 사설 IP여야 합니다.

🟢 **실행**

<!-- exec:attach-routes-spokeb -->
```bash
fw_ip=$(firewall_ready_ip) &&
assert_route_tables_ready "$fw_ip" &&
az network vnet subnet update -g "$RG_SPOKEB" --vnet-name "vnet-lzbegin-spokeb-$RUN_ID" -n snet-workload \
  --route-table "rt-lzbegin-spokeb-$RUN_ID" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

B Subnet도 자기 테이블을 참조합니다. 이제 왕복 경로 검증으로 이동합니다.

### 5-3. Allow 상태의 실제 증거

👁️ **설명**

검증 스크립트는 현재 통신을 판정하는 단일 목적입니다. 새 연결·NSG·유효 경로·이번 시각 이후 로그·
egress를 묶어 판정하는 내부 검사는 자동화로 남깁니다. 단순 curl 성공/실패로 대체하지 않습니다.
특히 `spokeb` HTTP 응답은 **어디에 도착했는지**, Firewall의 Allow 로그는
**어떤 규칙으로 통과했는지**를 각각 보여 줍니다. 둘 중 하나만으로 전체 경로를 증명하지 않습니다.

🟢 **실행**

<!-- exec:verify-allowed -->
```bash
bash scripts/verify-extension.sh "$STATE_FILE" allowed
```

📋 **확인**

A→B 및 B→A의 `VirtualAppliance` next hop이 Firewall IP입니다.
A→B HTTP 성공과 새 **Allow 로그**, 두 Spoke의 Firewall Public IP egress를 확인합니다.
Hub→B는 직접 `VNetPeering`입니다.

`egress`는 밖으로 나가는 통신입니다. 외부 IP 서비스가 본 출발지와 그 서비스의 유효 경로를
같이 검사합니다. 공인 IP만 같다고 모든 트래픽이 Firewall을 통과한다고 결론내리지 않습니다.
관리 경로가 실패하면 Run Command 결과도 돌아오지 않습니다. 검증 실패를 무시하고 NAT를 지우지 마세요.

## 6. Firewall 차단과 복구

👁️ **설명**

관리·egress 예외는 그대로 두고 `lab-http`만 바꿉니다.
배열 순서를 추측하지 않고 매번 이름으로 유일한 collection 위치를 찾습니다.
NSG와 UDR을 고정하고 Firewall 규칙만 바꿔 **같은 A→B 흐름**의 허용 → 차단 → 복구를
비교합니다. 모듈 04의 Hub→A NSG 차단 실험과 원인이 다릅니다.

### 6-1. HTTP collection을 Deny로 변경

👁️ **설명**

A→B HTTP 실험용 collection만 Deny로 바꿉니다.
관리 통신과 인터넷 출구 확인 규칙은 유지하여 차단 원인을 Firewall 규칙으로 좁힙니다.
`jq`는 collection의 현재 배열 위치를 `lab-http` 이름으로 찾습니다. 이름이 없거나
둘 이상이면 임의 항목을 바꾸지 않고 중단합니다.

🟢 **실행**

<!-- exec:firewall-deny -->
```bash
group=$(az network firewall policy rule-collection-group show -g "$RG_HUB" \
  --policy-name "fwpol-lzbegin-$RUN_ID" -n workshop -o json --subscription "$SUBSCRIPTION_ID") &&
index=$(jq -er 'if (.ruleCollections | type) != "array" then error("Expected collection array") else
  [.ruleCollections | to_entries[] | select(.value.name == "lab-http") | .key] end
  | if length == 1 then .[0] else error("Ambiguous lab-http collection") end' <<< "$group") &&
az network firewall policy rule-collection-group update -g "$RG_HUB" \
  --policy-name "fwpol-lzbegin-$RUN_ID" -n workshop \
  --set "ruleCollections[$index].action.type=Deny" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

`lab-http.action.type=Deny`. 관리 collection은 Allow로 유지합니다.

### 6-2. Deny 증거 검증

👁️ **설명**

HTTP 실패와 같은 흐름의 새 Deny 로그를 함께 확인합니다.
NSG와 경로는 정상인 상태에서 Firewall이 차단했는지 판정합니다.
로그의 출발지 A IP·목적지 B IP·TCP 8080·Action과 **이번 요청 이후의 시각**을 대조합니다.
이전 실험의 Deny 로그나 서버 응답 지연을 새 차단의 증거로 사용하지 않습니다.

🟢 **실행**

<!-- exec:verify-denied -->
```bash
bash scripts/verify-extension.sh "$STATE_FILE" denied
```

📋 **확인**

NSG는 Allow, next hop은 Firewall, HTTP는 실패하며 같은 흐름의 **새 Deny 로그**가 있습니다.
단순 timeout은 차단 성공 증거가 아닙니다.

### 6-3. Allow로 복구

👁️ **설명**

현재 collection 목록에서 `lab-http`의 위치를 다시 찾고 동작만 Allow로 되돌립니다.

⚠️ **주의**

**검증이 실패했어도 복구합니다.** 이전 `index` 변수를 사용하지 않습니다.

🟢 **실행**

<!-- exec:firewall-restore -->
```bash
group=$(az network firewall policy rule-collection-group show -g "$RG_HUB" \
  --policy-name "fwpol-lzbegin-$RUN_ID" -n workshop -o json --subscription "$SUBSCRIPTION_ID") &&
index=$(jq -er 'if (.ruleCollections | type) != "array" then error("Expected collection array") else
  [.ruleCollections | to_entries[] | select(.value.name == "lab-http") | .key] end
  | if length == 1 then .[0] else error("Ambiguous lab-http collection") end' <<< "$group") &&
az network firewall policy rule-collection-group update -g "$RG_HUB" \
  --policy-name "fwpol-lzbegin-$RUN_ID" -n workshop \
  --set "ruleCollections[$index].action.type=Allow" -o json --subscription "$SUBSCRIPTION_ID"
```

📋 **확인**

`lab-http`만 Allow로 돌아왔습니다.

### 6-4. 복구 증거 검증

👁️ **설명**

Allow로 되돌린 뒤 새 HTTP 요청과 로그로 복구를 확인합니다.
이전 Allow 로그를 재사용하지 않고 관리 통신과 인터넷 출구도 다시 검사합니다.
복구는 설정 변경 응답만으로 끝나지 않습니다. HTTP 성공과 **새 Allow 로그**가 함께
돌아와야 차단 실험 전의 통신 상태로 되돌아온 것입니다.

🟢 **실행**

<!-- exec:verify-restored -->
```bash
bash scripts/verify-extension.sh "$STATE_FILE" restored
```

📋 **확인**

HTTP가 `spokeb`를 반환하고 **새 Allow 로그** 및 egress 검증이 통과합니다.

| 단계 | NSG | A↔B 경로 | HTTP | 새 Firewall 로그 |
|---|---|---|---|---|
| allowed | Allow | Firewall | 성공 | Allow |
| denied | Allow | Firewall | 실패 | Deny |
| restored | Allow | Firewall | 다시 성공 | Allow |

## 7. Spoke NAT를 한 단계씩 제거

👁️ **설명**

UDR의 VirtualAppliance가 NAT보다 우선하므로 현재 출구는 Firewall입니다.
중복 비용을 줄이기 위해 **A 분리 → A NAT 삭제 → A Public IP 삭제 → B도 같은 순서**로 진행합니다.
Subnet에서 NAT 연결을 끊는 것과 NAT 자원을 삭제하는 것은 다릅니다.
NAT를 삭제한 뒤에는 연결이 끊긴 Public IP도 별도 자원으로 남으므로 따로 정리합니다.

⚠️ **주의**

**Hub NAT와 Firewall Public IP는 삭제하지 않습니다.**

각 블록 안의 `verify-extension.sh restored`는 그때 새 요청과 로그로 현재 관리·통신·egress를 검증합니다.
분리된 삭제 사이에 멈추거나 재접속할 수 있으므로 **매 작업 직전에 새 검증·현재 소유/참조 검사·확인 입력**을
요구합니다. 이전 PASS나 확인 입력을 재사용하지 않습니다. 반복 검증은 수 분씩 걸릴 수 있습니다.
`assert_spoke_nat_removal`은 읽기 전용이며 삭제 명령을 숨기지 않습니다.
오류/거절 시 그 블록은 자원을 변경하지 않습니다. 이미 완료한 다른 단계는 자동 복구되지 않습니다.

### 7-1. A Subnet에서 NAT 분리

👁️ **설명**

현재 Firewall 경로와 통신을 다시 검증한 뒤 A Subnet의 NAT 연결만 해제합니다.
NAT와 Public IP 자원의 삭제는 다음 두 단계에서 따로 수행합니다.

🟢 **실행**

<!-- exec:remove-spokea-detach -->
```bash
bash scripts/verify-extension.sh "$STATE_FILE" restored &&
assert_spoke_nat_removal spokea detach &&
read -rp "A Subnet에서 NAT만 분리합니다. REMOVE-SPOKE-NAT 입력: " confirm &&
if [[ "$confirm" == REMOVE-SPOKE-NAT ]]; then
  az network vnet subnet update -g "$RG_SPOKEA" --vnet-name "vnet-lzbegin-spokea-$RUN_ID" \
    -n snet-workload --remove natGateway -o json --subscription "$SUBSCRIPTION_ID"
else
  fail "Cancelled"
fi
```

📋 **확인**

A Subnet의 `natGateway`가 없고 route table은 유지됩니다. NAT 자원은 아직 있습니다.

### 7-2. 분리된 A NAT 삭제

👁️ **설명**

현재 Subnet이 분리됐고 NAT의 Subnet 참조가 비었는지 다시 검사합니다.
NAT가 아직 Subnet에 연결돼 있다면 삭제를 시도하지 않습니다.
앞 단계의 분리 결과를 재조회하는 이유는 Azure의 변경 반영이 늦을 수 있기 때문입니다.

🟢 **실행**

<!-- exec:remove-spokea-nat -->
```bash
bash scripts/verify-extension.sh "$STATE_FILE" restored &&
assert_spoke_nat_removal spokea nat &&
read -rp "분리된 A NAT만 삭제합니다. REMOVE-SPOKE-NAT 입력: " confirm &&
if [[ "$confirm" == REMOVE-SPOKE-NAT ]]; then
  az network nat gateway delete -g "$RG_SPOKEA" -n "nat-lzbegin-spokea-$RUN_ID" --subscription "$SUBSCRIPTION_ID"
else
  fail "Cancelled"
fi
```

📋 **확인**

오류 없이 삭제됩니다. 다음 단계가 실제 NAT 부재를 다시 확인합니다.

### 7-3. A NAT용 Public IP 삭제

👁️ **설명**

RG의 NAT 목록 조회가 성공하고 해당 NAT가 **실제로 없어야** 합니다.
조회 오류를 404/부재로 간주하지 않으며 Public IP의 소유 태그와 사용 참조도 검사합니다.
NAT용 IP가 아직 다른 자원에 연결돼 있다면 사용 중인 주소를 잘못 삭제하지 않도록 중단합니다.

🟢 **실행**

<!-- exec:remove-spokea-pip -->
```bash
bash scripts/verify-extension.sh "$STATE_FILE" restored &&
assert_spoke_nat_removal spokea pip &&
read -rp "A NAT용 Public IP만 삭제합니다. REMOVE-SPOKE-NAT 입력: " confirm &&
if [[ "$confirm" == REMOVE-SPOKE-NAT ]]; then
  az network public-ip delete -g "$RG_SPOKEA" -n "pip-lzbegin-spokea-$RUN_ID" --subscription "$SUBSCRIPTION_ID"
else
  fail "Cancelled"
fi
```

📋 **확인**

`pip-lzbegin-spokea-<실행 ID>`만 삭제됩니다. `pip-lzbegin-fw-...`는 대상이 아닙니다.

### 7-4. B Subnet에서 NAT 분리

👁️ **설명**

B도 현재 통신과 대상 참조를 확인한 뒤 Subnet의 NAT 연결부터 해제합니다.
A에서 성공한 결과를 B의 삭제 승인으로 대신하지 않습니다.
B의 NAT·Public IP는 A와 이름이 비슷해도 별도의 자원입니다. 연결 분리 후에도 B의
경로 테이블은 유지되어야 Spoke B의 인터넷 출구가 Firewall을 계속 사용합니다.

🟢 **실행**

<!-- exec:remove-spokeb-detach -->
```bash
bash scripts/verify-extension.sh "$STATE_FILE" restored &&
assert_spoke_nat_removal spokeb detach &&
read -rp "B Subnet에서 NAT만 분리합니다. REMOVE-SPOKE-NAT 입력: " confirm &&
if [[ "$confirm" == REMOVE-SPOKE-NAT ]]; then
  az network vnet subnet update -g "$RG_SPOKEB" --vnet-name "vnet-lzbegin-spokeb-$RUN_ID" \
    -n snet-workload --remove natGateway -o json --subscription "$SUBSCRIPTION_ID"
else
  fail "Cancelled"
fi
```

📋 **확인**

B Subnet의 `natGateway`가 없어지고 route table은 유지됩니다.

### 7-5. 분리된 B NAT 삭제

👁️ **설명**

B NAT에 Subnet 참조가 남지 않았는지 확인하고 NAT 자원만 삭제합니다.
Public IP는 NAT가 실제로 없어진 뒤 다음 단계에서 삭제합니다.

🟢 **실행**

<!-- exec:remove-spokeb-nat -->
```bash
bash scripts/verify-extension.sh "$STATE_FILE" restored &&
assert_spoke_nat_removal spokeb nat &&
read -rp "분리된 B NAT만 삭제합니다. REMOVE-SPOKE-NAT 입력: " confirm &&
if [[ "$confirm" == REMOVE-SPOKE-NAT ]]; then
  az network nat gateway delete -g "$RG_SPOKEB" -n "nat-lzbegin-spokeb-$RUN_ID" --subscription "$SUBSCRIPTION_ID"
else
  fail "Cancelled"
fi
```

📋 **확인**

B NAT만 삭제됩니다. A 단계의 검사 결과를 재사용하지 않았습니다.

### 7-6. B NAT용 Public IP 삭제

👁️ **설명**

B NAT의 부재와 Public IP의 소유권·사용 참조를 검사한 뒤 해당 IP만 삭제합니다.
인터넷 출구로 사용 중인 Firewall Public IP는 유지합니다.

🟢 **실행**

<!-- exec:remove-spokeb-pip -->
```bash
bash scripts/verify-extension.sh "$STATE_FILE" restored &&
assert_spoke_nat_removal spokeb pip &&
read -rp "B NAT용 Public IP만 삭제합니다. REMOVE-SPOKE-NAT 입력: " confirm &&
if [[ "$confirm" == REMOVE-SPOKE-NAT ]]; then
  az network public-ip delete -g "$RG_SPOKEB" -n "pip-lzbegin-spokeb-$RUN_ID" --subscription "$SUBSCRIPTION_ID"
else
  fail "Cancelled"
fi
```

📋 **확인**

B NAT용 IP만 삭제됩니다. Hub NAT와 Firewall IP는 유지됩니다.

### 7-7. 제거 후 전체 통신 검증

👁️ **설명**

두 Spoke NAT를 제거한 최종 상태에서 관리·HTTP·로그·egress를 다시 검사합니다.
삭제 명령의 성공만으로 네트워크 전환이 완료됐다고 판단하지 않습니다.
Hub NAT와 Firewall용 Public IP는 유지됩니다. 두 Spoke에서 관찰되는 출발지 공인 IP는
Firewall용 IP여야 하며, 다음 모듈의 전체 정리까지 비용이 계속 발생합니다.

🟢 **실행**

<!-- exec:verify-after-nat-removal -->
```bash
bash scripts/verify-extension.sh "$STATE_FILE" restored
```

📋 **확인**

두 Spoke NAT 없이도 Run Command·HTTP·새 Allow 로그·Firewall egress가 PASS입니다.
Portal에서도 두 NAT와 그 Public IP가 사라졌는지 확인합니다.

## 전환 실패 시 복구

⚠️ **주의**

**Spoke NAT가 아직 있고 Subnet에 연결되어 있다면**, 두 Spoke Subnet의 Route table 연결을
Portal에서 해제하면 기본 NAT egress로 돌아갑니다. NSG/Firewall을 모두 허용해 우회하지 마세요.
**NAT를 분리하거나 삭제한 뒤라면** UDR 해제만으로는 복구되지 않습니다.
모듈 04의 보조 템플릿을 what-if로 확인하여 필요한 NAT를 재생성·재연결하거나
[공통 cleanup](07-cleanup-production.md)으로 종료합니다.
중간 실패 후 제거 전체를 무작정 재실행하지 마세요. 이미 삭제한 자원 대신 남은 단계의 현재 상태를 확인합니다.
복구 도중에도 Firewall·VM 등 남아 있는 유료 자원의 과금은 계속되므로, 실습을 중단한다면
현재 상태 파일을 보관하고 모듈 07의 정확한 삭제 절차로 종료합니다.

<a id="트러블슈팅"></a>
## Portal 확인과 트러블슈팅

👁️ **설명**

경로는 NIC에서, 허용·차단 증거는 Log Analytics에서 확인합니다. 서로 다른 화면의 결과를 같은 통신 흐름으로 대조합니다.

🟢 **실행**

**NIC → Effective routes**에서 양쪽 `/16`·default route를 확인합니다.
**Log Analytics → Logs → AZFWNetworkRule**에서 SourceIp, DestinationIp, DestinationPort,
Action, TimeGenerated, `_ResourceId`를 대조합니다. 수집 지연은 최대 10분까지 기다립니다.

📋 **확인**

양쪽 Spoke의 상대 주소 공간 `/16`과 `/0` 경로가 Firewall 사설 IP를 가리켜야 합니다.
로그의 주소·포트·시각·Firewall ID가 방금 실행한 검증과 일치하는지 확인합니다.

| 증상 | 조치 |
|---|---|
| `firewall_ready_ip: command not found` | 현재 Cloud Shell Bash에서 위 **공통 준비 전체**를 다시 실행; `workshop-safety.sh`를 별도 프로세스로 실행하지 않기 |
| 연결 성공인데 로그 없음 | workspace/category/시간/리소스 ID 확인; 수집 지연 대기 |
| 테이블 없음·조회 오류 | 진단 설정/실제 트래픽 확인; 오류를 빈 결과나 Deny로 해석하지 않기 |
| `api.loganalytics.io` DNS 오류 | CLI 호스트 DNS/네트워크 복구 후 새 검증 |
| 왕복 중 한쪽만 Firewall | 반대 Spoke `/16`·Subnet 연결 확인 |
| IP 확인 서비스 오류 | `api.ipify.org` 상태·DNS·허용 규칙 확인; 차단 성공으로 처리하지 않기 |
| 이전 Allow/Deny와 혼재 | 새 검증의 시작 시각 이후 로그만 사용 |
| NAT 참조가 남음 | 완료/전파 상태를 조회하고 기다리기; 안전 검사 생략 금지 |

## 완료 체크

- NSG·경로·Firewall 로그로 허용/차단 원인을 구분했습니다.
- 두 Spoke의 관리 경로·egress가 유지되고 `lab-http`가 Allow입니다.
- 비용을 멈추기 위해 최종 cleanup으로 이동합니다.

## 다음 단계

- [이전: Firewall 준비](05-firewall.md)
- [다음: 전체 정리](07-cleanup-production.md)
