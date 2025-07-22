# Deep Research MCP Deployment

This project provides a production-ready deployment workflow for the Deep Research MCP Python application using Docker, Helm, and Kubernetes. It is designed for seamless deployment to Azure Kubernetes Service (AKS) with images stored in Azure Container Registry (ACR), and is fully compatible with Mac M1 (arm64) and amd64 platforms.

---

## Project Structure

- `deep_research_mcp.py` — Main Python application (FastMCP server, listens on port 8001)
- `.env` — Environment variables required for Azure AI/Agents integration
- `Dockerfile` — Multi-stage build, optimized for size and security, exposes port 8001
- `helm/deep-research-mcp/` — Helm chart for Kubernetes deployment
- `deploy.sh` — Automated script to build, push, and deploy the app

---

## MCP Tool: Deep Research Report

The MCP server exposes a tool named **retrieve_deep_research_report** via FastMCP, implemented in `deep_research_mcp.py`. This tool enables programmatic, automated research on arbitrary topics using Azure AI Agents and Bing Search.

### Tool Function

**retrieve_deep_research_report**  
Retrieves a research report on a user-specified topic, leveraging external Bing Search and a large language model (LLM) for synthesis. The tool supports different report lengths, output languages, and optional custom instructions.

#### Parameters

- `research_topic` (str, required): The topic to research.
- `report_type` (str, optional): The type of report to generate. One of `'brief'`, `'medium'`, or `'comprehensive'`. Default: `'comprehensive'`.
- `language` (str, optional): Output language in ISO 639-1 format (e.g., `'en'` for English, `'zh'` for Chinese). Default: `'en'`.
- `other_instructions` (str, optional): Additional instructions for the agent (e.g., style, focus, exclusions).

#### Behavior & Implementation

- On invocation, the tool:
  1. Authenticates with Azure AI Projects using environment variables.
  2. Looks up the Bing Search connection and Deep Research model deployment.
  3. Creates a new agent with the Deep Research tool attached.
  4. Starts a new thread and sends a user message with formatted instructions.
  5. Initiates a run and polls for completion (can take several minutes).
  6. Streams agent responses and run status updates.
  7. On completion, fetches the final agent message and generates a Markdown research summary, including references/citations if available.
  8. Cleans up by deleting the agent.

- The tool is **asynchronous** and may take several minutes to complete, depending on the complexity of the research topic and report type.

- Output is a Markdown-formatted research report, optionally including a "References" section with unique URLs cited by the agent.

#### Example Usage

Request a comprehensive English report on "quantum computing":

```json
{
  "research_topic": "quantum computing",
  "report_type": "comprehensive",
  "language": "en"
}
```

#### Notes

- The tool is designed for integration with MCP-compatible orchestrators and can be invoked via HTTP (default port 8001).
- For more details on the Deep Research tool, see: https://aka.ms/agents-deep-research
- Environment variables must be set for Azure authentication and resource access (see below).

---

## Prerequisites

- Docker (with buildx enabled for multi-arch builds)
- Helm
- Azure CLI (`az`)
- `yq` (YAML processor, e.g. `brew install yq`)
- Access to an Azure Container Registry (ACR) and AKS cluster
- Kubernetes context set to your target cluster

---

## Enabling Workload Identity in Azure Kubernetes Service (AKS)

This section provides a step-by-step guide to enable Azure AD Workload Identity on your AKS cluster, following the official Microsoft documentation:  
https://learn.microsoft.com/en-us/azure/aks/workload-identity-deploy-cluster

### Prerequisites

- Azure CLI version 2.44.1 or later (`az version`)
- AKS cluster running Kubernetes 1.24 or later
- Sufficient permissions to update AKS cluster features

---

### 1. Register the Workload Identity and OIDC Issuer Features

```sh
az feature register --namespace "Microsoft.ContainerService" --name "EnableWorkloadIdentityPreview"
az feature register --namespace "Microsoft.ContainerService" --name "EnableOIDCIssuerPreview"
az provider register --namespace Microsoft.ContainerService
az provider register --namespace Microsoft.ManagedIdentity
```

Wait for the features to be in the "Registered" state before proceeding:

```sh
az feature list -o table --query "[?contains(name, 'Microsoft.ContainerService/EnableWorkloadIdentityPreview')].{Name:name,State:properties.state}"
az feature list -o table --query "[?contains(name, 'Microsoft.ContainerService/EnableOIDCIssuerPreview')].{Name:name,State:properties.state}"
```

---

### 2. Enable OIDC Issuer and Workload Identity on the AKS Cluster

```sh
az aks update \
  --resource-group <RESOURCE_GROUP> \
  --name <CLUSTER_NAME> \
  --enable-oidc-issuer \
  --enable-workload-identity
```

---

### 3. Verify the OIDC Issuer URL

