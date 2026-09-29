@allowed([
  'hub'
  'spokea'
  'spokeb'
])
param zone string
param runId string
param location string = 'koreacentral'
param ipamPoolId string

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' existing = {
  name: 'nsg-lzbegin-${zone}-${runId}'
}

var workloadSubnet = zone == 'hub' ? 'snet-management' : 'snet-workload'

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-lzbegin-${zone}-${runId}'
  location: location
  tags: {
    workshop: 'lz-beginner'
    environment: 'lab'
    runId: runId
    managedBy: 'workshop'
  }
  properties: {
    addressSpace: {
      ipamPoolPrefixAllocations: [
        {
          numberOfIpAddresses: '4096'
          pool: {
            id: ipamPoolId
          }
        }
      ]
    }
    subnets: concat([
      {
        name: workloadSubnet
        properties: {
          ipamPoolPrefixAllocations: [
            {
              numberOfIpAddresses: '256'
              pool: {
                id: ipamPoolId
              }
            }
          ]
          networkSecurityGroup: {
            id: nsg.id
          }
          defaultOutboundAccess: false
        }
      }
    ], zone == 'hub' ? [
      {
        name: 'AzureFirewallSubnet'
        properties: {
          ipamPoolPrefixAllocations: [
            {
              numberOfIpAddresses: '64'
              pool: {
                id: ipamPoolId
              }
            }
          ]
        }
      }
    ] : [])
  }
}

output vnetId string = vnet.id
output vnetPrefixes array = vnet.properties.addressSpace.addressPrefixes
output subnets array = vnet.properties.subnets
