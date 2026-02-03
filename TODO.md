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

- [ ] **Cascading reconciliation** - Add kopf handlers to trigger MCPServer reconciliation when Tools/Prompts/Resources are deleted
  - Files: `src/controllers/mcptool_controller.py:146`, `mcpprompt_controller.py:158`, `mcpresource_controller.py:194`
  - Pattern: Use `kopf.adopt()` or watch for deletions and patch MCPServer

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

## Verification Checklist

- [ ] Deploy to k3d with `make k3d-create && make k3d-deploy`
- [ ] Apply example resources and verify reconciliation
- [ ] Delete an MCPTool and verify MCPServer updates (after fix)
- [ ] Check Prometheus metrics endpoint at :8080/metrics
- [ ] Verify health endpoints respond correctly
- [ ] Run security scan with no critical/high findings
- [ ] Deploy via Helm chart to ghul cluster
- [ ] Run full integration test suite
