# MCP Kubernetes Operator

A Kubernetes operator for managing [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) servers, tools, prompts, and resources.

## Overview

This operator enables dynamic registration of MCP tools, prompts, and resources that are exposed via an MCP server running in Kubernetes. It uses label-based selection to automatically discover and configure MCP components.

## Features

- **MCPServer** - Deploy highly available MCP server pods with automatic scaling
- **MCPTool** - Register tools that proxy to Kubernetes services
- **MCPPrompt** - Define prompt templates with variable substitution
- **MCPResource** - Expose resources via HTTP operations or inline content
- **Label-based discovery** - MCPServer automatically finds components via label selectors
- **Redis-backed state** - Sessions, caching, and rate limiting

## Quick Start

### Prerequisites

- Kubernetes cluster (k3d, kind, or remote)
- kubectl configured
- Python 3.11+
- Poetry

### Installation

```bash
# Clone the repository
git clone https://github.com/yourorg/mcp-operator.git
cd mcp-operator

# Install dependencies
make dev

# Create a k3d cluster (optional, for local development)
make k3d-create

# Install CRDs
make k3d-crds

# Install Redis
make k3d-redis

# Run the operator locally
make run
```

### Deploy an Example

```yaml
# Create an MCP server that selects tools with label "mcp-server: main"
apiVersion: mcp.example.com/v1alpha1
kind: MCPServer
metadata:
  name: main
  namespace: mcp-system
spec:
  replicas: 2
  redis:
    serviceName: mcp-redis
  toolSelector:
    matchLabels:
      mcp-server: main
---
# Register a tool
apiVersion: mcp.example.com/v1alpha1
kind: MCPTool
metadata:
  name: github-search
  namespace: mcp-system
  labels:
    mcp-server: main
spec:
  name: github-search
  description: Search GitHub repositories
  service:
    name: github-tool-svc
    port: 8080
    path: /search
  inputSchema:
    type: object
    required: [query]
    properties:
      query:
        type: string
```

```bash
kubectl apply -f example.yaml
```

## Development

### Commands

```bash
make dev          # Install dependencies
make lint         # Run linter
make format       # Format code
make test         # Run unit tests (80% coverage required)
make test-fast    # Run tests without coverage
make check        # Run all checks (lint, format, typecheck)
make run          # Run operator locally
```

### k3d Cluster

```bash
make k3d-create   # Create local cluster
make k3d-crds     # Install CRDs
make k3d-redis    # Deploy Redis
make k3d-examples # Deploy example resources
make k3d-delete   # Tear down cluster
```

### Deployment

Using Kustomize overlays:

```bash
# Local k3d
make kustomize-k3d

# Production
make kustomize-prod
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP Operator                              │
├─────────────────────────────────────────────────────────────────┤
│  MCPServer Controller    MCPTool Controller                      │
│  MCPPrompt Controller    MCPResource Controller                  │
└───────────────┬─────────────────────────────────────────────────┘
                │ watches/creates
                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Kubernetes Resources                         │
├─────────────────────────────────────────────────────────────────┤
│  Deployment (MCP Server Pods)    Service    Ingress    ConfigMap │
└───────────────┬─────────────────────────────────────────────────┘
                │ connects to
                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Runtime                                  │
├─────────────────────────────────────────────────────────────────┤
│  Redis (sessions, cache, rate limits)    Backing Services        │
└─────────────────────────────────────────────────────────────────┘
```

## CRDs

| CRD | Description |
|-----|-------------|
| `MCPServer` | Deploys MCP server pods, manages ingress, selects tools/prompts/resources |
| `MCPTool` | Defines tools that reference Kubernetes services |
| `MCPPrompt` | Defines prompt templates with `{{variable}}` placeholders |
| `MCPResource` | Defines resources with HTTP operations or inline content |

## Configuration

### MCPServer

```yaml
spec:
  replicas: 3                    # Number of MCP server pods
  redis:
    serviceName: mcp-redis       # Redis service for state
  ingress:
    host: mcp.example.com        # Ingress hostname
    tlsSecretName: mcp-tls       # TLS secret
    pathPrefix: /mcp             # Base path
  toolSelector:
    matchLabels:
      mcp-server: main           # Select tools/prompts/resources
  config:
    requestTimeout: 30s
    maxConcurrentRequests: 100
```

### MCPTool

```yaml
spec:
  name: my-tool                  # Tool name (unique per server)
  description: Does something
  service:
    name: backend-svc            # K8s service to proxy to
    port: 8080
    path: /api/tool
  inputSchema: {}                # JSON Schema for validation
  method: POST                   # HTTP method
```

### MCPPrompt

```yaml
spec:
  name: my-prompt
  template: |
    Hello {{name}}, your query is: {{query}}
  variables:
    - name: name
      required: true
    - name: query
      default: "none"
```

### MCPResource

```yaml
# Service-backed resource
spec:
  name: docs
  operations:
    - method: GET
      ingressPath: /resources/docs/{id}
      service:
        name: docs-svc
        port: 8080
        path: /api/docs/{id}

# Inline content
spec:
  name: config-template
  content:
    uri: "config://template"
    mimeType: text/yaml
    text: |
      key: value
```

## License

MIT
