# 00. Azure 첫걸음

> 목표 시간 15분. 네트워크를 만들기 전에 “무엇을 어디에 만들고, 누가 관리하는가”를 이해합니다.

## 목표

구독, 리소스 그룹, 리전, VNet, AVNM의 역할을 구분하고 Landing Zone이 필요한 이유를 설명합니다.

## 1. Azure를 처음 만날 때

👁️ **설명**

회사 사무실을 준비한다고 생각해 보세요. **구독(Subscription)**은 비용과 접근 권한의
큰 관리 경계, **리소스 그룹(Resource Group, RG)**은 함께 관리하고 정리할 자원의 묶음,
**리전(Region)**은 자원이 실행되는 지리적 위치입니다. VM은 가상 컴퓨터입니다.
RG는 폴더처럼 중첩할 수 없고, RG를 삭제하면 그 안의 자원도 삭제됩니다.
RG의 리전은 그룹 메타데이터를 저장하는 위치이며, 그 안의 모든 자원의 실행 위치를
자동으로 정하지는 않습니다. 이번 실습은 혼동을 줄이기 위해 자원도 같은 리전에 만듭니다.

**Landing Zone**은 앱을 올리기 전에 마련하는 공통 운영 기반입니다.
네트워크만이 아니라 계정·권한·정책·로그·비용 관리가 함께 필요합니다.
이번에는 그 원칙을 **단일 구독의 작은 교육용 환경**으로 경험합니다.
RG 세 개를 만든다고 운영용 다중 구독 Landing Zone이 완성되는 것은 아닙니다.

## 2. 사설 네트워크와 주소

👁️ **설명**

**VNet**은 Azure 안의 사설 네트워크이고 **Subnet**은 그 안의 주소 구역입니다.
`172.20.0.0/14`에서 `/14`는 주소 범위의 크기를 나타내는 CIDR 표기입니다.
운영자가 Korea Central에 미리 마련한 **공유 AVNM IPAM pool**이 세 VNet에
서로 다른 `/20` CIDR을 동적으로 배정합니다. `/24`와 `/26`은 각각 해당 VNet
안에 속하는 더 작은 Subnet입니다. 정확한 주소는 미리 알 수 없으며 모듈 02에서
배포 결과를 읽어 확인합니다.
Azure는 Subnet마다 앞의 네 주소와 마지막 주소를 예약하므로 `.1`을 VM 주소로 고정하지 않습니다.

| 구역 | VNet | Subnet | 목적 |
|---|---|---|---|
| Hub | pool 할당 `/20` | `snet-management` `/24`, `AzureFirewallSubnet` `/26` | 공통 기능, 교육용 검사 VM·Firewall |
| Spoke A | 별도 pool 할당 `/20` | `snet-workload` `/24` | 첫 번째 워크로드 |
| Spoke B | 별도 pool 할당 `/20` | `snet-workload` `/24` | 두 번째 워크로드 |

겹치지 않는 주소를 쓰면 어느 네트워크로 보내야 하는지 구분할 수 있습니다.
같은 pool의 할당 중복은 IPAM이 막지만 pool 외부 네트워크와의 충돌은 운영자가
사전에 조사해야 합니다. 공유 RG와 pool은 참가자의 모듈 07 정리 대상이 아닙니다.
이번 실습에서는 참가자가 네 방향 Peering을 직접 만들지 않고,
**AVNM(Azure Virtual Network Manager)**가 Hub↔Spoke Peering을 중앙에서 관리합니다.
Hub와 각각 연결해도 Spoke끼리 자동으로 연결되지는 않습니다. 이를
**비전이성(non-transitivity)**이라고 합니다. 모듈 04의 A→B 차단 검사는
직접 A↔B Peering은 만들지 않으며, 모듈 04에서 Firewall·Routing을 준비한 뒤
Spoke 간 통신을 확인합니다. 피어링만으로 Spoke 간 transit이 생기지는 않습니다.

## 3. AVNM이 연결을 관리하는 방법

👁️ **설명**

AVNM은 여러 VNet의 연결 구성을 **관리 계층(control plane)**에서 선언하고 배포하는 서비스입니다.
이 워크숍에서는 세 가지 용어를 먼저 구분합니다.

