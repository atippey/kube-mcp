#!/usr/bin/env bash
set -euo pipefail

# MCP Tool Example Scaffold Generator
# Generates the complete file skeleton for a new MCP tool example.
#
# Usage:
#   ./scripts/scaffold-tool.sh --name my-tool --endpoint /convert --description "Converts formats"
#   ./scripts/scaffold-tool.sh --name my-tool --endpoint /convert --description "Converts formats" --rbac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Defaults
NAME=""
ENDPOINT=""
DESC="TODO: add description"
RBAC=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --name) NAME="$2"; shift 2 ;;
        --endpoint) ENDPOINT="$2"; shift 2 ;;
        --description) DESC="$2"; shift 2 ;;
        --rbac) RBAC=true; shift ;;
        -h|--help)
            echo "Usage: $0 --name <tool-name> [--endpoint /path] [--description \"desc\"] [--rbac]"
            echo ""
            echo "Options:"
            echo "  --name         Tool name in kebab-case (required)"
            echo "  --endpoint     HTTP endpoint path (default: /<name>)"
            echo "  --description  Tool description (default: TODO)"
            echo "  --rbac         Include ServiceAccount + ClusterRole + ClusterRoleBinding"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Validate name
if [[ -z "$NAME" ]]; then
    echo "Error: --name is required"
    echo "Usage: $0 --name <tool-name> [--endpoint /path] [--description \"desc\"] [--rbac]"
    exit 1
fi

if ! [[ "$NAME" =~ ^[a-z][a-z0-9-]*$ ]]; then
    echo "Error: name must be kebab-case (lowercase letters, numbers, hyphens), starting with a letter"
    exit 1
fi

# Default endpoint to /<name>
if [[ -z "$ENDPOINT" ]]; then
    ENDPOINT="/${NAME}"
fi

if ! [[ "$ENDPOINT" =~ ^/ ]]; then
    echo "Error: endpoint must start with /"
    exit 1
fi

# Check directory doesn't exist
TOOL_DIR="${PROJECT_ROOT}/examples/${NAME}"
if [[ -d "$TOOL_DIR" ]]; then
    echo "Error: ${TOOL_DIR} already exists"
    exit 1
fi

# Derive PascalCase endpoint name for Go identifiers
# /my-endpoint -> MyEndpoint
ENDPOINT_PATH="${ENDPOINT#/}"
ENDPOINT_NAME=""
IFS='-' read -ra PARTS <<< "$ENDPOINT_PATH"
for part in "${PARTS[@]}"; do
    ENDPOINT_NAME+="$(echo "${part:0:1}" | tr '[:lower:]' '[:upper:]')${part:1}"
done

echo "Scaffolding MCP tool example:"
echo "  Name:     ${NAME}"
echo "  Endpoint: ${ENDPOINT}"
echo "  Handler:  handle${ENDPOINT_NAME}"
echo "  RBAC:     ${RBAC}"
echo "  Output:   ${TOOL_DIR}"
echo ""

# Create directory structure
mkdir -p "${TOOL_DIR}/manifests/base"
mkdir -p "${TOOL_DIR}/manifests/overlays/k3d"

# --- main.go ---
cat > "${TOOL_DIR}/main.go" << GOEOF
package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
)

