# 07. 정리와 운영 환경으로의 확장

> 워크숍 완료 또는 중도 중단 시 반드시 실행합니다. 목표 시간 10–15분이며,
> 실제 리소스 삭제는 그보다 오래 걸릴 수 있습니다.

## 목표

정상 완료와 중간 실패 모두에서 AVNM의 세 종류 구성을 먼저 해제한 뒤
**이번 실행의 정확한 세 RG만** 삭제합니다. 관리형 경로 테이블의 연결이나
잔존 테이블이 발견되면 중단하고 상태를 확인합니다. 공유 자원과 다른 참가자의
리소스는 보존합니다.

## 공통 준비

👁️ **설명**

모듈 01의 `STATE_FILE`을 사용합니다. 재접속 후 활성 구독이 원래 구독과 같다면
이 공통 준비를 실행하고, `STATE_FILE`이 비어 있을 때 기존
파일명을 `ls .workshop-state/`로 확인한 뒤
`예:`의 실제 경로를 참고해 `.workshop-state/<실행 ID>.json` 경로를 입력하세요.
파일이 여러 개라면 삭제할 실습의 파일을 직접 선택하세요.
파일을 잃었다면 아래 [상태 파일 복구](#상태파일을잃은경우)를 먼저 수행합니다.
기존 schema 2 파일이면 이 버전의 cleanup을 실행하지 말고
[기존 실행 복구](#기존-schema-2-실행-복구)를 따르세요.
활성 구독이 다르거나 다른 실습/구독으로 전환했다면
[모듈 01의 세션 복구](01-prerequisites.md#세션-재연결-시-변수-복구)를 먼저 실행한 뒤 공통 준비로 돌아오세요.
같은 세션에서 한 번만 준비하며, 경로가 이미 설정돼 있으면 다시 묻지 않습니다.
실패하면 삭제로 넘어가지 않습니다.

🟢 **실행**

<!-- exec:prepare-07 -->
```bash
source scripts/workshop-common.sh &&
ensure_state_file &&
load_run "$STATE_FILE" &&
assert_subscription
```

📋 **확인**

오류 없이 프롬프트로 돌아옵니다. 아직 삭제하지 않았습니다.

## 1. 삭제 대상 확인과 실행

👁️ **설명**

리소스 이름뿐 아니라 활성 구독과 네 개의 소유 태그를 검사합니다.
`IPAM_POOL_ID`는 삭제 대상을 만드는 데 사용하지 않습니다. schema 3의
`resourceGroups.hub/spokea/spokeb` 세 이름만 검사하고, 이미 없는 RG는 건너뜁니다.
모듈 02가 일부만 성공해 VNet이나 Subnet의 CIDR이 모두 배정되지 않아도
`load_ipam_cidrs` 없이 정리할 수 있습니다. **존재하는 RG의 구독·소유 태그는
부분 실행에서도 생략하지 않습니다.**
AVNM의 Routing·Security Admin·Connectivity 목표 상태를 리전에서 `None`으로 전환한
뒤 각 배포 완료와 Subnet의 관리형 경로 테이블 연결 해제·잔존 테이블 제거를
최대 10분씩 기다립니다. 남아 있으면
Azure Portal에서 배포 상태와 테이블을 확인한 뒤 다시 실행하세요. **관리형 RG를
수동으로 일괄 삭제하지 마세요.** 삭제 요청 접수는 완료가 아닙니다. 스크립트는
최대 45분 동안 잔존 여부를 확인합니다.
모듈 04의 피어링 강제가 활성화된 상태에서 피어링을 수동으로 삭제하지 마세요.
Connectivity 배포를 먼저 해제하는 아래 스크립트의 순서를 따릅니다.
**정리라는 한 목적의 안전 스크립트**는 그대로 사용합니다. RG별 raw delete로 쪼개면
전체 대상의 사전 검사·정확한 확인 문구·삭제 완료 대기가 빠질 수 있습니다.
스크립트 자체의 구독/소유권 재검사는 독립 실행 시에도 안전하게 하려는 내부 보호입니다.

⚠️ **주의**

이 작업은 해당 RG 안의 VM·디스크·Hub NAT·Public IP·Firewall·로그까지
삭제합니다. 필요한 학습 증거는 비밀을 제외하고 먼저 내려받으세요.
VM 정지/deallocate만으로 NAT, 디스크, Public IP, Firewall 비용은 없어지지 않습니다.

🟢 **실행**

<!-- exec:cleanup -->
```bash
# 현재 상태 파일의 구독·세 RG·소유 태그를 확인하고 정확한 삭제 확인 문구를 요청합니다.
# 확인 전 출력된 대상이 모두 내 실습인지 읽으세요. 이 명령은 RG 안의 로그와 디스크도 삭제합니다.
bash scripts/cleanup.sh "$STATE_FILE"
```

📋 **확인**

아래는 대상 확인 화면의 **출력 예시**입니다. 실제 화면의 구독 UUID와 실행 ID를 확인하세요.

```text
Subscription: <실제 구독 UUID>
Delete ONLY:
  rg-lzbegin-hub-<실행ID>
  rg-lzbegin-spokea-<실행ID>
  rg-lzbegin-spokeb-<실행ID>
Type exactly: DELETE <실행ID> FROM <실제 구독 UUID>
```

대상이 맞을 때만 출력된 문구를 그대로 입력합니다. 하나라도 다르면 입력하지 마세요.
이미 없는 RG는 `Already absent`로 표시합니다. 조회 실패를 “없는 자원”으로 처리하지 않습니다.

## 2. 삭제 완료 확인

👁️ **설명**

삭제 요청이 접수된 것과 자원이 사라진 것은 다릅니다. 스크립트의 완료 결과와 Portal의 잔존 여부를 대조합니다.

🟢 **실행**

**Portal → Resource groups**에서 정확한 세 이름을 검색해 사라졌는지 확인합니다.

📋 **확인**

`PASS: workshop group deletion complete...` 또는 세 RG가 이미 없다는 메시지가 나와야 합니다.
Portal에서도 이번 실습의 세 RG가 없어야 합니다.
구독의 배포 이력 `support-실행ID`가 남더라도 이는 실행 중인 VM/NAT가 아닙니다.
Cloud Shell 저장소, 공유 Network Watcher와 운영자 소유 공유 IPAM RG
`rg-lzbegin-ipam`은 삭제 대상이 아닙니다. 공유 pool 삭제는 운영자 별도 작업입니다.
Portal에서 공유 RG와 `avnm-lzbegin-ipam/ipam-lzbegin-shared`가 그대로
존재하는지 확인하되, 참가자는 이 자원에 대한 delete 명령을 실행하지 않습니다.
삭제 실패나 시간 초과 후에는 **같은 상태 파일**로 남은 RG를 조회하고 cleanup을 다시 실행할
수 있습니다. 이미 없는 그룹은 건너뛰지만, 조회 권한 오류나 소유 정보 불일치는 중단합니다.
RG 삭제 완료 뒤에도 비용 화면에는 과거 사용량이 지연 반영될 수 있습니다.

<a id="상태파일을잃은경우"></a>
## 상태 파일을 잃은 경우

⚠️ **주의**

새 ID를 만들지 말고 Portal에서 **원래 실행 ID와 구독**을 확인하세요.
다른 파일을 지우거나 비슷한 RG를 wildcard로 삭제하지 않습니다.
**schema 2 실행**이었다면 아래 `create_run`으로 schema 3 JSON을 만들지 말고
[고정 버전 절차](#기존-schema-2-실행-복구)를 따릅니다. 실행 시점이나 원본
교재 버전을 확인할 수 없다면 운영자에게 확인받기 전까지 삭제하지 않습니다.

### 복구 1. 원래 식별 정보 입력

👁️ **설명**

이 예외 경로는 기존 상태 파일이 없을 때만 사용합니다. 아직 공통 준비를 할 수 없으므로
함수를 읽고 Portal에서 확인한 정보를 입력합니다.

🟢 **실행**

<!-- exec:recovery-input -->
```bash
source scripts/workshop-common.sh &&
read -rp "원래 실행 ID: " ORIGINAL_RUN_ID &&
read -rp "원래 subscription ID: " ORIGINAL_SUBSCRIPTION &&
read -rp "원래 리전 (예: koreacentral): " ORIGINAL_LOCATION
```

📋 **확인**

세 입력값이 원래 실습과 일치해야 합니다. 다른 참가자의 ID를 추측하지 않습니다.

### 복구 2. 원래 구독 선택

👁️ **설명**

Portal에서 확인한 원래 실습 구독으로 CLI 대상을 맞춥니다.
다른 구독에서 같은 이름의 자원을 찾거나 새 실습을 만드는 단계가 아닙니다.

🟢 **실행**

<!-- exec:recovery-subscription -->
```bash
az account set --subscription "$ORIGINAL_SUBSCRIPTION"
```

📋 **확인**

오류 없이 끝났는지 확인합니다. 실패하면 상태 파일 생성으로 넘어가지 않습니다.

### 복구 3. 로컬 상태 파일만 재생성

👁️ **설명**

원래 실행 ID·구독·리전으로 로컬 복구 JSON만 다시 만듭니다.
실제 Azure 자원의 소유권은 이후 cleanup에서 별도로 대조합니다.

🟢 **실행**

<!-- exec:recovery-state -->
```bash
create_run "$ORIGINAL_RUN_ID" "$ORIGINAL_SUBSCRIPTION" "$ORIGINAL_LOCATION" &&
export STATE_FILE=".workshop-state/$ORIGINAL_RUN_ID.json"
```

📋 **확인**

원래 ID의 JSON 경로가 출력됩니다. Azure 자원은 생성하지 않습니다.
이제 위 **공통 준비 → 삭제 대상 확인과 실행**으로 돌아갑니다. 복구 성공만으로 자동 삭제하지 않습니다.

기존 파일이 있으면 `create_run`은 덮어쓰지 않습니다. 그 파일부터 복구하세요.
여기서는 원래 ID로 로컬 JSON만 복구하는 `create_run`을 사용합니다.
이 절차는 **schema 3으로 처음 시작한 실행에만** 해당합니다. 정확한 원래 구독·
ID·Korea Central 및 원래 공유 pool ID를 확인한 경우에만 계속하세요. 복구
파일에는 CIDR을 기록하지 않습니다. 이후 모듈 03–06 재개 시에는 실제 Azure의
세 VNet·네 Subnet 할당을 다시 조회하고, 아직 누락된 자원이 있으면 모듈 02부터
검사해 재개합니다. cleanup은 CIDR 조회 없이 부분 실행을 정리합니다.
새 실습 전용 `new_run`은 기존 RG 이름을 재사용하지 않으므로 복구에 사용하지 않습니다.
cleanup은 실제 Azure 자원의 태그까지 대조하므로 이름만 추측해서는 삭제할 수 없습니다.
JSON은 감사·복구를 위해 로컬에 유지되며 Git에는 포함되지 않습니다.

<a id="기존-schema-2-실행-복구"></a>
## 기존 schema 2 실행 복구

기존 고정 CIDR 실행의 상태·VNet 주소를 새 IPAM 버전으로 변환하지 않습니다.
**원래 schema 2 상태 JSON을 보관**하고 별도 디렉터리에서 고정된
`8d4781f` 버전의 교재·스크립트로만 재개하거나 cleanup하세요. 아래 Git 태그
`workshop-pre-ipam-8d4781f`는 운영자가 게시하기 전에는 원격에서 가져올 수
없습니다. 게시 여부를 먼저 확인하고, 없으면 운영자에게 요청하세요.

```bash
# 기존 작업 디렉터리는 변경하지 않습니다. 태그가 게시된 뒤 별도 clone에서 실행하세요.
git clone https://github.com/jungwoonlee_microsoft/ms-landing-zone-02.git \
  "$HOME/ms-landing-zone-02-legacy" &&
cd "$HOME/ms-landing-zone-02-legacy" &&
git fetch origin tag workshop-pre-ipam-8d4781f &&
git checkout --detach workshop-pre-ipam-8d4781f &&
git rev-parse --short=7 HEAD
```

마지막 출력이 `8d4781f`인지 확인합니다. 원래 JSON을 이 별도 clone에 안전하게
복사한 뒤 **구버전 모듈 01의 복구**로 원래 구독·상태를 확인하고, 구버전
모듈 07의 cleanup을 사용하세요. 파일을 잃었다면 원래 ID·구독·리전과
schema 2였다는 사실을 운영자와 확인한 후에만 구버전 복구 절차를 따릅니다.
이 저장소의 schema 3 `create_run`이나 `cleanup.sh`를 구버전 실행에 사용하지 않습니다.

## 운영 Landing Zone으로 확장하기

👁️ **설명**

| 이번 실습 | 운영 환경에서 추가할 설계 |
|---|---|
| 단일 구독과 RG 3개 | 관리 그룹, Connectivity/Management 구독, 워크로드별 구독 |
| Connectivity·Security Admin·Routing AVNM | 운영에서는 지역·구독별 정책 소유자와 배포 권한·변경 승인을 분리 |
| Spoke A/B의 정적 Network Group membership | 운영에서는 Azure Policy 기반 동적 membership도 검토하되 별도 검증 후 도입 |
| Hub-and-Spoke Connectivity Configuration 1개와 피어링 강제 | 다중 region/scope 및 강제 설정 변경 권한·배포 절차를 별도 검토 |
| Hub 테스트 VM | 공유 네트워크 기능만 Hub에 배치, 실제 앱은 Spoke |
| 실습용 Contributor 권한 | 최소 역할, PIM, 역할 분리, 정기 access review |
| 이름과 태그 | Azure Policy 상속, 예외 승인, 배포 표준 |
| 사설 HTTP | 인증·인가·TLS, 인증서 수명 주기 |
| Hub NAT·Spoke Firewall egress | 외부 통신 요구사항 분석, 관리 경로 분리, HA·DR·하이브리드 연결 |
| 두 Spoke의 AVNM 관리형 UDR | **Preview**인 Routing Configuration의 운영 지원 상태와 정책·락·관리형 RG 요구를 별도 검증 |
| Firewall 로그 | 중앙 진단 정책, 경고, 보존·비용 정책 |
| 관리형 디스크 기본 암호화 | 규제 요구에 따른 host encryption·키 관리·백업 |

⚠️ **주의**

이 교재의 Run Command용 `AzureCloud:443` 허용은 다른 Azure 고객의 공인 주소도
포함할 수 있습니다. 운영용 tenant 제한 정책으로 복사하지 마세요.
또한 위 표의 동적 membership, 다중 region의 피어링 강제, AVNM Routing Preview,
Security Admin Rules는 **운영 설계 검토 항목**이지 현재 워크숍의 대체 실행 경로가 아닙니다.

## 트러블슈팅

| 증상 | 조치 |
|---|---|
| Ownership mismatch | 구독·실행 ID·태그 확인; 태그를 바꿔서 우회하지 않기 |
| 삭제가 45분 이상 지속 | RG의 Locks·배포 진행 상태 확인 후 재실행 |
| 권한 오류 | RG 삭제 권한을 운영자에게 요청; “삭제 성공”으로 기록하지 않기 |
| 셸이 끊김 | 상태 복구 후 같은 cleanup 실행; 새 ID 만들지 않기 |
| Firewall 배포 도중 중단 | Portal 배포 상태를 확인하고 같은 세 RG를 정리 |

## 완료 체크

- 정확한 실습 RG 세 개의 삭제를 확인했습니다.
- 공유 Network Watcher와 Cloud Shell 저장소는 보존했습니다.
- 운영 환경에 그대로 복사하면 안 되는 실습 예외를 이해했습니다.

## 다음 단계

- [이전: 경로와 보안 검증](06-routing-validation.md)
- [워크숍 개요](../README.md)
