# 운영자 검증 안내

참가자 경로는 [README](../README.md)입니다. 이 문서는 교재 유지보수와 워크숍 개최 전 확인용입니다.

## 참가자 실행 블록 작성 원칙

각 실습 단계는 `👁️ **설명**` → `🟢 **실행**` → `📋 **확인**` 순서로 작성하고,
표시는 각각 독립된 줄에 놓은 뒤 빈 줄로 본문과 구분합니다. 설명에는 목적과 자원 관계를,
확인에는 실제 출력에서 비교할 이름·필드·상태를 적습니다. 출력 예시는 확인 항목 안에서
예시임을 명시하며 실제 실행 증거와 구분합니다. 개념 전용 절에는 인위적인 실행 단계를 만들지 않습니다.
비용·삭제·복구 주의사항은 `⚠️ **주의**`로 분리하며, 승인이나 삭제 전 알아야 할 내용은 명령 앞에 둡니다.
`<!-- exec:... -->`는 Bash fence 바로 앞에 유지하고 실행 표시는 그 주석보다 앞에 둡니다.
형식을 수정할 때 명령·실행 순서·스크린샷·안전 검사를 바꾸거나 개별 블록을 합치지 않습니다.

학습 대상인 VNet·Subnet·NSG·Peering·NAT 연결·UDR은 Hub·Spoke A·Spoke B별
Azure CLI 명령을 명시합니다. 참가자가 대상 RG, 주소 범위, 연결 방향을 비교할 수 있도록
`for`나 `zone_context`로 숨기지 않습니다. 한글 주석은 명령이 만드는 관계와 확인할 결과를 설명합니다.
의도적인 반복이므로 단순히 코드 길이를 줄이기 위해 다시 반복문으로 합치지 마세요.