| 용어 | 이번 실습에서 하는 일 |
|---|---|
| AVNM | 구독 범위의 연결 구성을 중앙 관리합니다. |
| Network Group | Spoke A와 Spoke B를 정적으로 묶어 Connectivity 대상 집합을 만듭니다. |
| Connectivity Configuration | Hub VNet과 Spoke Network Group을 Hub-and-Spoke 토폴로지로 연결하라고 선언합니다. |

Connectivity Configuration은 만든 즉시 적용되지 않습니다. **Korea Central에 commit/deploy**해야
실제 Hub↔Spoke Peering이 생성됩니다. 즉, 리전 대상 배포가 빠지면 선언만 있고 연결은 없습니다.
또한 AVNM은 데이터 경로의 라우터가 아닙니다. 모듈 04에서 AVNM Routing과
Firewall을 준비하기 전에는 Spoke A→B 패킷을 대신 전달하지 않습니다.

## 4. 자주 혼동하는 보안 기능

👁️ **설명**

| 기능 | 답하는 질문 | 이 과정의 예 |
|---|---|---|
| RBAC | 누가 Azure 자원을 관리할 수 있나? | 참가자가 VM의 Run Command를 실행 |
| NSG | 어느 IP·포트의 패킷을 허용하나? | Hub에서 Spoke의 TCP 8080 허용 |
| NAT Gateway | VM이 어떤 공인 IP로 인터넷에 나가나? | 관리 명령의 결과 반환 |
| Azure Firewall | 중앙에서 어떤 통신을 허용하고 기록하나? | 모듈 05–06에서 Spoke A→B 검사 |

통신은 **목적지까지 가는 경로**, **통과하는 보안 규칙**, **대상 VM에서 실행 중인 서비스**가
모두 맞아야 성공합니다. 문이 열려 있어도 길이 없거나 목적지의 서버가 꺼져 있으면 실패합니다.
NSG의 Allow는 길을 만들지 않고, Peering의 Connected는 TCP 8080 서비스를 시작하지 않습니다.
AVNM의 Connected 상태도 마찬가지로 **연결 구성의 적용 결과**일 뿐, Spoke 간 transit 경로를 자동으로
만들어 주지는 않습니다.

인터넷에서 VM으로 들어오는 **인바운드**와 VM이 먼저 인터넷에 연결하는 **아웃바운드**도
구분하세요. NAT Gateway는 후자의 출구입니다. NAT의 공인 IP가 있다고 인터넷 사용자가
그 IP로 VM의 SSH나 실습 웹 서버에 접속할 수 있는 것은 아닙니다.

⚠️ **주의**

**사설 IP는 암호화나 인증이 아닙니다.** 실습은 민감 정보 없는 HTTP 응답만
사용합니다. 운영 앱에는 HTTPS와 인증·인가를 별도로 적용해야 합니다.

## Portal 확인

👁️ **설명**

방금 배운 구독·RG·VNet이 Portal에서 각각 어디에 표시되는지 살펴봅니다. 이번 단계는 메뉴 탐색만 합니다.

🟢 **실행**

Azure Portal 검색창에서 **Subscriptions**, **Resource groups**, **Virtual networks**를
각각 찾아보세요. 아직 리소스를 만들 필요는 없습니다.
Portal 메뉴 이름은 언어와 업데이트에 따라 달라질 수 있습니다.

📋 **확인**

구독 목록과 RG·VNet 목록 화면이 서로 구분되는지 확인합니다.
아직 실습 자원이 없어도 정상이며, 이 모듈에서는 메뉴 위치만 익힙니다.

## 트러블슈팅

| 증상 | 확인 |
|---|---|
| 구독 목록이 비어 있음 | 오른쪽 위 Directory + subscriptions에서 올바른 tenant 선택 |
| 메뉴 이름이 다름 | Portal 상단 검색창에서 영문 서비스 이름 검색 |
| CIDR이 낯설음 | 배정된 각 `/20` 안에 `/24`와 `/26` Subnet이 들어간다는 점을 먼저 이해 |

## 완료 체크

- 구독과 RG의 차이를 설명할 수 있습니다.
- AVNM, Network Group, Connectivity Configuration의 역할을 설명할 수 있습니다.
- RBAC와 NSG가 다른 문제를 해결한다는 것을 이해했습니다.
- 이번 실습이 운영 Landing Zone 전체가 아니라는 것을 이해했습니다.

## 다음 단계

- [워크숍 개요](../README.md)
- [다음: 실습 준비](01-prerequisites.md)
