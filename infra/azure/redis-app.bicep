param location string = 'uksouth'
param environmentId string
param apiIdentityId string
param keyVaultSecretUrl string

resource redis 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'redis'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${apiIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: [
        {
          name: 'redispw'
          keyVaultUrl: keyVaultSecretUrl
          identity: apiIdentityId
        }
      ]
      ingress: {
        external: false
        targetPort: 6379
        exposedPort: 6379
        transport: 'Tcp'
      }
    }
    template: {
      containers: [
        {
          name: 'redis'
          image: 'docker.io/library/redis:7-alpine'
          command: [
            '/bin/sh'
          ]
          args: [
            '-c'
            'exec redis-server --requirepass "$REDIS_PASSWORD" --appendonly no --save ""'
          ]
          env: [
            {
              name: 'REDIS_PASSWORD'
              secretRef: 'redispw'
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

output fqdn string = redis.properties.configuration.ingress.fqdn