```sh
az aks show \
  --resource-group <RESOURCE_GROUP> \
  --name <CLUSTER_NAME> \
  --query "oidcIssuerProfile.issuerUrl" \
  -o tsv
```

---

### 4. Create a User-Assigned Managed Identity

```sh
az identity create \
  --name <MANAGED_IDENTITY_NAME> \
  --resource-group <RESOURCE_GROUP>
```

Get the client ID and resource ID:

```sh
az identity show \
  --name <MANAGED_IDENTITY_NAME> \
  --resource-group <RESOURCE_GROUP> \
  --query "{clientId:clientId,resourceId:id}"
```

---

### 5. Create a Federated Identity Credential

You must create a federated identity credential for the managed identity, using the OIDC issuer URL, Kubernetes service account name, and namespace.  
This can be done via the Azure portal, Azure CLI, or ARM/Bicep templates.

**Example using Azure CLI:**

```sh
az identity federated-credential create \
  --name <FEDERATED_CREDENTIAL_NAME> \
  --identity-name <MANAGED_IDENTITY_NAME> \
  --resource-group <RESOURCE_GROUP> \
  --issuer <OIDC_ISSUER_URL> \
  --subject system:serviceaccount:<K8S_NAMESPACE>:<KSA_NAME> \
  --audience api://AzureADTokenExchange
```

---

### 6. Annotate the Kubernetes Service Account

```sh
kubectl annotate serviceaccount <KSA_NAME> \
  --namespace <K8S_NAMESPACE> \
  azure.workload.identity/client-id=<MANAGED_IDENTITY_CLIENT_ID>
```

---

### 7. Assign Azure RBAC Permissions

Assign the necessary Azure RBAC roles to the managed identity so your workload can access required Azure resources.  
For example, to grant access to Azure Key Vault:

```sh
az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee <MANAGED_IDENTITY_CLIENT_ID> \
  --scope /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP>/providers/Microsoft.KeyVault/vaults/<KEYVAULT_NAME>
```

---

### 8. Test Workload Identity Integration

Deploy a test pod using the annotated service account and verify it can access Azure resources using the managed identity.

---

### Notes and Troubleshooting

- Ensure your Azure CLI is up to date.
- Wait for feature registration to reach the "Registered" state before updating the cluster.
- If you encounter issues, refer to the "Troubleshoot" section in the official documentation.
- For advanced scenarios (multi-tenant, multiple federated credentials, etc.), see the official documentation.

---

**Reference:**  
For the most up-to-date and detailed instructions, always refer to:  
https://learn.microsoft.com/en-us/azure/aks/workload-identity-deploy-cluster

---

## Environment Variables

The application requires the following environment variables (set in `.env`):

- `PROJECT_ENDPOINT`
- `MODEL_DEPLOYMENT_NAME`
- `DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME`
- `BING_RESOURCE_NAME`

These are loaded into the container via a Kubernetes ConfigMap.

---

## Dockerfile Details

- Multi-stage build for efficient, secure images
- Installs Python dependencies in a virtualenv
- Copies only necessary files to the final image
- Exposes port **8001** (matching the FastMCP server)
- Supports both `arm64` (Mac M1) and `amd64` architectures

---

## Helm Chart

Located in `helm/deep-research-mcp/`:
- **ConfigMap**: Loads `.env` and injects all variables into the container
- **Deployment**: Uses image and tag from `values.yaml`, mounts env from ConfigMap, exposes port 8001
- **Service**: Type `LoadBalancer` for public internet access on port 8001
- **Helpers**: Standard Helm template helpers for naming

---

## Deployment Instructions

1. **Set up your `.env` file**  
   Fill in all required Azure environment variables.

2. **Authenticate with Azure and ACR**
   ```sh
   az login
   az acr login --name tradingaz
   ```

3. **Build, Push, and Deploy**
   ```sh
   chmod +x deploy.sh
   ./deploy.sh
   ```
   This script will:
   - Build a multi-arch Docker image (`arm64`, `amd64`)
   - Push to `tradingaz.azurecr.io`
   - Update Helm values with the image info
   - Copy `.env` into the Helm chart for ConfigMap injection
   - Deploy (or upgrade) the Helm release to your Kubernetes cluster

4. **Access the Service**
   - After deployment, get the external IP:
     ```sh
     kubectl get svc deep-research-mcp
     ```
   - The service will be available at `http://<EXTERNAL-IP>:8001/`

---

## Updating Environment Variables

- Edit your `.env` file as needed.
- Re-run `./deploy.sh` to update the ConfigMap and redeploy.

---

## Notes

- The Helm chart and deployment are validated to match the application’s requirements.
- For customizations (replicas, resources, ingress, etc.), edit the Helm chart as needed.
- For troubleshooting, check pod logs:
  ```sh
  kubectl logs deployment/deep-research-mcp
  ```

---

## License

MIT License (c) Microsoft Corporation
