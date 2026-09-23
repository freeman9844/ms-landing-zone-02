#!/usr/bin/env bash
# run-vm.sh를 통해 Spoke VM 안에서 실행하는 설치 스크립트입니다. Cloud Shell에서 직접 실행하지 않습니다.
# 비민감한 spokea/spokeb 문자열만 제공하는 HTTP 서비스로, 연결된 대상이 맞는지 구분합니다.
set -euo pipefail
label="${1:-$(hostname -s)}"
# 명시한 인수 또는 VM 호스트 이름이 Spoke 형식인지 확인해 Hub 등 잘못된 대상의 설치를 막습니다.
case "$label" in
  spokea|spokea-*) label=spokea ;;
  spokeb|spokeb-*) label=spokeb ;;
  *) printf 'ERROR: Not a workshop Spoke VM.\n' >&2; exit 1 ;;
esac
command -v python3 >/dev/null
# 응답 본문에 실행 ID나 비밀은 넣지 않습니다. 연결 검증은 어느 Spoke에 도달했는지만 비교합니다.
# 서버는 파일을 읽기만 하면 됩니다. 전용 디렉터리에 응답을 두고 비특권 사용자도 읽을 수 있게 합니다.
install -d -m 0755 /var/lib/lzbegin-http
printf '%s\n' "$label" > /var/lib/lzbegin-http/index.html
chmod 0644 /var/lib/lzbegin-http/index.html
# 설치는 관리 권한으로 하지만 서비스는 nobody/nogroup으로 실행합니다.
# 아래 unit은 쓰기·홈 접근 등을 제한하며, 0.0.0.0 바인딩의 네트워크 접근 범위는 Subnet NSG로 제한합니다.
# NoNewPrivileges는 권한 상승, ProtectSystem/ProtectHome은 파일 접근, PrivateTmp는 임시 디렉터리 공유를 제한합니다.
# 0.0.0.0은 모든 IPv4 인터페이스에서 수신한다는 뜻이며, VM에 공인 IP를 생성한다는 뜻은 아닙니다.
cat > /etc/systemd/system/lzbegin-http.service <<'UNIT'
[Unit]
Description=Non-sensitive landing zone workshop response
After=network.target
[Service]
User=nobody
Group=nogroup
WorkingDirectory=/var/lib/lzbegin-http
ExecStart=/usr/bin/python3 -m http.server 8080 --bind 0.0.0.0
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
# unit 변경을 반영하고 재부팅 후에도 시작하도록 설정합니다. active 상태만으로 HTTP 준비를 단정하지 않습니다.
systemctl daemon-reload
systemctl enable --now lzbegin-http.service
systemctl is-active --quiet lzbegin-http.service
# VM 내부의 loopback으로 응답 내용까지 검사해 서비스 장애와 이후 네트워크 차단을 구분합니다.
# 시작 직후 연결 오류만 짧게 재시도하며, 엉뚱한 본문이나 마지막 시도 실패는 명시적으로 중단합니다.
# 이 loopback 성공은 게스트 서비스만 증명합니다. 다른 VM의 접근 가능 여부는 NSG·경로 검증에서 확인합니다.
python3 - "$label" <<'PY'
import sys
import time
import urllib.error
import urllib.request
for attempt in range(10):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/", timeout=2) as response:
            body = response.read().decode().strip()
        if body != sys.argv[1]:
            raise SystemExit(f"ERROR: unexpected local response {body!r}")
        print(f"PASS: local service {body}")
        break
    except urllib.error.URLError as error:
        if attempt == 9:
            raise SystemExit(f"ERROR: service did not become ready: {error}")
        time.sleep(1)
PY
