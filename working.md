# MCP Operator - Development State

Last updated: 2026-01-18

## Current Phase: Phase 1 - Project Setup (COMPLETE)

### Phase 1 - Completed
- [x] Create project directory structure (src/, tests/, manifests/)
- [x] Create src/__init__.py and main.py entry point
- [x] Create controller stubs (mcpserver, mcptool, mcpprompt, mcpresource)
- [x] Create models/crds.py with Pydantic models
- [x] Create utils (k8s_client.py, redis_client.py)
- [x] Create test fixtures and empty test files
- [x] Create Kustomize base manifests
- [x] Create Kustomize overlays (dev, k3d, production)
- [x] Verify ruff lint and format pass
- [x] Verify tests pass (21 tests passing)

### Phase 2 - Not Started (Core Controllers)
- [ ] Implement MCPTool controller reconciliation logic
- [ ] Implement MCPPrompt controller reconciliation logic
- [ ] Implement MCPResource controller reconciliation logic
- [ ] Implement MCPServer controller reconciliation logic
- [ ] Add unit tests with 80%+ coverage

### Phase 3 - Not Started (MCP Server)
- [ ] Implement MCP server that runs in pods
- [ ] Redis integration for state
- [ ] Request routing logic
- [ ] Health checks

### Phase 4 - Not Started (Testing & Docs)
- [ ] Integration tests with testcontainers (microk8s or kind TBD)
- [ ] Comprehensive documentation
- [ ] Example manifests

## Project Structure Created

```
src/
├── __init__.py
├── main.py                    # kopf entry point
├── controllers/
│   ├── __init__.py
│   ├── mcpserver_controller.py   # stub with TODO
│   ├── mcptool_controller.py     # stub with TODO
│   ├── mcpprompt_controller.py   # stub with TODO
│   └── mcpresource_controller.py # stub with TODO
├── models/
│   ├── __init__.py
│   └── crds.py                # Pydantic models for all CRDs
└── utils/
    ├── __init__.py
    ├── k8s_client.py          # K8s API wrapper
    └── redis_client.py        # Redis client wrapper

tests/
├── __init__.py
├── conftest.py                # pytest fixtures
├── unit/
│   ├── __init__.py
│   ├── test_mcpserver_controller.py
│   ├── test_mcptool_controller.py
│   ├── test_mcpprompt_controller.py
│   └── test_mcpresource_controller.py
└── integration/
    └── __init__.py            # empty, TBD with testcontainers

manifests/
├── base/
│   ├── kustomization.yaml
│   ├── namespace.yaml
│   ├── operator.yaml
│   ├── redis.yaml
│   ├── crds/
│   │   ├── kustomization.yaml
│   │   ├── mcpserver-crd.yaml
│   │   ├── mcptool-crd.yaml
│   │   ├── mcpprompt-crd.yaml
│   │   └── mcpresource-crd.yaml
│   └── rbac/
│       ├── kustomization.yaml
│       ├── service-account.yaml
│       ├── cluster-role.yaml
│       └── cluster-role-binding.yaml
└── overlays/
    ├── dev/                   # skips operator deployment
    │   └── kustomization.yaml
    ├── k3d/                   # local registry image
    │   └── kustomization.yaml
    └── production/            # ghcr.io image
        └── kustomization.yaml
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `pyproject.toml` | Poetry + poethepoet config, Python >=3.11 |
| `Makefile` | Top-level orchestration (make dev, make test, etc.) |
| `scripts/k3d-cluster.sh` | k3d cluster management |
| `claude.md` | Claude-specific context and design decisions |

## Commands

```bash
# Setup
conda activate kube-mcp
make dev

# Development
make lint          # ruff check
make format        # ruff format
make test          # pytest with coverage
make test-fast     # pytest without coverage
make check         # lint + format-check + typecheck
make run           # kopf run locally

# k3d
make k3d-create
make k3d-crds
make k3d-redis
make k3d-examples
make k3d-delete

# Kustomize
make kustomize-k3d
make kustomize-prod
```

## Next Steps

Phase 1 is complete. Ready to begin Phase 2:
1. Implement MCPTool controller (simplest - validates service, resolves endpoint)
2. Implement MCPPrompt controller (validates template syntax)
3. Implement MCPResource controller (handles operations or inline content)
4. Implement MCPServer controller (orchestrates all, creates Deployment/Service/Ingress)
5. Add comprehensive unit tests to hit 80% coverage

## Design Decisions

- **kopf** for operator framework
- **Poetry + poethepoet** for Python dependency/task management
- **ruff** for linting and formatting (Black-compatible)
- **Kustomize** for K8s deployments (Helm later)
- **Simple Redis** (no operator) - users bring own HA Redis for prod
- **Label-based selection** - MCPServer finds tools/prompts/resources via labels
