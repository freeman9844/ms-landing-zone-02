// 한 RG에 한 구역의 NAT와 출구용 Public IP를 만듭니다. 기본 배포 범위는 리소스 그룹입니다.
// VM NIC에 Public IP를 붙이는 템플릿이 아니며, 인터넷에서 VM으로 접속하는 경로를 열지 않습니다.
param runId string
param location string
// zone은 Hub/Spoke 이름입니다. 이 매개변수로 Azure 가용 영역을 선택하지 않습니다.
@allowed(['hub', 'spokea', 'spokeb'])
param zone string

// RG 태그는 하위 자원에 자동 상속되지 않으므로 각각 같은 실습 소유 태그를 지정합니다.
var tags = {
  workshop: 'lz-beginner'
  environment: 'lab'
  runId: runId
  managedBy: 'workshop'
}

resource publicIp 'Microsoft.Network/publicIPAddresses@2024-07-01' = {
  name: 'pip-lzbegin-${zone}-${runId}'
  location: location
  tags: tags
  // Standard NAT에서 사용할 Standard·고정 IPv4입니다. 이후 Firewall의 Public IP와는 별도 자원입니다.
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource nat 'Microsoft.Network/natGateways@2024-07-01' = {
  name: 'nat-lzbegin-${zone}-${runId}'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: {
    // 유휴 TCP 연결의 제한(분)입니다. NAT 자원의 수명이나 과금 종료 시간을 뜻하지 않습니다.
    idleTimeoutInMinutes: 4
    // 속성에서 publicIp.id를 참조하므로 Bicep이 Public IP 생성과의 의존 관계를 추론합니다.
    publicIpAddresses: [{ id: publicIp.id }]
  }
}

// 생성만으로 VM의 출구가 바뀌지 않습니다. 교재의 subnet update --nat-gateway에서 이 NAT를 연결합니다.
// 확장에서 Spoke NAT를 제거할 때는 Subnet 분리 → NAT 삭제 → 이 Public IP 삭제 순서를 지킵니다.
output natGatewayId string = nat.id
output publicIpId string = publicIp.id
