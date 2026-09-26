// 모듈 05에서 VM·NIC와 Hub NAT·Public IP를 준비하는 보조 템플릿입니다.
// VNet·NSG·Subnet은 교재의 CLI로 먼저 만듭니다. 이 파일은 그 자원을 만들거나 수정하지 않습니다.
// 한 구독 안의 세 기존 RG에 배포하므로 az deployment sub what-if/create로 실행합니다.
targetScope = 'subscription'

// 상태 JSON의 실행 ID를 그대로 받아 CLI에서 만든 자원과 이름을 일치시킵니다.
@minLength(6)
@maxLength(12)
param runId string
param location string = 'koreacentral'
// VM에 등록할 SSH 공개 키만 전달합니다. 개인 키는 이 템플릿이나 배포 인수에 넣지 않습니다.
param sshPublicKey string
// RG 이름을 받는다고 RG가 생성되지는 않습니다. 소유권 확인은 배포 전 교재에서 수행합니다.
param hubResourceGroup string
param spokeaResourceGroup string
param spokebResourceGroup string

// zone은 가용 영역이 아니라 실습 구역입니다. 배열 순서는 아래 outputs의 인덱스와 대응합니다.
var zones = [
  { name: 'hub', rg: hubResourceGroup, subnet: 'snet-management' }
  { name: 'spokea', rg: spokeaResourceGroup, subnet: 'snet-workload' }
  { name: 'spokeb', rg: spokebResourceGroup, subnet: 'snet-workload' }
]

// 관리 VM의 명시적 출구로 Hub NAT만 만듭니다. Spoke에는 NAT/Public IP를 만들지 않습니다.
// Hub NAT와 관리 Subnet의 연결은 참가자가 CLI로 직접 수행합니다.
module hubNat './modules/nat.bicep' = {
  name: 'nat-hub-${runId}'
  scope: resourceGroup(hubResourceGroup)
  params: {
    runId: runId
    location: location
    zone: 'hub'
  }
}

// 세 VM은 같은 모듈을 사용하되 각 구역의 기존 Subnet에 연결합니다.
// Hub NAT 모듈과 직접적인 의존 관계는 없습니다. 배포 완료가 Hub NAT 연결 완료를 뜻하지는 않습니다.
module vm './modules/test-vm.bicep' = [for zone in zones: {
  name: 'vm-${zone.name}-${runId}'
  scope: resourceGroup(zone.rg)
  params: {
    runId: runId
    location: location
    zone: zone.name
    // 구독 범위에서는 구독 ID와 RG를 모두 명시해 올바른 Subnet 전체 ID를 구성합니다.
    subnetId: resourceId(subscription().subscriptionId, zone.rg, 'Microsoft.Network/virtualNetworks/subnets', 'vnet-lzbegin-${zone.name}-${runId}', zone.subnet)
    sshPublicKey: sshPublicKey
  }
}]

// 생성 결과를 구역별로 모읍니다. ID는 참조용이며 통신 성공이나 AVNM 경로·보안 정책 완료의 증거는 아닙니다.
output support object = {
  hub: {
    vmName: vm[0].outputs.vmName
    nicId: vm[0].outputs.nicId
    privateIp: vm[0].outputs.privateIp
    natGatewayId: hubNat.outputs.natGatewayId
    publicIpId: hubNat.outputs.publicIpId
  }
  spokea: {
    vmName: vm[1].outputs.vmName
    nicId: vm[1].outputs.nicId
    privateIp: vm[1].outputs.privateIp
  }
  spokeb: {
    vmName: vm[2].outputs.vmName
    nicId: vm[2].outputs.nicId
    privateIp: vm[2].outputs.privateIp
  }
}
