# Enterprise-Readiness Goals for MCP Kubernetes Operator

## Current State Assessment

Project is **~85% production-ready** with solid fundamentals:
- [x] All 4 controllers implemented (MCPServer, MCPTool, MCPPrompt, MCPResource)
- [x] Comprehensive Pydantic models with excellent validation
- [x] 91% test coverage (80% enforced, 1.73x test-to-code ratio)
- [x] CI/CD pipeline with GitHub Actions (lint, typecheck, test, build, scan)
- [x] Alpine multi-stage Docker builds with GHCR publish
- [x] Kustomize deployment for dev/k3d/production
- [x] Type safety via mypy
- [x] Dependabot for dependency updates

---

## Phase 1: Fix Core Bug

- [x] **Cascading reconciliation** - Add kopf handlers to trigger MCPServer reconciliation when Tools/Prompts/Resources are deleted _(merged PR #30)_

---

## Phase 2: Observability

- [x] **Prometheus metrics** - prometheus-client on :9090, reconciliation_total/duration/errors counters _(merged PR #32)_
- [x] **Health endpoints** - kopf liveness probe on :8080/healthz _(merged PR #32)_
- [x] **Structured logging** - JSON format via python-json-logger _(merged PR #32)_

---

## Phase 3: Security — Complete

- [x] **Container scanning** - Trivy in CI, report-only until `kubernetes` client upgrades `urllib3 >=2.0` _(merged PR #37, #39)_
- [x] **Dependency scanning** - Dependabot for pip and GitHub Actions _(merged PR #37)_
- [x] **NetworkPolicy** - Controller-managed per-MCPServer egress, restrictive base manifests _(merged PR #36)_
- [x] **SBOM generation** - SPDX JSON via anchore/sbom-action for both images, runs on all builds _(merged PR #52)_
- [x] **Alpine slim image** - Multi-stage Dockerfile, non-root user, pip/setuptools stripped _(merged PR #39)_

---

## Phase 4: Helm Chart

- [ ] **Create chart** - `charts/mcp-operator/` with templates for all resources
- [ ] **Chart CI** - Add helm lint and helm template validation to workflow
- [ ] **Chart release** - Push to ghcr.io OCI registry on release

---

## Phase 5: Domain Migration & Documentation

- [x] **Migrate API group to kubemcp.io** - Replace `mcp.k8s.turd.ninja` with `kubemcp.io` across CRDs, controllers, models, manifests, RBAC, tests, Helm chart, and docs
- [ ] **Set up kubemcp.io docs site** - K8s-style docs with schema reference, concept pages, and task walkthroughs (MkDocs Material)
- [ ] **Update all repo references** - README, CLAUDE.md, AGENTS.md, examples, dogfood-ideas.md
- [ ] **Troubleshooting Guide** - Common errors and debug steps
- [ ] **Production Guide** - Resource sizing, HA Redis, TLS setup
- [ ] **README badges** - CI status, coverage, version

---

## Phase 6: Post-MVP Hardening _(from Codex dogfooding review, PR #54)_

### P0 — Safety & Correctness

- [ ] **CRD validation webhooks** - Reject invalid CRs at admission time instead of relying on convention (label matching, service references, endpoint existence). Fail loudly on bad input.
- [ ] **Service reference validation at admission** - Validate that referenced services exist and have matching ports before accepting MCPTool CRs. Currently correctness relies on reconcile-time checks.
- [ ] **Schema duplication elimination** - inputSchema is duplicated between CRD OpenAPI spec and Pydantic models. Single source of truth with codegen.
- [ ] **Label selector guardrails** - Warn or reject MCPServer CRs with selectors that match zero tools, or tools with labels that match no server.

### P1 — Observability & Diagnostics

- [ ] **Richer status conditions** - Surface more actionable diagnostics in CR status (e.g., "Service X not found in namespace Y", "0 tools matched selector Z")
- [ ] **Event emission** - Emit Kubernetes Events on reconcile errors, service resolution failures, and NetworkPolicy updates for `kubectl describe` visibility
- [ ] **Operator dashboard** - Grafana dashboard template for reconciliation metrics, error rates, tool counts

### P2 — Developer Experience

- [ ] **Reduce authoring friction** - Verbose manifests and manual service/tool wiring are the top UX complaint. Explore convention-over-configuration defaults (auto-detect port, infer service name from tool name).
- [ ] **CRD scaffolding improvements** - Extend scaffold generator to also produce `.compliance.yaml`, test fixtures, and k3d overlay

---

## Phase 7: Demo Polish

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

Consolidated from Jules examples (time-tool PR #26, hash-tool PR #27, dns-tool PR #28) and Codex compliance-tool review (PR #54).

### Codex OSS MVP Assessment _(PR #54)_

**Strengths**: Clean CRD model, K8s-native label/selector composition, good dogfooding ergonomics, multi-tool support, Redis-backed HA design.

**Weaknesses**: Authoring friction (verbose manifests, schema duplication, manual wiring), safety relying on convention, observability/diagnostics gaps, some permissive defaults in examples.

**Verdict**: OSS MVP-ready. Biggest next step is UX and guardrails, not architecture changes. See Phase 6 above.

### P0 — Silent Failures & Observability

- [x] **Status conditions on MCPServer and MCPTool** — Already implemented.
  MCPServer reports `toolCount`, `readyReplicas`, and a `Ready` condition. MCPTool validates service references and sets `ready: False` with condition if service resolution fails. Jules likely saw blank READY because the operator wasn't running during their tests.
  _Note: Verify CRD `additionalPrinterColumns` are wired correctly so `kubectl get` displays READY._

- [x] **Validate MCPTool service references** — Already implemented.
  MCPTool controller resolves the service endpoint and sets `ready: False` + condition on failure (`mcptool_controller.py:87-93`).

### P0 — CRD Design

- [x] **Multi-tool support to reduce manifest boilerplate** _(merged PR #35)_
  MCPTool now supports `spec.tools[]` array for multiple tool definitions sharing one service.
  CRD enforces `oneOf` (name vs tools). MCPServer controller expands multi-tool CRs into individual ConfigMap entries.

### P1 — Developer Experience

- [x] **Scaffold generator for new tools** _(merged PR #31)_
  `scripts/scaffold-tool.sh` generates Go boilerplate, Dockerfile, Kustomize manifests, and MCPTool CRD.

- [ ] **Getting-started guide for tool authors**
  Document end-to-end flow from "I have an HTTP server" to "it's a registered MCP tool in the cluster". Include module naming conventions, Go version expectations, manifest structure.
  _Source: hash-tool_

### P2 — Kustomize & Manifests

- [ ] **Reduce overlay boilerplate for local dev**
  The k3d overlay only rewrites the image tag. Explore Makefile target, skaffold profile, or convention-based approach to make local dev zero-config.
  _Sources: time-tool, hash-tool_

- [ ] **Standardize example structure**
  Enforce consistent naming: module names, resource filenames (`example-resources.yaml`), Go versions, Dockerfile base images. Consider CI lint check.

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
