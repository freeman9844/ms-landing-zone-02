# 처음 시작하는 Azure Landing Zone: Hub & Spoke 워크숍

Azure Virtual Network Manager를 사용하는 독립 저장소
`jungwoonlee_microsoft/ms-landing-zone-02`의 루트에서 실행합니다.

> Azure가 처음인 참가자를 위한 한국어 핸즈온입니다. **전체 목표 시간 185–220분** 동안
> Cloud Shell과 Portal로 Hub & Spoke를 만들고, AVNM 연결·라우팅·보안 정책과
> 중앙 Firewall·로그를 확인한 뒤 안전하게 정리합니다.

**처음이라면 [00. Azure 첫걸음](docs/00-azure-basics.md)부터 시작하세요.**
로컬 개발 도구나 컨테이너 지식은 필요하지 않습니다.

## 실습을 진행하는 방법

각 실습 단계는 **👁️ 설명 → 🟢 실행 → 📋 확인** 순서입니다.
설명으로 목적을 이해하고, 한 블록씩 실행한 뒤 확인 항목과 실제 결과를 비교합니다.
비용·삭제 등은 **⚠️ 주의**로 구분합니다. 개념만 배우는 단계에는 실행 명령이 없으며,
모듈 끝에서 Portal 확인과 완료 체크를 진행합니다.
실행 블록의 `#`로 시작하는 한글 주석도 함께 복사해도 됩니다. 주석은 실행되지 않습니다.
명령은 모두 저장소 루트의 **Cloud Shell Bash**에서 실행하며, VM 안에서 직접 입력하지 않습니다.
`scripts/run-vm.sh`가 필요한 명령만 VM으로 전달합니다.

