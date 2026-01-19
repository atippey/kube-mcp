# Jules Tasks

Rote development tasks to be completed by Jules to save Claude tokens.

---

## Task 1: Change CRD FQDN from example.com to k8s.turd.ninja

**Status:** Pending

**Description:**
Replace all occurrences of `mcp.example.com` with `mcp.k8s.turd.ninja` across the codebase.

**Files to update:**
- `manifests/base/crds/mcpserver-crd.yaml`
- `manifests/base/crds/mcptool-crd.yaml`
- `manifests/base/crds/mcpprompt-crd.yaml`
- `manifests/base/crds/mcpresource-crd.yaml`
- `crd/mcpserver-crd.yaml`
- `crd/mcptool-crd.yaml`
- `crd/mcpprompt-crd.yaml`
- `crd/mcpresource-crd.yaml`
- `manifests/examples/test-resources.yaml`
- `crd/examples.yaml`
- `examples.yaml`
- Any test files that reference the CRD group

**Search pattern:** `mcp.example.com`
**Replace with:** `mcp.k8s.turd.ninja`

**Verification:**
```bash
# Should return no results after completion
grep -r "mcp.example.com" --include="*.yaml" --include="*.py"

# Should return multiple results
grep -r "mcp.k8s.turd.ninja" --include="*.yaml" --include="*.py"
```

---

## Task 2: Multi-architecture Docker builds (arm64 + amd64)

**Status:** Pending

**Description:**
Update the Docker build process to produce multi-architecture images supporting both `linux/arm64` and `linux/amd64`. This is needed because `ghul` cluster runs Intel (amd64) while local dev uses Apple Silicon (arm64).

**Requirements:**
1. Set up Docker buildx for multi-platform builds
2. Update Makefile to use buildx with `--platform linux/arm64,linux/amd64`
3. Push manifest list to GHCR that includes both architectures

**Example build command:**
```bash
docker buildx build --platform linux/arm64,linux/amd64 \
  -t ghcr.io/atippey/mcp-operator:dev \
  --push .
```

**Files to update:**
- `Makefile` - add buildx targets
- Optionally create a `docker-bake.hcl` for complex builds

**Verification:**
```bash
# Check manifest for both architectures
docker manifest inspect ghcr.io/atippey/mcp-operator:dev

# Should show both:
# - linux/arm64
# - linux/amd64
```

---

## Task 3: Add status subresource to CRDs

**Status:** Pending

**Description:**
The CRDs currently don't have the `status` subresource enabled, which prevents kopf from persisting status updates. Add the status subresource configuration to all four CRDs.

**Files to update:**
- `manifests/base/crds/mcpserver-crd.yaml`
- `manifests/base/crds/mcptool-crd.yaml`
- `manifests/base/crds/mcpprompt-crd.yaml`
- `manifests/base/crds/mcpresource-crd.yaml`
- `crd/mcpserver-crd.yaml`
- `crd/mcptool-crd.yaml`
- `crd/mcpprompt-crd.yaml`
- `crd/mcpresource-crd.yaml`

**Change required:**
Add this to each CRD under `spec.versions[].subresources`:

```yaml
spec:
  versions:
    - name: v1alpha1
      served: true
      storage: true
      subresources:
        status: {}  # <-- ADD THIS
      schema:
        # ... existing schema
```

**Verification:**
```bash
# After applying updated CRDs, check they have status subresource
kubectl get crd mcptools.mcp.k8s.turd.ninja -o jsonpath='{.spec.versions[0].subresources}'
# Should output: {"status":{}}

# Then verify status persists after reconciliation
kubectl annotate mcptool echo-tool -n mcp-test test=$(date +%s) --overwrite
kubectl get mcptool echo-tool -n mcp-test -o jsonpath='{.status}'
# Should show status fields like ready, conditions, etc.

**Agent Hint:**
After updating the YAML, Jules should check if the Makefile has a make apply-crds or similar target to update the cluster before running the kubectl verification.
```

---

## Task 4: (Reserved for future tasks)

**Status:** Pending

**Description:**
TBD

---
