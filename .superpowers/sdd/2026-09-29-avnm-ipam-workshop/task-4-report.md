# Task 4 — 실제 Azure IPAM CIDR 조회와 검증

## 구현

- `load_ipam_cidrs`는 상태 파일의 정확한 구독/RG/VNet/Subnet 이름으로 `az network vnet show` 세 번, `az network vnet subnet show` 네 번만 호출한다. 호출 전에 기존 CIDR 환경 변수 및 이전 zone 대상/PREFIX를 비운다. CLI 오류, 잘못된 JSON 또는 검증 실패 시 `ERROR:`와 함께 중단하며 **어떤 이전 주소도 다시 export하지 않는다**.
- Python `ipaddress` 검증기는 실제 Azure CLI 응답의 전체 자원 ID, VNet 소유 태그, VNet `addressSpace.ipamPoolPrefixAllocations` 및 Subnet `ipamPoolPrefixAllocations`의 단일 pool ID/주소 수를 검사한다. 실제 VNet `addressSpace.addressPrefixes`, Subnet `addressPrefix` 또는 `addressPrefixes`를 읽어 정확한 단일 IPv4 `/20`·`/24`·`/26`, `172.20.0.0/14` 포함 관계, 각 Subnet의 부모 포함 관계, 세 VNet 간 및 두 Hub Subnet 간 비중복을 검증한다.
- 모든 검사가 성공한 경우에만 `HUB_VNET_CIDR`, `SPOKEA_VNET_CIDR`, `SPOKEB_VNET_CIDR`, `HUB_SUBNET_CIDR`, `SPOKEA_SUBNET_CIDR`, `SPOKEB_SUBNET_CIDR`, `FIREWALL_SUBNET_CIDR` 일곱 변수를 한꺼번에 export한다. `zone_context`는 해당 VNet 실제 CIDR을 `PREFIX`로 전달하고 주소 미초기화/알 수 없는 구역에서는 이전 구역 대상을 비운다. `load_run`의 기존 `clear_run`은 이전 CIDR도 해제한다.
- 모듈 03–06 공통 준비와 독립 검증 스크립트는 구독 및 소유 RG 확인 뒤에 resolver를 실행한다. `run-vm.sh`도 실제 IP를 확인한 후 zone을 선택한다. VNet 생성 전에도 동작해야 하는 preflight와 부분 실행 cleanup은 resolver를 호출하지 않는다. 모듈 02는 세 배포를 마친 뒤 실제 할당 주소 일곱 개를 표시한다.

## RED (구현 전 확인)

1. 신규 `test_ipam_cidrs.py`를 작성하고 `python3 -m unittest discover -s tests -p test_ipam_cidrs.py -v` 실행: 정상 할당/오류 조건이 미구현 `load_ipam_cidrs` 때문에 실패했다. `zone_context`의 미해결 CIDR 거부 단독 테스트는 예상대로 기존 함수의 성공(종료 코드 0) 때문에 실패했다.
2. 문서 준비 블록 통합 테스트는 기존 준비가 구독/RG까지만 검사해 Azure 조회 7개가 호출되지 않는 것으로 실패(가짜 CLI 4/11 호출). 독립 검증 테스트도 예상 CIDR 조회 대신 연결 설정/Firewall부터 읽어서 실패.
3. `set -u`에서 상태 미설정 `zone_context hub` 테스트는 예상 `ERROR:` 대신 `RG_HUB: unbound variable`로 실패. 이전 zone 실패 후 대상을 정리하도록 변경했다. 다시 조회 중 API 실패 시 이전 `PREFIX`가 남는다는 실패 테스트도 먼저 관찰하고, resolver 시작 시 zone 대상까지 함께 해제했다.

## GREEN 및 회귀

