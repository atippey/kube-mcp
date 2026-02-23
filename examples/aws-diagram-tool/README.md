# AWS Diagram Tool Example

This example demonstrates how to deploy an external MCP server (`mcp/aws-diagram`) using the `MCPServer` CRD.

The `aws-diagram` tool is an MCP server that generates AWS architecture diagrams using Python DSL.

## Overview

This example differs from others in that it uses the `MCPServer` CRD to deploy a 3rd party image directly, rather than using the default `mcp-server` aggregator. This showcases the operator's flexibility in managing external MCP servers.

**Note:** Because we are replacing the default aggregator image with `mcp/aws-diagram`, any `MCPTool` resources defined in Kubernetes will be ignored by this server (as it does not read the mounted `tools.json` config). Instead, the server exposes its own built-in tools.

## Prerequisites

- k3d cluster with `mcp-operator` installed.
- `kubectl` configured.

## Usage

1.  Apply the manifests:
    ```bash
    kubectl apply -k manifests/overlays/k3d
    ```

2.  Verify the deployment:
    ```bash
    kubectl get mcpserver aws-diagram -n mcp-system
    kubectl get pod -n mcp-system -l kubemcp.io/server=aws-diagram
    ```

3.  The server will be exposed via Ingress at `http://aws-diagram.kubemcp.io/sse` (or whatever the Ingress configuration maps to).

## Cleanup

```bash
kubectl delete -k manifests/overlays/k3d
```
