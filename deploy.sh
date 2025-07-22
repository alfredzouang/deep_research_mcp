#!/bin/bash
set -e

# NOTE: Run this script as ./deploy.sh, not with 'sh deploy.sh'

# Check for yq dependency
if ! command -v yq >/dev/null 2>&1; then
  echo "Error: 'yq' is required but not installed. Please install yq (e.g., 'brew install yq' on Mac) and re-run this script."
  exit 1
fi

# Configurable variables
IMAGE_NAME="tradingaz.azurecr.io/deep-research-mcp"
RESOURCE_GROUP="trading"
USER_ASSIGNED_IDENTITY_NAME="azkubernetesdeepresearchidentity"
LOCATION="eastasia" # Change if needed

# Get git commit hash if available, else use timestamp
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  IMAGE_TAG=$(git rev-parse --short HEAD)
else
  IMAGE_TAG=$(date +%s)
fi

CHART_DIR="helm/deep-research-mcp"
RELEASE_NAME="deep-research-mcp"
NAMESPACE="default"

# 0. Ensure user-assigned managed identity exists
echo "Checking for user-assigned managed identity: $USER_ASSIGNED_IDENTITY_NAME in $RESOURCE_GROUP..."
IDENTITY_JSON=$(az identity show --resource-group "$RESOURCE_GROUP" --name "$USER_ASSIGNED_IDENTITY_NAME" 2>/dev/null || true)
if [ -z "$IDENTITY_JSON" ]; then
  echo "Identity not found. Creating user-assigned managed identity..."
  az identity create --resource-group "$RESOURCE_GROUP" --name "$USER_ASSIGNED_IDENTITY_NAME" --location "$LOCATION"
  IDENTITY_JSON=$(az identity show --resource-group "$RESOURCE_GROUP" --name "$USER_ASSIGNED_IDENTITY_NAME")
else
  echo "Identity already exists."
fi

USER_ASSIGNED_CLIENT_ID=$(echo "$IDENTITY_JSON" | yq e '.clientId' -)
echo "User Assigned Client ID: $USER_ASSIGNED_CLIENT_ID"

# Update Helm values.yaml with workloadIdentityClientId
yq e -i '.workloadIdentityClientId = "'"$USER_ASSIGNED_CLIENT_ID"'"' ${CHART_DIR}/values.yaml

# 1. Build multi-arch Docker image (arm64 for M1, amd64 for cross-platform)
echo "Building Docker image for amd64..."
docker buildx build --platform linux/amd64 \
  -t ${IMAGE_NAME}:${IMAGE_TAG} \
  -t ${IMAGE_NAME}:latest \
  --push .

# 2. Login to Azure Container Registry (requires az CLI)
echo "Logging in to Azure Container Registry..."
az acr login --name tradingaz

# 3. Update values.yaml with image info (optional: user can do this manually)
echo "Updating Helm values.yaml with image info..."
yq e -i '.image.repository = "'${IMAGE_NAME}'"' ${CHART_DIR}/values.yaml
yq e -i '.image.tag = "'${IMAGE_TAG}'"' ${CHART_DIR}/values.yaml

# 4. Convert .env to YAML and copy into chart directory for ConfigMap
echo "Converting .env to YAML for Helm ConfigMap..."
ENV_YAML_PATH="${CHART_DIR}/.env.yaml"
awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/{gsub(/^[ \t]+|[ \t]+$/, "", $1); gsub(/^[ \t]+|[ \t]+$/, "", $2); printf "%s: \"%s\"\n", $1, $2}' .env > "$ENV_YAML_PATH"

# 5. Deploy with Helm (upgrade if exists, install if not)
echo "Deploying to Kubernetes with Helm..."
helm upgrade --install ${RELEASE_NAME} ${CHART_DIR} --namespace ${NAMESPACE} --create-namespace

echo "Deployment complete."

# 6. Output MCP service URL
SERVICE_NAME="deep-research-mcp"
echo "Retrieving external IP for service: $SERVICE_NAME..."

EXTERNAL_IP=""
for i in {1..30}; do
  EXTERNAL_IP=$(kubectl get svc $SERVICE_NAME -n $NAMESPACE -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null)
  if [[ -n "$EXTERNAL_IP" ]]; then
    break
  fi
  echo "Waiting for external IP to be assigned... ($i/30)"
  sleep 5
done

if [[ -z "$EXTERNAL_IP" ]]; then
  echo "Error: External IP not assigned after waiting. Please check the service status."
else
  MCP_URL="http://$EXTERNAL_IP:8001/mcp"
  echo "MCP service is available at: $MCP_URL"
fi