- 가짜 Azure CLI를 통해 성공 순서/변수 값과 실패 시 기존 export 제거를 실제 셸 프로세스에서 확인. 잘못된 pool·할당 크기·누락된 할당/서브넷·틀린 ID/태그·잘못된 prefix 길이·부모 밖 Subnet·두 Hub Subnet 중복·VNet 중복·pool 범위 밖 CIDR·비정규 CIDR·IPv6·비정상 JSON·조회 실패 모두 거부하는 테스트 포함.
- 모듈 02의 최종 출력 블록, 모듈 03–06 준비 블록, 독립 검증의 후속 증거 전 거부, VM 헬퍼, 종료된/Hub RG만 있는 정리 실행을 fake CLI로 검증. 기존 테스트의 준비 fixture/상태 전환/zone 의존 테스트는 새 계약에 맞게 갱신했다.
- 실제 Azure에는 접속하거나 자원을 변경하지 않았다. fake `az`가 예상 외 호출을 거부한다. 실환경 IPAM 응답·동시 할당은 별도 승인된 리허설에서 검증해야 한다.

| 검증 대상 | 직접 실행한 조건/기대 결과 |
|---|---|
| 정상 조회 | Hub `172.20.0.0/20`, 관리 `172.20.0.0/24`, Firewall `172.20.1.0/26`, A `172.20.16.0/20`·`/24`, B `172.20.32.0/20`·`/24` → 정확히 일곱 변수 export |
| ID/소유/할당 | VNet/Subnet ID 또는 VNet 태그 변조, 잘못된 pool ID, 누락/중복 allocation, VNet 4096·Subnet 256·Firewall 64 크기 불일치 → 실패하고 기존 일곱 변수 모두 `UNSET` |
| CIDR 무결성 | 잘못된 `/20`·`/24`·`/26`, VNet 중복, Hub 두 Subnet 중복, Subnet이 부모 밖, pool 밖, IPv6, 비정규 IPv4, 누락된 Subnet prefix, 다중 VNet prefix → 실패 |
| 조회 실패·재시도 | 첫 VNet 또는 마지막 Subnet CLI 실패, 응답 JSON 손상, 성공 조회 직후 재조회 실패 → 이전 CIDR 및 `PREFIX`/zone 대상 제거 |
| 실행 경계 | module02은 전체 생성 후 출력, module03–06 및 독립 verifier는 소유 검사 뒤 조회, preflight는 VNet 조회 없음, cleanup은 RG가 모두 없거나 Hub만 있을 때도 CIDR 조회 없이 완료 |

## 확인 명령

- `python3 -m unittest discover -s tests -p test_ipam_cidrs.py -q`
- `python3 -m unittest discover -s tests -p test_state.py -q`
- `python3 -m unittest discover -s tests -p test_core.py -q`
- `python3 -m unittest discover -s tests -p test_extension.py -q`
- `python3 -m unittest discover -s tests -p test_run_vm.py -q`
- `python3 -m unittest discover -s tests -p test_network_docs.py -q`
- `python3 -m unittest discover -s tests -p test_stepwise_docs.py -q`
- `python3 -m unittest discover -s tests -p 'test_*.py' -q` — 최종 **229 tests, OK** (첫 전체 실행에서는 이전 zone 계약을 사용하는 `test_recovery_docs` fixture 1건이 실패; fixture 수정 후 재실행 성공)
- `bash -n scripts/workshop-ipam.sh scripts/workshop-common.sh scripts/cleanup.sh scripts/run-vm.sh scripts/verify-core.sh scripts/verify-extension.sh scripts/preflight.sh`
- `python3 -m py_compile scripts/check-ipam-cidrs.py` 및 `git --no-pager diff --check`

## 범위 및 주의

이 작업은 CIDR 계약과 세션 준비를 확립한다. 기존 모듈 04–06의 모든 방화벽/라우팅 규칙 및 예시 안에 남은 고정 `10.x` 주소를 실제 변수로 변경하는 일은 다음 작업이 필요하다. 정적 테스트를 실환경 pool 할당이나 통신 검증으로 오인하지 않는다.
