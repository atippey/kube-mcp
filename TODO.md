# Enterprise-Readiness Goals for MCP Kubernetes Operator

## Current State Assessment

Project is **75-80% production-ready** with solid fundamentals:
- [x] All 4 controllers implemented (MCPServer, MCPTool, MCPPrompt, MCPResource)
- [x] Comprehensive Pydantic models with excellent validation
- [x] 80% test coverage enforced (1.73x test-to-code ratio)
- [x] CI/CD pipeline with GitHub Actions
- [x] Multi-arch Docker builds (amd64/arm64)
- [x] Kustomize deployment for dev/k3d/production
- [x] Type safety via mypy

---

## Phase 1: Fix Core Bug

- [x] **Cascading reconciliation** - Add kopf handlers to trigger MCPServer reconciliation when Tools/Prompts/Resources are deleted _(merged PR #30)_

---

## Phase 2: Observability

- [ ] **Prometheus metrics** - Add prometheus-client, expose /metrics endpoint
  - New file: `src/utils/metrics.py`
  - Metrics: reconciliation_total, reconciliation_errors, reconciliation_duration_seconds
  - Update Dockerfile to expose port 8080 for metrics

- [ ] **Health endpoints** - Add /healthz and /readyz
  - Can use kopf's built-in health server or add aiohttp

- [ ] **Structured logging** - Switch to JSON format logging
  - Configure kopf logging settings in main.py

---

## Phase 3: Security

- [ ] **Container scanning** - Add Trivy to CI workflow
- [ ] **Dependency scanning** - Add Dependabot config (`.github/dependabot.yml`)
- [ ] **NetworkPolicy** - Add manifest to restrict mcp-system traffic
- [ ] **SBOM generation** - Add to release workflow

---

## Phase 4: Helm Chart

- [ ] **Create chart** - `charts/mcp-operator/` with templates for all resources
- [ ] **Chart CI** - Add helm lint and helm template validation to workflow
- [ ] **Chart release** - Push to ghcr.io OCI registry on release

---

## Phase 5: Documentation

- [ ] **Troubleshooting Guide** - Common errors and debug steps
- [ ] **Production Guide** - Resource sizing, HA Redis, TLS setup
- [ ] **README badges** - CI status, coverage, version

---

## Phase 6: Demo Polish

- [ ] **Demo scenario** - End-to-end walkthrough script
- [ ] **README improvements** - Animated GIF or demo video link

---

## Priority Reference

| Priority | Goal | Effort | Impact |
|----------|------|--------|--------|
| P0 | Fix cascading reconciliation | Low | High (functional bug) |
| P0 | Add Prometheus metrics | Medium | High (enterprise requirement) |
| P0 | Add container/dependency scanning | Low | High (security checkbox) |
| P1 | Create Helm chart | Medium | High (enterprise deployment) |
| P1 | Add health endpoints | Low | Medium (operational) |
| P1 | Add NetworkPolicy | Low | Medium (security) |
| P1 | Add Troubleshooting Guide | Low | Medium (user experience) |
| P2 | Expand integration tests | Medium | Medium (confidence) |
| P2 | Add PodDisruptionBudget | Low | Low (resilience) |
| P2 | Demo video/GIF | Medium | High (LinkedIn appeal) |

---

---

## Dogfooding Feedback

Consolidated from Jules examples (time-tool PR #26, hash-tool PR #27, dns-tool PR #28).

### P0 — Silent Failures & Observability

- [x] **Status conditions on MCPServer and MCPTool** — Already implemented.
  MCPServer reports `toolCount`, `readyReplicas`, and a `Ready` condition. MCPTool validates service references and sets `ready: False` with condition if service resolution fails. Jules likely saw blank READY because the operator wasn't running during their tests.
  _Note: Verify CRD `additionalPrinterColumns` are wired correctly so `kubectl get` displays READY._

- [x] **Validate MCPTool service references** — Already implemented.
  MCPTool controller resolves the service endpoint and sets `ready: False` + condition on failure (`mcptool_controller.py:87-93`).

### P0 — CRD Design

- [ ] **Multi-tool support to reduce manifest boilerplate**
  Two MCPTools pointing at the same Service share everything except `name`, `path`, `description`, and `inputSchema`. A `tools:` list inside MCPServer or a multi-tool MCPTool would cut YAML significantly. Currently ~200 lines of manifests for two HTTP endpoints.
  _Source: crane-tool_

### P1 — Developer Experience

- [ ] **Scaffold generator for new tools**
  Create a CLI or script (`mcp-cli create tool <name>`) that generates boilerplate: `main.go`, `go.mod`, `Dockerfile`, `manifests/base/*`, `manifests/overlays/k3d/*`, MCPServer + MCPTool CRDs.
  _Sources: hash-tool, dns-tool_

- [ ] **Getting-started guide for tool authors**
  Document end-to-end flow from "I have an HTTP server" to "it's a registered MCP tool in the cluster". Include module naming conventions, Go version expectations, manifest structure.
  _Source: hash-tool_

### P2 — Kustomize & Manifests

- [ ] **Reduce overlay boilerplate for local dev**
  The k3d overlay only rewrites the image tag. Explore Makefile target, skaffold profile, or convention-based approach to make local dev zero-config.
  _Sources: time-tool, hash-tool_

- [ ] **Standardize example structure**
  Enforce consistent naming: module names, resource filenames (`example-resources.yaml`), Go versions, Dockerfile base images. Consider CI lint check.
  _Partially addressed in hash-tool and dns-tool PRs_

### P3 — Nice to Have

- [ ] **inputSchema external reference or codegen**
  Embedding JSON Schema in YAML is verbose. Explore optional support for referencing an external schema or generating inputSchema from code annotations.
  _Source: time-tool_

### Positive Feedback (preserve these patterns)

- CRD structure is clear and intuitive, especially `inputSchema` with JSON Schema
- Label selector pattern (MCPServer → MCPTool) is standard K8s and works predictably
- Kustomize base/overlays separation is clean and reusable
- Tool authors don't need to understand operator internals
- Reconciliation is reliable with no race conditions observed

---

## Verification Checklist

- [ ] Deploy to k3d with `make k3d-create && make k3d-deploy`
- [ ] Apply example resources and verify reconciliation
- [ ] Delete an MCPTool and verify MCPServer updates (after fix)
- [ ] Check Prometheus metrics endpoint at :8080/metrics
- [ ] Verify health endpoints respond correctly
- [ ] Run security scan with no critical/high findings
- [ ] Deploy via Helm chart to ghul cluster
- [ ] Run full integration test suite
