# DNS Tool Report

## Implementation Details
The DNS Tool is a Go application using the standard `net` and `net/http` packages. It provides a `/lookup` endpoint to query DNS records.

## Limitations
- **TTL Support:** The Go standard library `net` package does not expose the TTL (Time To Live) of DNS records. The response currently uses a hardcoded placeholder (`300`) to satisfy the output schema. A production version would require a third-party library like `github.com/miekg/dns`.

## MCP Operator Framework Feedback

### CRD Intuitiveness
Defining the `MCPTool` CRD was straightforward. mapping the `inputSchema` to the expected JSON payload of the tool was intuitive, especially with the `properties` and `required` fields clearly mirroring JSON Schema standards.

### Tool Selector & Label Matching
The `toolSelector` mechanism in the `MCPServer` resource is powerful but requires careful attention to labels.
- **Experience:** It was easy to set up, but I had to double-check that the `mcp-server: dns-tool` label on the `MCPTool` matched the `matchLabels` selector in the `MCPServer`.
- **Friction:** A mismatch here fails silently (the tool just doesn't get picked up), which could be improved with some status feedback on the `MCPServer` resource indicating "0 tools found" or similar if the selector matches nothing.

### Kustomize Pattern
The `base` and `overlays` pattern works well for separating the core resource definitions from environment-specific configurations (like the k3d image registry rewrite). It keeps the manifests clean and reusable.

### Reconciliation
Reconciliation appeared to work as expected. Once the resources were applied, the operator (assumed) picked them up. I did not encounter any race conditions or errors during the manifest creation process.

### Developer Experience (DX)
Going from a raw Go HTTP server to a registered MCP tool was a smooth process.
- **Pros:** The abstraction is clean. I didn't need to write any operator code or understand the internal reconciliation loop. I just needed to describe *what* my tool is and *where* it lives.
- **Cons:** The boilerplate for the manifests is a bit verbose (Deployment + Service + MCPServer + MCPTool). A CLI tool or scaffold generator (`mcp-cli create tool`) would significantly speed up this initial setup phase.
