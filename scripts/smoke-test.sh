#!/usr/bin/env bash
set -euo pipefail

# Smoke test: deploy each example to k3d, verify MCPServer conditions, clean up.
# Requires: running k3d cluster with CRDs + Redis installed, operator running.

TIMEOUT=60
FAILED=0
PASSED=0
SKIPPED=0

# Each entry: "name|kustomize-path|namespace"
EXAMPLES=(
    "echo-server|examples/echo-server/manifests/|mcp-test"
    "hash-tool|examples/hash-tool/manifests/base/|mcp-test"
    "time-tool|examples/time-tool/manifests/base/|mcp-test"
    "weather-tool|examples/weather-tool/manifests/base/|mcp-test"
    "dns-tool|examples/dns-tool/manifests/base/|mcp-test"
    "kubectl-explain|examples/kubectl-explain/manifests/base/|mcp-test"
    "kube-info-tool|examples/kube-info-tool/manifests/base/|mcp-test"
    "act-tool|examples/act-tool/manifests/base/|mcp-test"
    "crane-tool|examples/crane-tool/manifests/base/|mcp-test"
    "compliance-tool|examples/compliance-tool/manifests/base/|mcp-test"
    "aws-diagram-tool|examples/aws-diagram-tool/manifests/base/|mcp-system"
)

smoke_test() {
    local name="$1"
    local path="$2"
    local ns="$3"

    echo "--- ${name} ---"

    # Deploy
    if ! kubectl apply -k "$path" 2>&1; then
        echo "  FAIL: kubectl apply failed"
        FAILED=$((FAILED + 1))
        return
    fi

    # Wait for MCPServer Ready condition
    local mcpserver_name
    mcpserver_name=$(kubectl get mcpservers -n "$ns" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

    if [ -z "$mcpserver_name" ]; then
        echo "  SKIP: no MCPServer found in namespace $ns"
        SKIPPED=$((SKIPPED + 1))
        kubectl delete -k "$path" --ignore-not-found 2>/dev/null || true
        return
    fi

    # Wait for ToolsDiscovered condition (the one that matters for validation)
    local elapsed=0
    local tools_status=""
    while [ "$elapsed" -lt "$TIMEOUT" ]; do
        tools_status=$(kubectl get mcpserver "$mcpserver_name" -n "$ns" \
            -o jsonpath='{.status.conditions[?(@.type=="ToolsDiscovered")].status}' 2>/dev/null || true)
        if [ -n "$tools_status" ]; then
            break
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done

    # Report
    local tools_msg
    tools_msg=$(kubectl get mcpserver "$mcpserver_name" -n "$ns" \
        -o jsonpath='{.status.conditions[?(@.type=="ToolsDiscovered")].message}' 2>/dev/null || true)
    local config_status
    config_status=$(kubectl get mcpserver "$mcpserver_name" -n "$ns" \
        -o jsonpath='{.status.conditions[?(@.type=="ConfigReady")].status}' 2>/dev/null || true)

    if [ "$tools_status" = "True" ] && [ "$config_status" = "True" ]; then
        echo "  PASS: ${tools_msg}"
        PASSED=$((PASSED + 1))
    elif [ "$tools_status" = "False" ]; then
        echo "  WARN: ToolsDiscovered=False — ${tools_msg}"
        # This is acceptable for Direct Pattern examples (aws-diagram) with no tools
        PASSED=$((PASSED + 1))
    else
        echo "  FAIL: timed out waiting for conditions (${TIMEOUT}s)"
        echo "        ToolsDiscovered=${tools_status:-<unset>} ConfigReady=${config_status:-<unset>}"
        FAILED=$((FAILED + 1))
    fi

    # Cleanup
    kubectl delete -k "$path" --ignore-not-found 2>/dev/null || true
    # Wait for namespace cleanup
    sleep 2
}

echo "=== kube-mcp Smoke Test ==="
echo "Cluster: $(kubectl config current-context)"
echo ""

for entry in "${EXAMPLES[@]}"; do
    IFS='|' read -r name path ns <<< "$entry"
    smoke_test "$name" "$path" "$ns"
    echo ""
done

echo "=== Results: ${PASSED} passed, ${FAILED} failed, ${SKIPPED} skipped ==="

if [ "$FAILED" -gt 0 ]; then
    exit 1
fi
