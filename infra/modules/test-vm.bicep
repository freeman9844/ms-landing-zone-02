// 한 구역의 테스트 VM과 사설 NIC만 만듭니다. HTTP 응답 서비스는 나중에 Run Command로 설치합니다.
// Hub는 요청을 보내는 관리 VM, 두 Spoke는 요청에 응답하는 워크로드 VM으로 사용합니다.
param runId string
param location string
@allowed(['hub', 'spokea', 'spokeb'])
param zone string
// 모듈 02에서 이미 만든 Subnet의 전체 ID입니다. 여기서 Subnet·NSG를 덮어쓰지 않습니다.
param subnetId string
param sshPublicKey string
param adminUsername string = 'workshopadmin'

var name = 'vm-lzbegin-${zone}-${runId}'
// VM과 NIC에 직접 붙이는 태그입니다. 운영 환경 전체의 태그 준수를 보장하는 정책은 아닙니다.
var tags = {
  workshop: 'lz-beginner'
  environment: 'lab'
  runId: runId
  managedBy: 'workshop'
}

resource nic 'Microsoft.Network/networkInterfaces@2024-07-01' = {
  name: 'nic-lzbegin-${zone}-${runId}'
  location: location
  tags: tags
  properties: {
    // 이 VM은 라우터가 아닙니다. Spoke 사이 중계는 확장 과정의 Azure Firewall이 담당합니다.
    enableIPForwarding: false
    ipConfigurations: [{
      name: 'private'
      properties: {
        // 사설 IP는 Subnet에서 자동 할당됩니다. .4로 가정하지 않고 검증 시 실제 NIC에서 조회합니다.
        // publicIPAddress 속성을 두지 않아 VM에 직접 연결되는 공인 IP는 없습니다.
        privateIPAllocationMethod: 'Dynamic'
        subnet: { id: subnetId }
      }
    }]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2024-11-01' = {
  // 아래 세 예외는 교육용 VM에만 적용합니다. VM agent는 Run Command에 필요합니다.
  // 디스크 SSE는 사용하지만 host encryption 및 게스트 ADE까지 구성했다는 뜻은 아닙니다.
  // 각 Checkov 예외의 범위와 운영 전환 조건은 docs/maintainer-validation.md에 설명합니다.
  // checkov:skip=CKV_AZURE_50:Run Command requires the VM agent/extension; access is limited by Azure RBAC.
  // checkov:skip=CKV_AZURE_97:Non-sensitive lab uses managed disk SSE; host encryption requires a subscription feature prerequisite.
  // checkov:skip=CKV_AZURE_151:Linux managed disks use platform SSE; guest Azure Disk Encryption is outside this disposable lab.
  name: name
  location: location
  tags: tags
  properties: {
    // 실습용 2 vCPU / 4 GiB SKU입니다. 구독·리전의 사용 가능 여부와 quota는 preflight로 확인합니다.
    hardwareProfile: { vmSize: 'Standard_B2als_v2' }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        // VM 삭제 시 OS 디스크도 함께 삭제합니다. 실습 VM 안에 보존할 업무 데이터를 두지 않습니다.
        deleteOption: 'Delete'
        managedDisk: { storageAccountType: 'StandardSSD_LRS' }
      }
    }
    osProfile: {
      computerName: '${zone}-${runId}'
      adminUsername: adminUsername
      linuxConfiguration: {
        // 비밀번호 로그인을 끄고 공개 키만 등록합니다. 교재의 주된 관리 경로는 SSH가 아닌 VM agent입니다.
        disablePasswordAuthentication: true
        provisionVMAgent: true
        ssh: {
          publicKeys: [{
            path: '/home/${adminUsername}/.ssh/authorized_keys'
            keyData: sshPublicKey
          }]
        }
      }
    }
    // Trusted Launch의 Secure Boot와 vTPM을 켭니다. 네트워크 접근 제어(NSG)를 대신하지는 않습니다.
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: {
        secureBootEnabled: true
        vTpmEnabled: true
      }
    }
    // storageUri를 별도 지정하지 않는 관리형 부팅 진단입니다. Firewall 흐름 로그와는 다른 증거입니다.
    diagnosticsProfile: { bootDiagnostics: { enabled: true } }
    networkProfile: {
      networkInterfaces: [{
        // NIC ID 참조가 배포 의존 관계를 만들며, VM 삭제 시 이 NIC도 함께 삭제하도록 지정합니다.
        id: nic.id
        properties: { deleteOption: 'Delete' }
      }]
    }
  }
}

output vmName string = vm.name
output nicId string = nic.id
// !는 배포 후 IP가 할당된다는 전제를 Bicep 형식 검사에 알려 줍니다. 실제 통신 검사는 별도로 수행합니다.
output privateIp string = nic.properties.ipConfigurations[0].properties.privateIPAddress!