모듈 02는 **생성 16개·조회 3개의 독립 코드 블록**으로 구성합니다.
모든 자원을 하나의 `( ... )` 또는 `{ ...; }`로 다시 묶지 않습니다.
모듈 02–07의 시작에서 **한 번만 source/ensure_state_file/load_run/assert_subscription**으로 준비합니다.
`ensure_state_file`은 경로가 비어 있을 때만 기존 JSON 경로를 묻고, 취소·빈 입력 시 이전 대상 변수를 지웁니다.
잘못된 경로/JSON은 `load_run`에서 실패하며, 구독 불일치는 자동 전환하지 않습니다.
모듈 05는 비용 안내를 배포 전 읽도록 유지하되 각 자원 생성마다 반복 입력을 요구하지 않습니다.
각 자원 작업은 준비된 같은 세션에서 필요한 조회/의존 상태 검사와 한 CLI 작업만 `&&`로 연결합니다.
재접속·상태 파일 변경·실습/구독 전환 시 준비를 다시 수행하도록 안내합니다.
직접 Azure 자원 명령은 `--subscription "$SUBSCRIPTION_ID"`로 대상을 고정합니다.
모듈 03–06은 공통 준비에서 세 RG의 소유권을 한 번 확인하고, 일반 작업의 중복 `assert`는 생략합니다.
모듈 02는 RG 생성 분기에서 기존 RG의 소유권을 확인합니다. 중간 재개 시에도 해당 RG 생성 단계를 다시 실행합니다.
Peering과 진단 설정의 ID, NSG/Firewall 규칙의 NIC IP는 명시적인 구독·RG·이름으로 조회하여 그대로 전달합니다.
일반 작업에 ID/IP 형식 검사를 다시 추가하지 않습니다. 조회 실패는 `&&`로 변경 명령에 전파합니다.
모듈 05의 진단 category·저장된 workspace/전용 테이블 확인과 모듈 06의 전환·삭제 안전 검사는 유지합니다.
모듈 04의 NAT는 같은 RG의 명시적인 이름으로 연결하며, 연결 결과는 JSON으로 보여 주고 참가자가 NAT·NSG·outbound 값을 비교합니다.
이 조회를 자동 PASS 판정으로 설명하지 않습니다. 비용 승인과 독립 통신 검증 스크립트는 유지합니다.
독립 실행 스크립트의 내부 구독·소유권 검사는 유지합니다.
`load_run`은 새 JSON을 읽기 전에 이전 실습의 구독·실행 ID·세 RG와 `zone_context` 파생 변수를 비웁니다.
상태 로딩 실패 후에도 참가자 셸은 유지하지만 이전 대상 변수를 재사용하지 않습니다.
복구 블록은 폴더 이동·source·입력부터 `&&`로 연결하고 업로드한 JSON의 경로도 허용합니다.
남겨 둔 안전 검사에서 Azure 리소스 ID는 **전체 문자열을 대소문자 구분 없이 비교**합니다. 구독·RG·종류·이름 중
어느 부분도 생략하거나 suffix만 비교하지 않습니다. 명령에는 조회한 원본 ID를 유지합니다.
[Workspace Get 공식 예시](https://learn.microsoft.com/en-us/rest/api/loganalytics/workspaces/get?view=rest-loganalytics-2025-07-01)처럼
`resourcegroups`와 provider namespace가 소문자로 반환될 수 있습니다.
`assert_resource_id`와 JSON ID 비교는 이 표기 차이만 허용하며, 실제 불일치는 오류로 표시합니다.
새 셸에서 **공통 준비 후 개별 작업만** 실행하는 mock 테스트로 앞 작업의 임시 변수에 의존하지 않는지,
검사 실패 시 자원을 변경하지 않고 참가자 셸도 종료하지 않는지 확인합니다.
생성 응답은 JSON으로 보여 주고 각 단계 바로 아래에 확인할 필드를 설명합니다.

AVNM manager/group/static member/connectivity configuration/commit/effective-configuration,
NAT 배포/개별 연결/조회, NSG 변경/검증, Firewall 자원/collection/진단,
UDR 테이블/각 route/연결/검증은 별도 블록입니다.
두 Spoke 테이블과 네 전달 Peering을 완성한 뒤 각 Subnet 연결 직전에 현재 준비 상태를 검사합니다.
NAT 제거는 Spoke별 **분리 → NAT 삭제 → Public IP 삭제** 여섯 작업이며 매 작업 안에
새 통신 검증·현재 소유/참조 확인·삭제 확인 입력이 있습니다. 마지막 제거 후 검증도 별도입니다.
`workshop-safety.sh`는 읽기 전용이며 성공 티켓/새 상태 스키마/숨겨진 변경 래퍼가 아닙니다.
확인 입력을 별도 선행 승인 블록으로 빼거나 오래된 성공 플래그로 대체하지 마세요.

보조 Bicep과 내부 검증·정리 스크립트의 반복 처리는 유지합니다.
구독·소유권 확인, 유료 배포/삭제 확인 문구, NAT 제거 전후 검증은 교재에서도 생략하지 않습니다.
명령을 펼친 뒤에는 CLI mock으로 대상과 인수·호출 순서를 확인하고 문서 Bash 구문을 검사합니다.
아래 실제 Azure 리허설은 이 편집 이전의 기록이며, 명시적 명령으로 편집한 교재의 재리허설을 뜻하지 않습니다.
원본 워크숍의 NAT 없는 Firewall 선행 순서는 이 변형에 이식하지 않았습니다. 원본의
`/0 → Firewall` 리허설에서 확인된 경로 선택은 모듈 06 설명에 반영하고,
관리 규칙 세부 검사는 Spoke NAT 제거 전 `firewall_ready_ip`에 반영했습니다.
이 변경의 검증은 로컬/mock이며 아래 AVNM 실전 리허설을 재실행한 것은 아닙니다.

## 단일 과정 구성

현재 참가자 경로는 **00 → 01 → 02 → 03 → 04 → 05 Firewall → 06 경로·로그 검증 → 07 정리**입니다.
기존 운영 기초·종료 선택 모듈은 내용 전체를 제거했으며 다른 모듈로 이관하지 않았습니다.
Firewall·왕복 UDR·Allow/Deny 로그·Spoke NAT 제거는 모두 정규 과정입니다.
README의 목표 시간 합계는 160–190분이며 배포·수집·삭제 대기 때문에 늘어날 수 있습니다.
중간 실패·중단 시의 cleanup 경로는 계속 제공하되 별도의 기본 과정 완료 분기로 안내하지 않습니다.

`verify-core.sh`는 모듈 04의 NSG·비전이성 검증, `verify-extension.sh`는 모듈 06의 Firewall 검증을 담당합니다.
`preflight.sh --extension`은 모듈 05의 기존 VM 재사용 점검 옵션입니다.
이 파일명과 옵션은 기존 호출 호환성을 위해 유지하며 선택 과정이라는 의미는 아닙니다.
`docs/superpowers/`의 설계·계획은 최초 제작 당시의 이력이며 현재 진행 순서의 기준은 README입니다.

## AVNM 변형 유지 계약

- 참가자 경로의 모듈 03은 `docs/03-avnm-connectivity.md` 하나로 고정합니다. 이전 수동-peering 모듈 파일은
  역사적 이력일 뿐 현재 경로에 다시 넣지 않습니다.
- 상태 파일은 `schemaVersion: 2`, `topology: "avnm-hub-spoke"`만 허용합니다. 다른 schema/topology는
  Azure API 호출 전에 거부해야 합니다.
- 참가자 문서에는 수동 VNet peering 생성 CLI가 남아 있으면 안 됩니다. 모듈 06의 `peering update`
  는 AVNM이 만든 기존 Peering의 `allowForwardedTraffic`만 바꾸는 용도로 유지합니다.
- 모듈 03의 완료 조건은 commit 성공 메시지가 아니라 **두 Spoke의 effective connectivity
  configuration**과 실제 Hub↔Spoke Peering 상태입니다. 별도로 지정한 Hub는 정적 Network
  Group 밖에 있어 effective 목록이 비어 있으며, 실제 CLI 응답에는
  `targetVirtualNetwork.id`가 없습니다. 로컬 VNet을 대상으로 조회하고 전체 remote VNet ID로
  양방향 Peering을 검사합니다.
- AVNM이 만든 Peering 이름은 안정적인 계약이 아닙니다. 테스트와 스크립트는 remote VNet의 **전체 resource ID**
  로 정확히 하나를 찾아야 하며, suffix 비교나 생성 규칙 추정에 의존하지 않습니다.
- 실행 경로는 Connectivity-only입니다. 참가자 문서와 예제에는 Security Admin configuration,
  AVNM Routing configuration, 동적 membership 실행, direct connectivity, global mesh, hub gateway,
  peering enforcement, peering deletion이 들어가면 안 됩니다.

## 스크립트 읽는 순서

`scripts/`의 한글 주석은 실행 위치, 검증 근거와 실패 시 중단 이유를 설명합니다.
함수 라이브러리는 `source`로 읽고, 실행 스크립트는 교재에 적힌 인수와 순서로 호출하세요.
특히 `guest-server.sh`는 Cloud Shell이 아니라 **Run Command로 Spoke VM 안에서 실행**합니다.

| 파일 | 읽을 때 확인할 내용 |
|---|---|
| `workshop-common.sh` | 상태 JSON 생성·복구, schema 2/topology 검증, 구독·RG 소유 확인, AVNM 이름 파생 |
| `workshop-safety.sh` | 전체 ID 대소문자 비교, generated Peering의 remote-ID 조회, Firewall/진단/Allow 준비, 양쪽 경로·Peering, 단계별 NAT 소유/참조의 읽기 전용 검사 |
| `preflight.sh` | 읽기 전용 사전 점검, 기존 VM 재사용, SKU 제한과 quota 판정 |
| `run-vm.sh` | Bash 실행 지정, stdout/stderr 분리, 게스트 종료 마커 검증 |
| `guest-server.sh` | 비특권 HTTP 서비스 설치와 VM 내부 준비 상태 확인 |
| `verify-common.sh`, `assert-route.py` | IP·NSG·HTTP 증거와 최장 접두사 유효 경로 판정 |
| `verify-core.sh`, `verify-extension.sh` | 기본·확장 단계의 여러 증거를 함께 비교하는 순서 |
| `firewall-logs.sh` | 이번 흐름의 로그 필터, 수집 지연 대기와 조회 오류 구분 |
| `cleanup.sh` | 정확한 삭제 범위, 사용자 확인, 삭제 요청 후 실제 부재 확인 |

## Bicep 읽는 순서

한글 주석은 구독/RG 배포 범위, 모듈의 의존 관계, 공개 키와 사설 NIC,
VM 보안 설정 및 NAT 연결이 별도 단계인 이유를 설명합니다.
리소스 설정과 Checkov 예외 식별자는 설명 주석과 구분해서 읽으세요.

| 파일 | 읽을 때 확인할 내용 |
|---|---|
| `infra/lab-support.bicep` | 기존 세 RG에 보조 모듈 배포, 구독을 명시한 Subnet ID, 구역별 출력 |
| `infra/modules/nat.bicep` | NAT 출구용 고정 Public IP, 참조로 생기는 의존 관계, CLI에서 별도로 수행하는 Subnet 연결 |
| `infra/modules/test-vm.bicep` | 공인 IP 없는 NIC, SSH 공개 키/VM agent, Trusted Launch, VM 삭제 시 디스크·NIC 수명 |

이 템플릿은 네트워크 뼈대를 다시 만들지 않습니다. VNet·NSG·Subnet 생성과
NAT·Peering·UDR 연결은 교재의 개별 Azure CLI 작업으로 유지합니다.

## 로컬 검사

필요 도구는 Bash, Python 3.10+, jq, Azure CLI와 Bicep CLI, Checkov입니다.
외부 Python 테스트 패키지는 필요하지 않습니다.

```bash
bash tests/validate.sh
```

이 명령은 실제 Azure 배포를 하지 않습니다. CLI mock은 예상하지 않은 호출을 거부하며
실제 `az`로 fallback하지 않습니다. Bicep 검사는 로컬 ARM 템플릿 컴파일입니다.
문서의 Bash 구문과 상대 링크도 검사합니다. cloud 테스트와 혼동하지 마세요.
참가자용 한글 주석은 독립된 줄에 유지하세요. `\`로 이어지는 명령 중간에 주석을 넣으면
명령 인수가 끊길 수 있습니다. 설명 수정 후에도 문서 검사를 실행하고,
주석의 예상 결과를 실제 검증 스크립트가 확인하는 범위와 맞춥니다.
게스트 실행 테스트는 Action Run Command처럼 실행 가능한 파일을 `/bin/sh -c`로
호출하여 첫 줄 shebang에 따른 Bash 선택과 게스트 종료 마커를 확인합니다.
CLI 대체 응답은 [Azure CLI의 Linux 실행 기록](https://github.com/Azure/azure-cli/blob/dev/src/azure-cli/azure/cli/command_modules/vm/tests/latest/recordings/test_vm_run_command_with_parameters.yaml)처럼
`ProvisioningState/succeeded` 메시지에 `[stdout]`과 `[stderr]`를 함께 담습니다.
분리된 `ComponentStatus` 응답도 지원하지만, API 성공만으로 게스트 성공을 간주하지 않습니다.
실패한 게스트·누락된 종료 마커·stderr의 가짜 성공 마커·잘못된 응답 형식을 회귀 검사합니다.
난수 ID와 기존 RG 충돌 거부, 기존 VM 재사용 시 quota 계산, Network Watcher
신규 활성화와 공유 RG 보존도 로컬 회귀 검사에 포함됩니다.
모듈 02–07의 개별 블록은 공통 준비 뒤 독립 실행하며, 실패한 조회/잘못된 응답,
소유권 불일치, 승인 거절, 전환 준비 누락, NAT 삭제 순서/범위를 검사합니다.
`tests/test_docs.py`는 README와 활성 참가자 모듈에서 이전 수동-peering 링크와
수동 peering 생성 CLI가 남지 않았는지, AVNM 범위가 Connectivity-only인지 확인합니다.
모듈 03 mock은 AVNM manager/group/static member/connectivity configuration/commit/effective-configuration
블록의 호출 순서와 인수를 확인합니다.
상태·복구 테스트는 schema 2/topology 거부, generated-name 불안정성에 영향받지 않는
full-ID 비교, 독립 저장소 경로 `$HOME/ms-landing-zone-02` 복구 동작을 회귀 검사합니다.
`bash tests/validate.sh`의 최종 요약은 `PASS: local validation only; no Azure resources were deployed.`여야 합니다.
소문자·혼합 대소문자 ID와 workspace 참조는 허용하되, 다른 구독·RG·종류·이름 및 추가 경로는 거부하는 회귀 검사도 포함합니다.
검증/정리 스크립트 호출은 문서 테스트에서 인수와 실패 전파를 확인하고 기존 스크립트 테스트를 함께 실행합니다.
복구 회귀 검사는 이미 준비된 셸에서 잘못된 상태를 읽은 뒤 대상 변수가 남지 않는지 직접 확인합니다.
교재의 실제 복구 블록을 실행하여 디렉터리 이동 실패·입력 EOF·JSON 오류 시 구독 변경이 없는지,
상태 디렉터리 밖에 업로드한 JSON으로도 복구할 수 있는지 검사합니다.
이후 문서 개정은 **로컬/mock만** 검증합니다. 아래 2026-09-24 Azure 리허설을
새로 변경한 설명이나 브라우저 Cloud Shell 조작의 재실행 결과로 해석하지 않습니다.

도구가 없으면 먼저 누락 오류를 확인한 뒤 조직이 승인한 방법으로 설치하세요.
예를 들어 별도 환경에서 `uv tool install checkov`를 사용하고 해당 executable을 PATH에 둡니다.
시스템 Python의 패키지를 임의로 바꾸거나 설치 실패를 검사 성공으로 처리하지 않습니다.

작성 시 사용한 Bicep CLI는 `0.45.15`, Firewall extension은 `2.2.1`입니다.
2026-09-21 실제 사전 점검에서 실습 구독의 Korea Central에 `Standard_B2s`가
`NotAvailableForSubscription`으로 제한되어, 사용자 승인 후 같은 2 vCPU/4 GiB의
`Standard_B2als_v2`로 교재와 템플릿을 변경했습니다. SKU 허용과 quota는 구독별로 다시 확인합니다.
Azure CLI/Checkov 버전은 검사 시 `az version`, `checkov --version`으로 기록합니다.
Task 6의 로컬 검증에서는 누락된 Checkov를 승인된 방법인 `uv tool install checkov`로 설치했고,
재실행에 사용한 버전은 `checkov 3.3.19`였습니다.
Cloud Shell에서 실제 같은 명령을 재현해야 하며, CLI 도움말 확인만으로 API 실행을 검증했다고 하지 않습니다.

## 보안 검사 예외

`infra/modules/test-vm.bicep`의 VM 한 개 정의에만 다음 세 Checkov 예외가 있습니다.
전체 규칙을 끄거나 다른 리소스에 일반화하지 않습니다.

| Check | 교육용 예외 이유 | 운영 전환 |
|---|---|---|
| CKV_AZURE_50 | Run Command는 VM agent/extension이 필요하며 public SSH 대신 사용 | RBAC 최소화, extension 허용 정책, 관리 경로 분리 |
| CKV_AZURE_97 | disposable 비민감 VM의 관리형 디스크 SSE 사용; host encryption 기능 등록을 입문 전제로 추가하지 않음 | 지원 SKU·구독 기능 확인 후 host encryption |
| CKV_AZURE_151 | Linux VM은 플랫폼 관리형 디스크 암호화를 사용하며 guest Azure Disk Encryption은 미구성 | 요구사항에 맞는 암호화·키 관리 선정 |

이는 모든 보안 기준 준수 선언이 아닙니다. 공인 NIC 없음, SSH 암호 인증 비활성화,
Trusted Launch·Secure Boot·vTPM, 비특권 응답 서비스는 적용합니다.
관리형 디스크 SSE는 host cache/temporary disk 암호화와 같지 않습니다.
실습에는 고객 데이터·자격 증명·업무 워크로드를 올리지 않습니다.

## 실제 Azure 리허설

### 2026-09-21 수동 Peering 원본 워크숍 이력

**2026-09-21 실제 Azure 리허설 수행.** 사용자 비용 승인 후 Korea Central의 새 실습 RG 세 개에서
당시 **수동 Peering 기반 원본 워크숍**과 Firewall 확장을 실행했습니다. 현재의 AVNM 변형에 대한
실행 증거가 아니라 source workshop의 역사적 참고 기록입니다. 실행 환경은
**Linux Bash / Azure CLI 2.90.0 / Bicep 0.45.15 / Firewall extension 2.2.1 / log-analytics 1.0.0b2**입니다.
브라우저 Cloud Shell/Portal에서 직접 조작한 결과는 아닙니다.
아래 체크는 당시 실행에서 확보한 증거의 범위이며, AVNM 변형의 배포 성공을 보장하지 않습니다.

- [x] 테스트 구독, 비용 승인, 실제 생성·변경 권한, provider 등록, VM SKU/이미지/6 vCPU 및 지역 용량 확인
- [ ] Cloud Shell의 Azure CLI·Bicep·extension 버전 기록
- [x] 모듈 02–03 CLI 진행, 수동 네 방향 Peering, Subnet outbound/NSG 상태 확인
- [x] 수정한 Bicep what-if에서 VM이 포함되고 기존 VNet/Subnet 삭제·덮어쓰기 없음 확인
- [x] VM 3대와 NAT 3개, VM NIC Public IP 없음 확인
- [x] Run Command가 세 VM에서 응답하며 두 guest service가 로컬 정상 응답
- [x] Hub→두 Spoke의 정상 HTTP, NSG 차단/복구, A→B 비전이성을 경로·NSG 증거와 대조
- [ ] Cloud Shell을 새로 열고 원래 상태 JSON으로 재개
- [ ] Firewall 생성 전 중단 시 cleanup 완료, watcher와 Cloud Shell 저장소 보존 확인
- [ ] 별도 새 ID로 중간 배포 실패/중단 상황의 cleanup 확인
- [x] 동일 실행 ID에서 NSG 검증에 이어 Firewall 구성, 진단 설정 후 왕복 UDR 적용
- [x] A→B Allow/Deny/복구를 실제 이번 흐름 로그로 확인(Deny 로그 조회 재시도 포함)
- [x] 두 Spoke egress IP와 유효 next hop이 Firewall에 일치
- [x] Spoke NAT 제거 전후 관리 기능과 HTTP·로그·egress 검증
- [x] 전체 cleanup과 세 RG 실제 삭제 확인, 기존 Korea Central Network Watcher 보존 확인
- [ ] 각 모듈 실제 소요 시간, 배포 대기, 로그 지연, 비용 요인을 기록하고 시간표 조정

### 이번 리허설에서 발견하고 수정한 항목

| 항목 | 실제 관측과 조치 |
|---|---|
| VM SKU 제한 | 기존 B2s가 구독·리전에서 제한됨. 사용자 승인 후 같은 2 vCPU/4 GiB의 B2als_v2로 변경 |
| quota 응답 타입 | CLI가 `currentValue`·`limit`을 문자열로 반환함. 숫자와 숫자 문자열의 비음수 정수만 허용하도록 수정 |
| 구독 범위 Subnet ID | `resourceId`가 RG 이름을 구독 ID로 해석해 VM 배포 실패. 구독 ID를 명시하고 what-if·배포를 재실행해 성공 |
| Run Command 실제 응답 | 앞서 수정한 Bash shebang과 stdout/stderr 파서가 세 실제 VM에서 정상 동작함 |
| 로그 조회 DNS 오류 | 실행 호스트가 일시적으로 `api.loganalytics.io`를 해석하지 못해 Deny 검증이 중단됨. 오류를 숨기지 않고 같은 흐름의 로그를 재조회해 Deny 증거 확보; Allow 복구 검증도 통과 |

원본 실패 기록은 성공으로 바꾸지 않고 보존합니다. 매 실행 블록은 새 Bash 프로세스에서
원래 상태 JSON을 읽었으나, 이는 브라우저 Cloud Shell 재접속 시험을 대신하지 않습니다.

| 실행 구간 | 이번 관측 시간 |
|---|---:|
| 네트워크 생성 / 수동 Peering | 약 95초 / 39초 |
| 수정 후 VM·NAT 배포 및 연결 / 두 서비스 준비 | 약 113초 / 69초 |
| 기본 통신 / NSG 차단 / 복구 검증 | 약 190초 / 191초 / 148초 |
| Firewall 생성 / 규칙 생성 / 진단 설정 | 약 531초 / 507초 / 9초 |
| 왕복 UDR 적용과 Allow 검증 | 약 393초 |
| Deny 단계(조회 오류로 중단) / Allow 복구 검증 | 약 340초 / 561초 |
| NAT 제거 전·후 검증을 포함한 제거 블록 | 약 617초 |
| 최종 세 RG 삭제 완료 대기 | 약 872초(14분 32초) |

여러 로그 조회에서 30초 간격으로 4–8회 기다렸습니다. 위 값은 명령 실행의 한 사례이며
설명·참가자 입력·문제 해결 시간을 포함한 수업 시간표의 검증은 아닙니다.
Firewall 생성 전 중단 상황의 별도 배포·cleanup, 새 ID의 중도 실패 cleanup, 브라우저 실습은 남은 항목입니다.
이번 실행의 세 RG는 모두 삭제 완료했으며 기존 공유 Network Watcher는 `Succeeded`로 유지됩니다.
실행 기록은 로컬 `evidence/rehearsal-18560e683452/`에 보관했습니다(Git 제외).

### AVNM 변형 리허설 체크리스트

아래 항목은 **현재 AVNM 교재**의 실제 관측값입니다. 로컬 터미널의 인증된
Azure CLI로 진행했으며 브라우저 Cloud Shell 재접속은 시험하지 않았습니다.

- [ ] Cloud Shell의 Azure CLI·Bicep·`virtual-network-manager` extension·Checkov 버전을 기록했다.
- [x] 모듈 03에서 AVNM, Network Group, 정적 Spoke A/B membership, Connectivity Configuration을 만들었다.
- [x] `koreacentral` commit 뒤 두 Spoke의 effective connectivity configuration이 기대한 ID를 가리키고 Hub의 목록이 비어 있었다.
- [x] Hub에는 Connected Peering 2개, 각 Spoke에는 Connected Peering 1개가 생겼고 Spoke A↔B 직접 Peering은 없었다.
- [x] 모듈 04에서 Hub→Spoke 정상 HTTP, NSG 차단/복구, Spoke A→B 실패를 다시 확인했다.
- [x] 모듈 05–06에서 Firewall, 진단, `allowForwardedTraffic`, 왕복 UDR, Allow/Deny 로그, egress, Spoke NAT 제거를 확인했다.
- [x] generated Peering 이름을 가정하지 않고 remote VNet full ID 기준으로 검증했다.
- [x] cleanup으로 정확한 세 RG만 삭제하고 공유 Network Watcher 보존을 확인했다.

### 2026-09-23 AVNM 실제 리허설 시도 — 실행 생성 전 차단

2026-09-23 18:30–18:35 KST에 Korea Central 새 실행을 시작하기 전 도구와 구독 접근을 확인했습니다.
선택된 구독은 `ME-MngEnvMCAP974883-jungwoonlee-1`
(`e9c89382-b9fd-4856-8ae4-647988d62a44`)이었습니다.

- Azure CLI `2.90.0`, Bicep `0.45.15`, Firewall extension `2.2.1`,
  log-analytics extension `1.0.0b2`, Checkov `3.3.19`를 기록했습니다.
- `virtual-network-manager` extension은 설치되어 있지 않아 버전을 기록하지 못했습니다.
- Azure MCP 구독 조회는 자격 증명 획득 실패와 `login.microsoftonline.com` 네트워크 접근 불가로 실패했습니다.
  Azure CLI의 읽기 전용 `az group list` 접근 확인도 응답을 반환하지 않아 5분 후 중단했습니다.
- 따라서 인증·네트워크와 필수 CLI capability가 준비되지 않은 blocker로 판단해 `new_run`을 호출하지 않았습니다.
  `RUN_ID`, 상태 파일, 소유 RG 이름은 생성되지 않았고 Azure 자원 생성·변경도 시도하지 않았습니다.
- 모듈 01–06과 실제 검증은 실행하지 않았으므로 위 AVNM 체크리스트는 모두 미완료로 유지합니다.
- 실행과 소유 RG가 없으므로 `scripts/cleanup.sh`를 호출할 상태 파일이 없었습니다.
  세 RG의 `false` 조회 증거도 만들 수 없어 이번 시도는 완료가 아니라 **blocked**입니다.
- 비밀이 없는 환경 및 blocker 증거는
  `evidence/rehearsal-blocked-20260923T182607+0900/`에 보관했습니다(Git 제외).

### 2026-09-23 AVNM 리허설 재시도 — 인증 경로 여전히 차단

18:52 KST에 같은 구독의 읽기 전용 접근을 다시 확인했습니다. `az account show`는 저장된
계정 정보만 반환했으므로 실제 접근 증거로 사용하지 않았습니다. Azure MCP의 RG 조회는
자격 증명 획득 실패(401), Azure CLI의 `az group list`는
`login.microsoftonline.com` 연결 시 `No route to host`로 실패했고, 별도 HTTPS
접속도 시간 초과되었습니다. `virtual-network-manager` extension도 설치되지 않았습니다.
따라서 새 run/state/RG를 생성하지 않았고, 실제 배포·검증·cleanup 및 세 RG 부재
증명은 여전히 미완료입니다. 기존 AVNM 체크리스트는 완료로 표시하지 않습니다.

재시도 중 `bash tests/validate.sh`는 137개 테스트와 Checkov 7 passed /
0 failed / 3 skipped로 통과했습니다. 현재 참가자 경로와 스크립트에는 수동
`az network vnet peering create` 또는 제외된 AVNM 설정 명령이 없으며,
이 결과는 Azure 리허설을 대신하지 않습니다.

### 2026-09-23 실제 AVNM Azure 리허설 — 로컬 CLI 실행

19:08 KST에 인증 경로가 복구되어 읽기 전용 `az group list`가 성공했습니다.
`virtual-network-manager` extension `3.0.2`를 설치한 뒤 Korea Central에서
`f0ccc3b0d3c8` 실행을 시작했습니다. 처음에는 정적 멤버 생성 직후 목록의 전파가
지연되어 Connectivity Configuration의 사전 검사가 실패했습니다. 재조회 후
configuration 생성과 commit은 성공했고 deployment status는 `Deployed`였습니다.
별도 Hub의 effective 목록은 빈 배열, 두 Spoke는 올바른 configuration ID였습니다.
실제 응답에는 `targetVirtualNetwork.id`가 없어서 20:00 KST에 사용자가 승인한
검증 기준(두 Spoke effective + 양방향 전체 ID Peering)으로 교재·검증기를 바로잡았습니다.
이 첫 실행은 모듈 04로 넘어가지 않고 `cleanup.sh`로 삭제했으며 세 RG 모두 `false`를
조회했습니다. 증거: `evidence/rehearsal-f0ccc3b0d3c8/` (Git 제외).

새 `0c392ad416c9` 실행에서 모듈 01의 preflight와 모듈 02–06의 참가자 블록을 순서대로
실행했습니다. 첫 정적 멤버 목록 조회는 역시 전파 전 상태여서 같은 블록을 재실행했고,
commit 직후 Spoke A effective 검사는 약 15초 후 통과했습니다. 문서의 전파 대기 검사를
보강했으며, 조회 API 오류·예상 밖 멤버 ID는 성공으로 취급하지 않습니다.
모듈 04에서 baseline/NSG deny/restore 검증 3회, 모듈 06에서 Firewall
Allow/Deny/restore 및 NAT 제거 후 검증이 모두 `PASS`였습니다.
AVNM 생성 Peering은 Hub 2개·각 Spoke 1개이며 별도 Spoke 간 Peering은 없었습니다.
Firewall Allow/Deny 로그는 해당 시점의 요청 후 조회했고 인터넷 `/0` 경로와 출구 IP는
Firewall로 확인했습니다.

| 실제 관측 구간 | 소요 |
|---|---:|
| 지원 VM/NAT 배포 | 약 71초 |
| Firewall IP 구성 | 약 475초 |
| Firewall Allow 로그 수집까지 검증 | 약 423초 |
| Firewall Deny 로그 수집까지 검증 | 약 300초 |
| Firewall Allow 복구 로그 수집까지 검증 | 약 314초 |
| NAT 제거 후 최종 검증 | 약 288초 |
| 세 RG 삭제 및 부재 조회 | 약 16분 38초 |

Azure CLI `2.90.0`, Bicep `0.45.15`, AVNM extension `3.0.2`, Firewall extension
`2.2.1`, log-analytics extension `1.0.0b2`, Checkov `3.3.19`를 로컬에서 사용했습니다.
지역 용량·Policy·provider 등록 오류는 없었고, 위의 초기 전파 지연은 명시적으로
처리했습니다. `cleanup.sh` 완료 후 정확한 세 RG를 별도 조회해 `false` 세 개를
기록했고 기존 Korea Central Network Watcher는 `Succeeded`로 남았습니다.
증거: `evidence/rehearsal-0c392ad416c9/` (Git 제외). 브라우저 Cloud Shell에서
동일 명령을 실행하거나 세션 재연결을 시험했다는 의미는 아닙니다.
로컬 최종 검사는 139 tests, Checkov 7 passed / 0 failed / 3 skipped입니다.

### 2026-09-24 게시 버전 실제 AVNM Azure 재리허설

게시 저장소 `main`의 `b8c7893`에서 Korea Central의 새 실행 `8c43433227ef`을
인증된 로컬 Azure CLI로 실행했습니다. 시작 전 별도 실행 `98f2d58f5774`의 세 RG가
존재하는 것을 확인했으며, 그 실행의 자원은 변경하거나 삭제하지 않았습니다.
모듈 01의 읽기 전용 preflight와 모듈 02–06의 참가자 실행 블록을 순서대로 실행했습니다.
AVNM의 Hub effective 목록은 비어 있고 두 Spoke에는 승인된 구성 하나씩, Hub에는
Connected Peering 두 개와 두 Spoke에는 각각 Hub를 향한 Connected Peering 하나씩
있었습니다. Commit 직후 Spoke A의 첫 effective 조회는 아직 반영 전이라 실패했고,
20초 후 **같은 읽기 전용 블록 재조회**에서 통과했습니다. 실패를 성공으로 취급하거나
commit을 다시 수행하지 않았습니다.

모듈 04의 baseline·NSG 차단·복구, 모듈 06의 Firewall Allow·Deny·복구 로그,
양쪽 `/16` 왕복 경로와 `/0` 출구, 여섯 단계의 Spoke NAT 분리·삭제 및 제거 후
최종 검증이 모두 `PASS`였습니다. 변경된 `firewall_ready_ip`의 관리 규칙 상세 검사는
Subnet에 UDR을 연결하기 전에 실제 Policy 응답을 대상으로 통과했습니다.

| 실제 관측 구간 | 소요 |
|---|---:|
| 지원 VM/NAT 배포 | 약 68초 |
| Firewall IP 구성 | 약 7분 51초 |
| 첫 Firewall Allow 검증·로그 | 약 7분 6초 |
| Firewall Deny 검증·로그 | 약 5분 9초 |
| Firewall Allow 복구 검증·로그 | 약 5분 1초 |
| Spoke NAT 제거 후 최종 검증 | 약 5분 |
| `cleanup.sh`와 세 RG 부재 재조회 | 약 14분 21초 |

Azure CLI `2.90.0`, Bicep `0.45.15`, AVNM extension `3.0.2`, Firewall extension
`2.2.1`, log-analytics extension `1.0.0b2`, Checkov `3.3.19`를 사용했습니다.
`cleanup.sh`가 성공한 뒤 새 실행의 Hub·Spoke A·Spoke B RG를 독립적으로 조회해
각각 `false`를 확인했습니다. 기존 `NetworkWatcher_koreacentral`은
`Succeeded`이고 다른 실행의 세 RG도 남아 있었습니다.
증거: 로컬 `evidence/rehearsal-8c43433227ef/` (Git 제외).
이 리허설은 브라우저 Cloud Shell 재접속이나 다른 구독·지역에서의 동작 검증이 아닙니다.
기록 추가 후 로컬 최종 검사는 141 tests, Checkov 7 passed / 0 failed / 3 skipped입니다.
2026-09-25 원본 워크숍의 세션 복구 설명, Hub Subnet Portal 예시, Firewall IP 연결
대기 안내를 AVNM 과정에 맞춰 이관했습니다. 수동 Peering 생성 예시와 원본의
Spoke NAT 없는 Firewall 선행 흐름은 이관하지 않았습니다. 이 문서 변경 후 Azure
리허설을 다시 수행하지 않았으며, 위 결과는 변경 전 게시본의 검증 증거입니다.

증거는 `evidence/`에 보관하되 access token, 개인 키, 비밀번호, 로그의 민감 데이터는
넣지 않습니다. 이 폴더는 Git에서 제외됩니다. 사용자 구독 ID가 포함된 캡처를 공개하기
전에는 해당 조직의 공유 정책을 따릅니다.

## 설계와 구현의 작은 차이

검증기 사이의 IP·HTTP·NSG·경로 확인을 중복하지 않기 위해
`scripts/verify-common.sh`와 `scripts/assert-route.py`를 추가했습니다.
경로 판정은 문자열 포함 검사가 아니라 **active route의 longest-prefix match**를 계산합니다.
보조 템플릿은 Subnet을 소유하지 않으며, NAT 연결은 CLI로 기존 Subnet의 해당 속성만 변경합니다.
Firewall 차단 실습은 관리용 collection을 건드리지 않고 `lab-http`를 명시적 Deny로 전환합니다.
이는 단순 네트워크 장애와 정책 차단을 구분하는 로그를 확보하기 위한 것입니다.

검사기는 세션의 성공 결과를 상태 JSON에 저장하지 않습니다. 다음 단계마다 실제 Azure
상태와 해당 시점의 증거를 다시 확인합니다.
