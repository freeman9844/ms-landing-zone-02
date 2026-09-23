#!/usr/bin/env python3
# 저장한 NIC 유효 경로 JSON과 목적지 IP로 예상 next hop을 확인합니다. Azure API는 호출하지 않습니다.
# 사용법: assert-route.py ROUTE_JSON DESTINATION NEXT_HOP [NEXT_HOP_IP]
import ipaddress
import json
import sys


def main():
    if len(sys.argv) not in (4, 5):
        raise ValueError("Usage: assert-route.py ROUTE_JSON DESTINATION NEXT_HOP [NEXT_HOP_IP]")
    with open(sys.argv[1], encoding="utf-8") as stream:
        table = json.load(stream)
    destination = ipaddress.ip_address(sys.argv[2])
    candidates = []
    # Azure의 모든 경로 우선순위를 재구현하지 않고, NIC가 Active로 보고한 결과를 보수적으로 검사합니다.
    # 비활성 경로는 제외하고 목적지 IP를 포함하는 주소 범위만 후보로 모읍니다.
    for route in table["value"]:
        if route["state"].lower() != "active":
            continue
        for prefix in route["addressPrefix"]:
            network = ipaddress.ip_network(prefix)
            if destination in network:
                candidates.append((network.prefixlen, route))
    if not candidates:
        # 조회 결과가 없다는 사실과 명시적인 None(버림) 경로는 다릅니다. 증거 누락은 실패입니다.
        raise ValueError("No active matching route; missing evidence is not a drop route")
    # 가장 긴 접두사를 택합니다. 예: 상대 Spoke /16은 사설 주소 /8과 기본 경로 /0보다 구체적입니다.
    longest = max(length for length, _ in candidates)
    selected = [route for length, route in candidates if length == longest]
    # None은 Python의 빈 값이 아니라 Azure nextHopType의 문자열이며, 해당 경로가 패킷을 버린다는 뜻입니다.
    # 동률 후보 중 편리한 하나만 고르지 않습니다. 최장 접두사 후보 모두가 기대한 경로여야 통과합니다.
    for route in selected:
        if route["nextHopType"].lower() != sys.argv[3].lower():
            raise ValueError(f"Unexpected effective next hop: {route}")
        # VirtualAppliance라는 유형만 맞는 것으로 부족하므로 지정된 경우 Firewall의 정확한 IP까지 비교합니다.
        if len(sys.argv) == 5 and route.get("nextHopIpAddress") != [sys.argv[4]]:
            raise ValueError(f"Unexpected next hop IP: {route}")
    print(f"PASS: {destination} /{longest} -> {sys.argv[3]}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        sys.exit(f"ERROR: route evidence invalid: {error}")
