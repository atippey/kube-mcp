# Dogfood Results: AWS Diagram Tool

## Goal
Verify the "ops-managed approved MCP servers" workflow by deploying the Docker Hub MCP server image `mcp/aws-diagram` into Kubernetes via `kube-mcp`.

## Approach
We initially considered two approaches:
1.  **Proxy Pattern:** Deploy `aws-diagram` as a backend service and use the standard `MCPServer` aggregator to proxy requests to it via `MCPTool`.
2.  **Direct Pattern:** Use the `MCPServer` CRD to deploy the `aws-diagram` image directly, replacing the default aggregator.

We chose the **Direct Pattern** because:
*   **Protocol Mismatch:** The default `mcp-server` aggregator expects backend tools to expose REST-like endpoints (HTTP POST with JSON body). `mcp/aws-diagram` is a standard MCP server that speaks the MCP protocol (JSON-RPC over SSE/Stdio). Proxying would require an intermediate adapter layer, which adds complexity.
*   **Schema Discovery:** `aws-diagram` is a dynamic server that lists its own tools. Defining static `MCPTool` CRDs with schemas would duplicate this information and be brittle. By running the server directly, clients can discover tools dynamically via the standard MCP protocol.

## Findings & Feedback

### 1. Missing Configuration for Custom Images (Fixed)
**Issue:** The `MCPServer` CRD allowed specifying a custom `image`, but lacked fields for `command`, `args`, and `env`. This made it impossible to run `mcp/aws-diagram` in SSE mode (which requires passing `--transport sse --port 8080` args) without modifying the operator code.
**Fix:** We enhanced the `MCPServer` CRD and Controller to support `command`, `args`, and `env` fields. This makes the operator much more flexible for hosting arbitrary MCP servers.

### 2. Aggregator Assumption
**Observation:** The operator's architecture heavily leans towards the "Aggregator" model (building an MCP server from K8s services). The "Federator" model (connecting existing MCP servers) is not yet natively supported.
**Suggestion:** Consider adding a `type: mcp-server` to `MCPTool` or a new CRD `MCPBackend` that tells the aggregator to proxy MCP protocol messages directly, handling handshake and tool discovery automatically.

### 3. Tool Registration for Direct Deployment
**Observation:** When using the Direct Pattern, `MCPTool` resources are effectively ignored because the custom image (e.g., `aws-diagram`) does not read the `tools.json` config file mounted by the operator.
**Impact:** This means `MCPServer` CRD acts purely as a Deployment/Service manager in this mode. While useful for "central hosting", it loses the dynamic tool management capabilities of the operator.
**Suggestion:** Update documentation to clarify that `MCPTool` resources only apply when using the default aggregator image (or an image that supports the `tools.json` contract).

## Verification
*   **Tests:** `make test-fast` passed.
*   **Linting:** `make check` passed (after fixing type hints in controller).
*   **Manifests:** Created `examples/aws-diagram-tool` with production-ready manifests using the new CRD fields.

## Conclusion
The dogfooding exercise was successful in identifying a gap in the `MCPServer` CRD (`args`/`env` support) and prompting a fix that significantly improves the operator's utility for hosting 3rd party MCP servers. The resulting example demonstrates a viable path for enterprise hosting of approved MCP servers.
