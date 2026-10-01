targetScope = 'resourceGroup'

param runId string
param location string = 'koreacentral'

resource manager 'Microsoft.Network/networkManagers@2024-05-01' existing = {
  name: 'avnm-lzbegin-${runId}'
}

resource pool 'Microsoft.Network/networkManagers/ipamPools@2024-05-01' = {
  parent: manager
  name: 'ipam-lzbegin-${runId}'
  location: location
  properties: {
    addressPrefixes: ['172.20.0.0/14']
  }
}

output poolId string = pool.id
