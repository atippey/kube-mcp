# Time Tool Report

## Implementation Details
The time-tool is a Go application using `net/http` to provide time in various timezones and formats.
It uses `alpine` base image with `tzdata` installed to support timezone loading.

## Framework Feedback & Friction Points

### 1. Kustomize Overlay Complexity
- The pattern of having `manifests/base` and `manifests/overlays/k3d` works, but rewriting the image tag in `kustomization.yaml` for local development feels slightly brittle.
- **Suggestion**: Could the operator or a dev tool helper automatically handle image references for local development to reduce boilerplate in `overlays/k3d`?

### 2. MCPTool CRD Authoring
- Defining the `inputSchema` in the `MCPTool` CRD is straightforward but verbose, especially since it requires embedding JSON schema within YAML.
- **Suggestion**: It would be helpful if the `inputSchema` could optionally reference an external file or be generated from the code, although that might be out of scope for the operator itself.

### 3. Service & Tool Linking
- The linkage between `MCPTool` and the backend `Service` (via `service.name`) is manual. If the Service name changes, the Tool breaks silently until runtime.
- **Suggestion**: Validating admission webhook or status condition on the `MCPTool` to warn if the referenced Service doesn't exist in the same namespace.

### 4. Label Selection
- The `MCPServer` selecting tools via `toolSelector` (labels) is a standard Kubernetes pattern and worked intuitively. However, managing matching labels across multiple files (`example-resources.yaml`) requires discipline to avoid typos.

## Bugs Encountered
- **Docker Rate Limiting**: Encountered `toomanyrequests` from Docker Hub when attempting to build the image in the development environment. This is an environment issue rather than a framework issue, but it impacts the "getting started" experience for new tool developers.
