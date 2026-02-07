# Framework Feedback Report

## Developer Experience

### MCPTool CRD Authoring
The `MCPTool` Custom Resource Definition (CRD) provides a clear structure for defining tool capabilities. The `inputSchema` field, which leverages JSON Schema, is particularly powerful.
-   **Pros:** The ability to use `enum` in the `inputSchema` (as used for the `algorithm` field in this tool) makes input validation straightforward and declarative. This reduces the need for extensive validation logic within the tool implementation itself.
-   **Cons:** None encountered. The schema definition is intuitive for anyone familiar with OpenAPI or JSON Schema.

### Kustomize Pattern
The project's convention of using a `base` and `overlays` structure for Kustomize manifests is a robust pattern for managing environment-specific configurations.
-   **Clarity:** Separating the core resource definitions (`base`) from environment patches (`overlays/k3d`) keeps the configuration clean.
-   **Local Development:** The `k3d` overlay makes it easy to patch image registries for local development without modifying the source manifests, which is a significant friction reducer.

### Label Selectors
The mechanism for associating an `MCPTool` with an `MCPServer` via label selectors (`mcp-server: <name>`) is standard Kubernetes practice and works predictably. It allows for flexible decoupling of tools and servers.

## Friction Points
-   **Manifest Structure:** While the Kustomize pattern is powerful, ensuring all files are in the correct `base` vs `overlays` structure requires some initial boilerplate setup. A scaffold generator could speed this up for new tools.
-   **Registry Management:** Manually patching image names in the Kustomize overlay is necessary but can be a point of error if the local registry port or name changes.

## Suggestions
-   **Scaffolding Tool:** A CLI command or script to generate the initial directory structure (`manifests/base`, `manifests/overlays`, `Dockerfile`, `go.mod`) for a new example tool would improve the onboarding experience.
-   **Documentation:** Explicit documentation on the expected Go module naming convention and versioning (e.g., matching the Dockerfile Go version) would prevent common setup errors.
