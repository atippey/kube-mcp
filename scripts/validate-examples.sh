#!/usr/bin/env bash
set -euo pipefail

# Validate all example manifests against CRD schemas using kubeconform.
# Requires: kubeconform, kubectl (for kustomize build), .schemas/ generated

SCHEMA_DIR=".schemas"
FAILED=0
PASSED=0

validate() {
    local name="$1"
    local path="$2"

    if ! kubectl kustomize "$path" 2>/dev/null | \
        kubeconform -strict \
            -ignore-missing-schemas \
            -schema-location default \
            -schema-location "${SCHEMA_DIR}/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json" \
            -summary; then
        echo "  FAIL: $name"
        FAILED=$((FAILED + 1))
    else
        echo "  PASS: $name"
        PASSED=$((PASSED + 1))
    fi
}

echo "Validating example manifests..."
echo ""

# echo-server uses manifests/ directly (no base/overlays split)
validate "echo-server" "examples/echo-server/manifests/"

# All other examples use manifests/base/
for dir in examples/*/manifests/base/; do
    name=$(echo "$dir" | cut -d/ -f2)
    validate "$name" "$dir"
done

echo ""
echo "Results: ${PASSED} passed, ${FAILED} failed"

if [ "$FAILED" -gt 0 ]; then
    exit 1
fi