type ${ENDPOINT_NAME}Request struct {
	// TODO: Add request fields
	Input string \`json:"input"\`
}

type ${ENDPOINT_NAME}Response struct {
	// TODO: Add response fields
	Result string \`json:"result"\`
	Error  string \`json:"error,omitempty"\`
}

func main() {
	http.HandleFunc("/health", handleHealth)
	http.HandleFunc("${ENDPOINT}", handle${ENDPOINT_NAME})

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("Starting ${NAME} server on :%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
}

func handle${ENDPOINT_NAME}(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method != http.MethodPost {
		http.Error(w, \`{"error": "method not allowed"}\`, http.StatusMethodNotAllowed)
		return
	}

	var req ${ENDPOINT_NAME}Request
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(${ENDPOINT_NAME}Response{Error: "invalid request body"})
		return
	}

	// TODO: Implement your tool logic here
	resp := ${ENDPOINT_NAME}Response{
		Result: "not implemented",
	}

	json.NewEncoder(w).Encode(resp)
}
GOEOF

# --- go.mod ---
cat > "${TOOL_DIR}/go.mod" << MODEOF
module ${NAME}

go 1.25
MODEOF

# --- Dockerfile ---
cat > "${TOOL_DIR}/Dockerfile" << 'DOCKEOF'
FROM golang:1.25-alpine AS builder

WORKDIR /app

# Copy go mod files
COPY go.mod go.sum* ./
RUN go mod download

# Copy source
COPY *.go ./

# Build static binary
DOCKEOF

cat >> "${TOOL_DIR}/Dockerfile" << DOCKEOF
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /${NAME} .

# Final minimal image
FROM alpine:3.19

# Add ca-certificates for HTTPS
RUN apk add --no-cache ca-certificates

# Non-root user
RUN adduser -D -u 1000 appuser
USER appuser

COPY --from=builder /${NAME} /${NAME}

EXPOSE 8080

ENTRYPOINT ["/${NAME}"]
DOCKEOF

# --- manifests/base/namespace.yaml ---
cat > "${TOOL_DIR}/manifests/base/namespace.yaml" << 'NSEOF'
apiVersion: v1
kind: Namespace
metadata:
  name: mcp-test
NSEOF

# --- manifests/base/{NAME}-backend.yaml ---
if [[ "$RBAC" == "true" ]]; then
cat > "${TOOL_DIR}/manifests/base/${NAME}-backend.yaml" << BEEOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${NAME}
  namespace: mcp-test
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ${NAME}-reader
rules:
  # TODO: Update resources and verbs for your tool's needs
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ${NAME}-reader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: ${NAME}-reader
subjects:
  - kind: ServiceAccount
    name: ${NAME}
    namespace: mcp-test
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${NAME}
  namespace: mcp-test
  labels:
    app.kubernetes.io/name: ${NAME}
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: ${NAME}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ${NAME}
    spec:
      serviceAccountName: ${NAME}
      containers:
        - name: ${NAME}
          image: ghcr.io/atippey/${NAME}:latest
          ports:
            - containerPort: 8080
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
          resources:
            requests:
              memory: "64Mi"
              cpu: "100m"
            limits:
              memory: "128Mi"
              cpu: "200m"
---
apiVersion: v1
kind: Service
metadata:
  name: ${NAME}-svc
  namespace: mcp-test
  labels:
    app.kubernetes.io/name: ${NAME}
spec:
  selector:
    app.kubernetes.io/name: ${NAME}
  ports:
    - name: http
      port: 8080
      targetPort: 8080
      protocol: TCP
BEEOF
else
cat > "${TOOL_DIR}/manifests/base/${NAME}-backend.yaml" << BEEOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${NAME}
  namespace: mcp-test
  labels:
    app.kubernetes.io/name: ${NAME}
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: ${NAME}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ${NAME}
    spec:
      containers:
        - name: ${NAME}
          image: ghcr.io/atippey/${NAME}:latest
          ports:
            - containerPort: 8080
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
          resources:
            requests:
              memory: "64Mi"
              cpu: "100m"
            limits:
              memory: "128Mi"
              cpu: "200m"
---
apiVersion: v1
kind: Service
metadata:
  name: ${NAME}-svc
  namespace: mcp-test
  labels:
    app.kubernetes.io/name: ${NAME}
spec:
  selector:
    app.kubernetes.io/name: ${NAME}
  ports:
    - name: http
      port: 8080
      targetPort: 8080
      protocol: TCP
BEEOF
fi

# --- manifests/base/example-resources.yaml ---
cat > "${TOOL_DIR}/manifests/base/example-resources.yaml" << RESEOF
apiVersion: mcp.k8s.turd.ninja/v1alpha1
kind: MCPServer
metadata:
  name: ${NAME}
  namespace: mcp-test
spec:
  replicas: 1
  redis:
    serviceName: mcp-redis
  toolSelector:
    matchLabels:
      mcp-server: ${NAME}
---
apiVersion: mcp.k8s.turd.ninja/v1alpha1
kind: MCPTool
metadata:
  name: ${NAME}
  namespace: mcp-test
  labels:
    mcp-server: ${NAME}
spec:
  name: ${NAME}
  description: |
    ${DESC}
  service:
    name: ${NAME}-svc
    port: 8080
    path: ${ENDPOINT}
  inputSchema:
    type: object
    properties: {}
    # TODO: Define your tool's input properties and required fields
    # Example:
    #   properties:
    #     input:
    #       type: string
    #       description: "Describe this field"
    #   required:
    #     - input
  method: POST
RESEOF

# --- manifests/base/kustomization.yaml ---
cat > "${TOOL_DIR}/manifests/base/kustomization.yaml" << KUSTEOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - namespace.yaml
  - ${NAME}-backend.yaml
  - example-resources.yaml
KUSTEOF

# --- manifests/overlays/k3d/kustomization.yaml ---
cat > "${TOOL_DIR}/manifests/overlays/k3d/kustomization.yaml" << K3DEOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base

images:
  - name: ghcr.io/atippey/${NAME}
    newName: mcp-operator-registry:5000/${NAME}
    newTag: latest
K3DEOF

# Summary
echo "Created ${NAME} example:"
find "${TOOL_DIR}" -type f | sort | while read -r f; do
    echo "  ${f#${PROJECT_ROOT}/}"
done
echo ""
echo "Next steps:"
echo "  1. cd examples/${NAME} && go build -o ${NAME} ."
echo "  2. Implement your tool logic in main.go"
echo "  3. docker build -t localhost:5000/${NAME}:latest examples/${NAME}/"
echo "  4. docker push localhost:5000/${NAME}:latest"
echo "  5. kubectl apply -k examples/${NAME}/manifests/overlays/k3d/"
