// The pilot Container Apps: api, workers, collector and web. Each runs its own managed identity, pulls from the
// registry with that identity (AcrPull), and gets non-secret settings only. Secrets are not in this file: the code
// reads them from Key Vault at run time with the same identity (OVERWATCH_KEY_VAULT_URL, AZURE_CLIENT_ID).
//
// The images are the hello-world placeholder until the real images are pushed. Changing the image later is one
// parameter (or az containerapp update --image), and the settings stay as they are.
//
// Deploy: az deployment group create -g rg-diucs-pilot-uks -f infra/azure/apps.bicep -n pilot-apps

param location string = 'uksouth'
param environmentName string = 'cae-diucs-pilot-uks'
param registryServer string = 'acrdiucspilot7k2q.azurecr.io'
param keyVaultUrl string = 'https://kv-diucs-pilot-7k2q.vault.azure.net/'
param neo4jUri string = 'neo4j+s://8cb817d8.databases.neo4j.io'
// An Aura instance's username is its id, not "neo4j" (the settings default).
param neo4jUser string = '8cb817d8'
param baseUrl string = 'https://overwatch.mirroredintelligence.com'
param operatorBaseUrl string = 'https://overwatch-admin.mirroredintelligence.com'
param fhirBaseUrl string = 'https://api.internal.victorioustree-0cb125c2.uksouth.azurecontainerapps.io/fhir'
param placeholderImage string = 'mcr.microsoft.com/k8se/quickstart:latest'
// The real images, pushed to the pilot registry. Pass the tag at deploy time (the commit short sha).
param backendImage string
param webImage string
// The Entra app registrations (GUIDs, not secrets) and the operator's own directory.
param entraStaffClientId string = '7fb43bde-6a6d-4aed-9cac-9118de48ab52'
param entraOperatorClientId string = '9b4e9144-358a-47cc-9ffb-e63bf0d21c41'
param operatorDirectoryId string = 'c5901e0b-8d43-4ae8-97c3-ca6c52573a33'
// The platform's Twilio account SID (an identifier, not a secret): passed at deploy time, never stored here.
// Its auth token is the secret twilio-auth-token. Used for the platform's own email (admin consent invitations).
param platformTwilioAccountSid string
// The platform's shared text number (E.164), for organisations that have no number of their own yet (outgoing texts
// only; it is never an organisation's number and no text to it identifies one). Passed at deploy time, never stored here.
// Left empty, the shared line is not offered. It sends from the platform account above, with the secret twilio-auth-token.
param platformSmsFrom string = ''

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: environmentName
}

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: 'id-diucs-api-pilot'
}
resource webIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: 'id-diucs-web-pilot'
}
resource workersIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: 'id-diucs-workers-pilot'
}
resource collectorIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: 'id-diucs-collector-pilot'
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'api'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${apiIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8000
        transport: 'Auto'
      }
      registries: [
        {
          server: registryServer
          identity: apiIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: '${registryServer}/diucs-backend:${backendImage}'
          env: [
            { name: 'OVERWATCH_KEY_VAULT_URL', value: keyVaultUrl }
            { name: 'AZURE_CLIENT_ID', value: apiIdentity.properties.clientId }
            { name: 'OVERWATCH_BASE_URL', value: baseUrl }
            { name: 'OVERWATCH_NEO4J_URI', value: neo4jUri }
            { name: 'OVERWATCH_NEO4J_USER', value: neo4jUser }
            { name: 'OVERWATCH_EDGE', value: 'none' }
            { name: 'OVERWATCH_ENTRA_STAFF_CLIENT_ID', value: entraStaffClientId }
            { name: 'OVERWATCH_ENTRA_OPERATOR_CLIENT_ID', value: entraOperatorClientId }
            { name: 'OVERWATCH_OPERATOR_DIRECTORY_ID', value: operatorDirectoryId }
            { name: 'OVERWATCH_PLATFORM_TWILIO_ACCOUNT_SID', value: platformTwilioAccountSid }
            { name: 'OVERWATCH_PLATFORM_SMS_FROM', value: platformSmsFrom }
            { name: 'OVERWATCH_POSTCODE_CENTROIDS_PATH', value: '/app/data/postcodes/centroids-dt-bh.csv' }
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

resource workers 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'workers'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${workersIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        {
          server: registryServer
          identity: workersIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'workers'
          image: '${registryServer}/diucs-backend:${backendImage}'
          command: ['python', '-m', 'overwatch.bootstrap.workers_main']
          env: [
            { name: 'OVERWATCH_KEY_VAULT_URL', value: keyVaultUrl }
            { name: 'AZURE_CLIENT_ID', value: workersIdentity.properties.clientId }
            { name: 'OVERWATCH_NEO4J_URI', value: neo4jUri }
            { name: 'OVERWATCH_NEO4J_USER', value: neo4jUser }
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

resource collector 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'collector'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${collectorIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 80
        transport: 'Auto'
      }
      registries: [
        {
          server: registryServer
          identity: collectorIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'collector'
          image: placeholderImage
          env: [
            { name: 'AZURE_CLIENT_ID', value: collectorIdentity.properties.clientId }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

resource web 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'web'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${webIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 3000
        transport: 'Auto'
        // Bindings made with the CLI: a deployment without them would remove them.
        customDomains: [
          {
            name: 'overwatch.mirroredintelligence.com'
            bindingType: 'SniEnabled'
            certificateId: '${environment.id}/managedCertificates/mc-cae-diucs-pilo-overwatch-mirror-1741'
          }
          {
            name: 'overwatch-admin.mirroredintelligence.com'
            bindingType: 'SniEnabled'
            certificateId: '${environment.id}/managedCertificates/mc-cae-diucs-pilo-overwatch-admin--6315'
          }
        ]
      }
      registries: [
        {
          server: registryServer
          identity: webIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: '${registryServer}/diucs-web:${webImage}'
          env: [
            { name: 'OVERWATCH_KEY_VAULT_URL', value: keyVaultUrl }
            { name: 'AZURE_CLIENT_ID', value: webIdentity.properties.clientId }
            { name: 'OVERWATCH_FHIR_BASE_URL', value: fhirBaseUrl }
            // OVERWATCH_VISITOR_ADDRESS_SOURCE (not set: the default is right for this ingress, DEC-1311) says where web reads
            // the visitor address it passes to api for the rate limits: 'x-forwarded-for' (default, the right-most entry the
            // ingress added) or 'cf-connecting-ip' (set it only when Cloudflare proxies web).
            { name: 'ENTRA_CLIENT_ID', value: entraStaffClientId }
            { name: 'OVERWATCH_PUBLIC_URL', value: baseUrl }
            { name: 'OPERATOR_ENTRA_CLIENT_ID', value: entraOperatorClientId }
            { name: 'OPERATOR_ENTRA_DIRECTORY_ID', value: operatorDirectoryId }
            { name: 'OVERWATCH_OPERATOR_PUBLIC_URL', value: operatorBaseUrl }
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
