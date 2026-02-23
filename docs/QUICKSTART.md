# Quickstart: kube-mcp on k3d

Deploy a working MCP server with tools, prompts, and resources on a local k3d cluster.

## Prerequisites

| Tool | Install |
|------|---------|
| [Docker](https://docs.docker.com/get-docker/) | Must be running |
| [k3d](https://k3d.io/) | `brew install k3d` or `make setup-k3d` |
| [kubectl](https://kubernetes.io/docs/tasks/tools/) | `brew install kubectl` |
| [Conda](https://docs.conda.io/) | For operator dev mode |

## 1. Create the cluster

```bash
make k3d-create
```

This creates a k3d cluster (`mcp-operator`) with 1 server node, 2 agent nodes, a local registry at `localhost:5000`, and port-forwards `localhost:8080` to the cluster's ingress.

Verify it's running:

```bash
make k3d-status
```

## 2. Install CRDs and Redis

```bash
make k3d-crds
make k3d-redis
```

This installs the four CRDs (`MCPServer`, `MCPTool`, `MCPPrompt`, `MCPResource`) and deploys a single-replica Redis in the `mcp-system` namespace.

## 3. Run the operator

```bash
conda activate kube-mcp
make run
```

The operator starts in dev mode (kopf standalone), running on your host and talking to the k3d cluster. Leave this terminal open.

## 4. Deploy the echo-server example

In a new terminal:

```bash
kubectl apply -k examples/echo-server/manifests/
```

This deploys:

| Resource | Name | What it does |
|----------|------|-------------|
| **Namespace** | `mcp-test` | Isolated namespace for the example |
| **Deployment + Service** | `echo-backend` | Simple HTTP echo backend (hashicorp/http-echo) |
| **MCPServer** | `echo` | MCP server that aggregates tools/prompts/resources via label selector `mcp-server: echo` |
| **MCPTool** | `echo-tool` | Echoes back input — points to the echo-backend Service |
| **MCPTool** | `calculator-tool` | Basic math operations — same backend |
| **MCPPrompt** | `greeting-prompt` | Template with `{{name}}`, `{{date}}`, `{{topic}}` variables |
| **MCPPrompt** | `code-review-prompt` | Code review template with `{{language}}` and `{{code}}` |
| **MCPResource** | `sample-config` | Inline JSON configuration |
| **MCPResource** | `readme` | Inline Markdown documentation |

## 5. Verify it works

Check that the operator reconciled everything:

```bash
# CRDs
kubectl get mcpservers -n mcp-test
kubectl get mcptools -n mcp-test
kubectl get mcpprompts -n mcp-test
kubectl get mcpresources -n mcp-test

# Generated resources
kubectl get deployment,service,configmap -n mcp-test -l app.kubernetes.io/instance=echo

# Pods should be Running
kubectl get pods -n mcp-test
```

The operator creates a Deployment, Service, and ConfigMap for the `echo` MCPServer. The ConfigMap contains the aggregated tool/prompt/resource configuration, mounted into the MCP server pod.

## 6. Deploy a third-party MCP server (Direct Pattern)

Not all MCP servers need tool backends. Some (like `mcp/aws-diagram`) are self-contained — the operator just needs to run them with the right args and env:

```bash
kubectl apply -k examples/aws-diagram-tool/manifests/base/
```

The MCPServer CR uses `image`, `args`, and `env` to configure the container directly:

```yaml
apiVersion: kubemcp.io/v1alpha1
kind: MCPServer
metadata:
  name: aws-diagram
  namespace: mcp-system
spec:
  replicas: 1
  image: mcp/aws-diagram:latest
  args:
    - "--transport"
    - "sse"
    - "--port"
    - "8080"
    - "--host"
    - "0.0.0.0"
  env:
    - name: FASTMCP_LOG_LEVEL
      value: "ERROR"
  redis:
    serviceName: mcp-redis
  ingress:
    host: aws-diagram.kubemcp.io
    pathPrefix: /sse
  toolSelector:
    matchLabels:
      mcp-server: aws-diagram
```

The `env` field also supports `valueFrom` for referencing Secrets and ConfigMaps:

```yaml
env:
  - name: API_KEY
    valueFrom:
      secretKeyRef:
        name: my-secret
        key: api-key
```

## 7. Explore more examples

| Example | Description |
|---------|-------------|
| [echo-server](../examples/echo-server/) | Simple echo backend — the "hello world" of kube-mcp |
| [hash-tool](../examples/hash-tool/) | Cryptographic hash generation (md5, sha1, sha256, sha512) |
| [time-tool](../examples/time-tool/) | Timezone-aware time formatting |
| [weather-tool](../examples/weather-tool/) | Weather information via external API |
| [dns-tool](../examples/dns-tool/) | DNS lookup tool |
| [kubectl-explain](../examples/kubectl-explain/) | Kubernetes resource explanation |
| [kube-info-tool](../examples/kube-info-tool/) | Kubernetes cluster information |
| [act-tool](../examples/act-tool/) | GitHub Actions local runner (nektos/act) |
| [crane-tool](../examples/crane-tool/) | Container image registry tool |
| [compliance-tool](../examples/compliance-tool/) | FIPS, STIG, FedRAMP compliance checking |
| [aws-diagram-tool](../examples/aws-diagram-tool/) | AWS architecture diagram generator (Direct Pattern) |

Each example follows the same structure: backend Deployment/Service + MCP CRDs in `manifests/`.

## 8. In-cluster deployment

To run the operator inside the cluster instead of on your host:

```bash
# Build the operator image and push to the local k3d registry
make k3d-build

# Deploy operator + RBAC + Redis via Kustomize
make k3d-deploy
```

Or use Kustomize directly:

```bash
kubectl apply -k manifests/overlays/k3d
```

## 9. Cleanup

```bash
# Delete example resources
kubectl delete -k examples/echo-server/manifests/

# Delete the cluster entirely
make k3d-delete
```

## Next steps

- **[CLAUDE.md](../CLAUDE.md)** — Full development guide, project structure, and architecture
- **[manifests/base/crds/](../manifests/base/crds/)** — CRD schemas for all four resource types
- **[manifests/overlays/production/](../manifests/overlays/production/)** — Production deployment with hardened NetworkPolicy and resource limits
- **[GIT_STRATEGY.md](GIT_STRATEGY.md)** — Branching and release workflow