처음 보는 Bash 문법과 공통 함수는 [실행 블록 읽는 법](docs/01-prerequisites.md#실행-블록-읽는-법)을
먼저 확인하세요. 블록 전체를 실행한 뒤 결과를 비교하고, 오류가 나면 다음 블록으로 넘어가지 않습니다.
특히 **예상된 통신 차단**과 **배포·검증 명령의 오류**는 다릅니다. 검증기는 차단 이유까지
확인해야 `PASS`를 출력합니다. 중간 실패 시에는 해당 모듈의 복구 또는 공통 정리 절차를 따릅니다.

## 무엇을 배우나요?

구독·리소스 그룹·리전을 구분하고, 겹치지 않는 네트워크를 설계합니다.
모듈 03에서는 AVNM(Azure Virtual Network Manager)의 세 범위와 Network Group으로
Hub↔Spoke 연결을 배포합니다. 모듈 04에서는 VM을 만들기 전에 Firewall과 AVNM
Routing으로 Spoke의 왕복 경로와 인터넷 출구를 준비합니다. 모듈 05에서는 사설 VM과
AVNM Security Admin 규칙으로 정상·차단·복구 통신을 검증합니다. 모듈 06에서는
Firewall의 Allow/Deny 로그와 아웃바운드를 확인합니다. AVNM은 연결·경로·L4 정책을
중앙 관리하지만 Firewall의 FQDN 검사·로그나 NAT 주소 변환을 대신하지 않습니다.
**모듈 00–07을 순서대로 진행하는 하나의 과정**이며, Firewall과 최종 정리까지 모두 포함합니다.

이 과정은 **단일 구독의 교육용 축소 Landing Zone**입니다. 운영 Landing Zone 전체의
보안·가용성 인증이나 자동 구축 도구가 아닙니다. 관리 그룹·다중 구독·Policy 상속은
[운영 전환 대응표](docs/07-cleanup-production.md#운영-landing-zone으로-확장하기)에서 설명합니다.

## 1단계: AVNM 연결과 Firewall 경로 준비

```mermaid
flowchart LR
  subgraph H["Hub · 10.0.0.0/16"]
    HV["교육용 검사 VM"]
    HN["NAT Gateway"]
    HV -.-> HN
  end
  subgraph A["Spoke A · 10.10.0.0/16"]
    AV["응답 VM · AVNM Security Admin"]
  end
  subgraph B["Spoke B · 10.20.0.0/16"]
    BV["응답 VM · AVNM Security Admin"]
  end
  F["Hub Azure Firewall"]
  HV -->|"Peering · HTTP 8080"| AV
  HV -->|"Peering · HTTP 8080"| BV
  AV -->|"AVNM Routing"| F
  BV -->|"AVNM Routing"| F
```

VM은 모두 private IP만 사용합니다. Hub VM 관리용 NAT에만 NAT Public IP가 있습니다.
Spoke NAT는 처음부터 만들지 않으며 Spoke outbound는 Firewall 경로를 사용합니다.
Cloud Shell의 Run Command는 Azure 관리 기능과 VM agent를 이용합니다.

**모듈 04에서 Firewall 경로가 준비되기 전에는 Spoke VM을 만들지 않습니다.**
따라서 이전 과정의 “A→B 경로 부재” 실험은 수행하지 않습니다.
Hub VM은 교육용 검사 도구이며, 운영 애플리케이션을 Hub에 배치하는 권장이 아닙니다.

## 2단계: 중앙 보안 정책과 Firewall 로그 검증

```mermaid
flowchart LR
  A["Spoke A VM"] -->|"상대 Spoke /16 AVNM 경로"| F["Hub Azure Firewall Standard"]
  F -->|"AVNM Always Allow · Firewall TCP 8080"| B["Spoke B VM"]
  B -->|"응답 /16 AVNM 경로"| F
  F --> A
  A -.->|"default route"| F
  B -.->|"default route"| F
  F -.-> I["허용한 인터넷 통신"]
  F -.-> L["Log Analytics"]
```

Spoke 간 요청·응답은 Firewall을 통과합니다. Hub의 검사 VM→Spoke는 직접 Peering을
유지하므로 **모든 통신이 Firewall을 거친다고 주장하지 않습니다.** Security Admin
`Always Allow`는 기본 NSG 차단 평가를 우회합니다. 두 Spoke에는 처음부터 NAT가 없고,
Hub NAT는 최종 정리까지 유지됩니다.

## 사전 요구사항

| 항목 | 필요한 준비 |
|---|---|
| Azure 계정 | 실습용 구독의 Contributor 또는 운영자가 준비한 동등한 권한 |
| 브라우저 | Azure Portal 및 Cloud Shell **Bash** |
| GitHub | 이 저장소를 clone할 수 있는 권한; 비공개일 때 인증 필요 |
| 기본 리전 | Korea Central, Standard_B2als_v2 3대에 필요한 총 6 vCPU와 Basv2-family quota |
| 시간과 비용 | 목표 시간보다 배포가 길어질 수 있으며 종료 시 반드시 cleanup |

Owner나 역할 할당 권한은 이 워크숍에서 요구하지 않습니다. 조직의 Policy·할당량·
지역 용량 제한은 참가자 구독에서 별도로 확인합니다.

## 모듈 목차

| # | 모듈 | 완료하면 할 수 있는 일 | 목표 시간 |
|---|---|---|---:|
| 00 | [Azure 첫걸음](docs/00-azure-basics.md) | 구독·RG·리전·Landing Zone의 목적 설명 | 15분 |
| 01 | [실습 준비](docs/01-prerequisites.md) | Cloud Shell·권한·상태 복구·quota 확인 | 15분 |
| 02 | [네트워크 뼈대](docs/02-network-foundation.md) | Hub·Spoke·Subnet·NSG 준비 | 20분 |
| 03 | [AVNM 연결 관리](docs/03-avnm-connectivity.md) | 세 범위·Network Group·Hub-and-Spoke 연결 배포 | 25분 |
| 04 | [Firewall·AVNM Routing](docs/04-connectivity-nsg.md) | Firewall·진단 및 VM 생성 전 왕복 경로 준비 | 35–45분 |
| 05 | [VM·AVNM Security Admin](docs/05-firewall.md) | 사설 VM 통신의 중앙 L4 허용·차단·복구 | 35–45분 |
| 06 | [경로와 Firewall 검증](docs/06-routing-validation.md) | 실제 경로·Allow/Deny 로그·egress 검증 | 30–40분 |
| 07 | [정리와 운영 전환](docs/07-cleanup-production.md) | 정확한 실습 리소스 삭제와 운영 차이 이해 | 10–15분 |
| | **전체 합계** | | **185–220분** |

모듈 04 이후에도 같은 실행 ID와 리소스를 유지한 채 **05 → 06 → 07**로 진행합니다.
목표 시간은 배포·정책 반영·로그 수집·삭제 대기에 따라 늘어날 수 있습니다.
중도 중단 시에는 남은 실습 대신 모듈 07의 정리를 실행하세요.

<a id="비용과정리"></a>
## 비용과 정리

| 항목 | 모듈 04까지 | 모듈 05–06에서 변화 | 유의사항 |
|---|---:|---|---|
| VM·OS 디스크·NIC | 없음 | 각 3개 | VM deallocate 후에도 디스크 비용 유지 |
| NAT Gateway | 없음 | Hub에만 1개 | 유휴 상태에도 시간 과금 |
| Standard Public IP | Firewall용 1개 | Hub NAT용 1개 추가 | 연결·할당 상태에 따라 비용 발생 |
| Azure Firewall Standard | 1개 | 동일 | 배포·유휴 시간 및 처리량 과금 |
| Azure Virtual Network Manager | 모듈 03부터 1개 | 동일 | 관리 범위와 구성 사용량에 따라 비용이 발생할 수 있음 |
| Log Analytics | 1개 | 동일 | 수집량과 보존에 따른 비용 |
| Peering·전송 | 사용량 기반 | 사용량 기반 | 반복/대량 부하 검사는 하지 않기 |

고정 금액이나 무료 사용을 약속하지 않습니다.
[가격 계산기](https://azure.microsoft.com/pricing/calculator/),
[VM](https://azure.microsoft.com/pricing/details/virtual-machines/linux/),
[NAT](https://azure.microsoft.com/pricing/details/azure-nat-gateway/),
[Firewall](https://azure.microsoft.com/pricing/details/azure-firewall/),
[Virtual Network Manager](https://azure.microsoft.com/pricing/details/azure-virtual-network-manager/),
[Monitor](https://azure.microsoft.com/pricing/details/monitor/)에서 리전·시간을 확인하세요.

**완료·실패 여부와 관계없이 [cleanup](docs/07-cleanup-production.md)을 실행하세요.**
대상은 `rg-lzbegin-hub-{runId}`, `rg-lzbegin-spokea-{runId}`, `rg-lzbegin-spokeb-{runId}`입니다.
공유 Network Watcher와 Cloud Shell 저장소는 삭제하지 않습니다.

## 세션이 끊겼을 때

Cloud Shell 변수는 새 세션에 남지 않습니다. [상태 복구](docs/01-prerequisites.md#세션-재연결-시-변수-복구)로
`.workshop-state/{runId}.json`을 읽고 **원래 실행 ID**를 사용합니다.
이 파일과 실습용 키는 Git에서 제외됩니다. 임시 Cloud Shell이면 종료 전에 상태 JSON을 내려받으세요.

## 진행 전 알아둘 한계

- 사설 HTTP는 전송 암호화와 인증이 아닙니다. 비민감 응답만 사용합니다.
- Run Command는 높은 관리 권한입니다. 신뢰할 수 없는 스크립트를 실행하지 않습니다.
- Firewall 규칙의 `AzureCloud:443`은 자사 tenant 전용 허용이 아닙니다.
- 기본 VM은 관리형 디스크의 플랫폼 암호화를 사용합니다. host encryption·guest ADE와
  VM extension 금지 권고에는 [명시적인 교육용 예외](docs/maintainer-validation.md#보안-검사-예외)가 있습니다.
- **2026-09-24 재리허설은 이전 NSG·수동 UDR·Spoke NAT 구성에 대한 기록입니다.**
  이 AVNM Routing·Security Admin 재설계는 유료 자원을 사용하는 Azure 실환경에서
  아직 리허설하지 않았습니다. 개최 전 별도 실환경 검증이 필요합니다.

## 태깅 범례와 트러블슈팅

| 표시 | 읽는 방법 |
|---|---|
| 👁️ **설명** | 작업 목적, 개념과 리소스 관계를 먼저 읽습니다. |
| 🟢 **실행** | 바로 아래 명령 블록이나 Portal 작업을 수행합니다. |
| 📋 **확인** | 실제 출력의 이름·값·상태를 제시된 기준과 비교합니다. |
| ⚠️ **주의** | 보안·비용·삭제·실패 복구에 관한 조건을 확인합니다. |

각 표시는 본문과 분리된 줄에 배치합니다. 확인 항목에 포함된 출력 예시와 Portal 이미지는
비교를 돕는 참고 자료이며, 자신의 실제 실행 증거가 아닙니다.

| 증상 | 이동 |
|---|---|
| 권한·quota·상태 파일·소스 인증 | [사전 준비](docs/01-prerequisites.md#트러블슈팅) |
| 주소·Peering 상태 | [네트워크](docs/02-network-foundation.md#트러블슈팅), [AVNM 연결 관리](docs/03-avnm-connectivity.md#트러블슈팅) |
| Run Command·HTTP·Security Admin | [VM·AVNM Security Admin](docs/05-firewall.md) |
| Firewall·진단·로그 지연 | [Firewall 준비](docs/04-connectivity-nsg.md), [경로와 보안 검증](docs/06-routing-validation.md#portal-확인과-트러블슈팅) |
| 중도 실패·삭제 지연 | [정리](docs/07-cleanup-production.md#트러블슈팅) |

## 참고 자료

- [Azure Landing Zone 개요](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/landing-zone/)
- [CAF 네트워크 설계 권장 사항](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/traditional-azure-networking-topology)
- [Hub & Spoke 아키텍처](https://learn.microsoft.com/azure/architecture/networking/architecture/hub-spoke)
- [Linux Run Command 요구사항](https://learn.microsoft.com/azure/virtual-machines/linux/run-command)
- [NAT Gateway](https://learn.microsoft.com/azure/nat-gateway/nat-overview)
- [NSG 규칙](https://learn.microsoft.com/azure/virtual-network/network-security-groups-overview)
- [Azure Firewall 구조화 로그](https://learn.microsoft.com/azure/firewall/firewall-structured-logs)
- [교재 형식 참고 워크숍](https://github.com/freeman9844/aca-github-runner-workshop-private/tree/master)

참고 교재의 진행 형식을 활용했으며 원본 문장·코드·이미지를 복사하지 않았습니다.
