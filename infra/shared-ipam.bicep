targetScope = 'resourceGroup'

param location string = 'koreacentral'

resource manager 'Microsoft.Network/networkManagers@2024-05-01' = {
  name: 'avnm-lzbegin-ipam'
  location: location
  properties: {
    networkManagerScopes: {
      managementGroups: []
      subscriptions: [subscription().id]
    }
    networkManagerScopeAccesses: []
  }
}

resource pool 'Microsoft.Network/networkManagers/ipamPools@2024-05-01' = {
  name: 'ipam-lzbegin-shared'
  parent: manager
  location: location
  properties: {
    addressPrefixes: ['172.20.0.0/14']
  }
}

output poolId string = pool.id
