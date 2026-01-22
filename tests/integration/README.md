# Integration Tests

This directory contains end-to-end integration tests for the MCP Operator using `testcontainers-python` and `k3s`.

## Prerequisites

*   Docker (must be running)
*   Python 3.11+
*   Poetry

## Running Tests

To run the integration tests:

```bash
make test-integration
# or
poetry run poe test-integration
```

## Structure

*   `conftest.py`: Defines the `k3s_cluster` and `operator` fixtures. It spins up a K3s container, installs CRDs and Redis, and runs the operator in a subprocess.
*   `test_mcpserver_e2e.py`: Contains lifecycle tests for `MCPServer` and the Echo Server integration scenario.
*   `test_aggregation.py`: Verifies that adding tools/prompts/resources updates the `MCPServer` ConfigMap.

## Notes

*   Tests require Docker to be available. If Docker is not found or permission is denied, tests will be skipped automatically.
*   The K3s container takes a few seconds to start.
*   The tests verify that the operator correctly creates Kubernetes resources (Deployments, Services, ConfigMaps) and updates status.
