import contextlib
import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from kubernetes import client, config, utils
from testcontainers.k3s import K3SContainer

# Define the image to use
K3S_IMAGE = "rancher/k3s:v1.27.1-k3s1"


@pytest.fixture(scope="session")
def k3s_cluster():
    """Starts a K3s cluster using testcontainers."""
    k3s = None
    kube_config_path = None
    try:
        k3s = K3SContainer(image=K3S_IMAGE)
        k3s.start()

        # Get kubeconfig content
        kubeconfig_yaml = k3s.config_yaml()

        # Write to temp file
        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".yaml") as f:
            f.write(kubeconfig_yaml)
            kube_config_path = f.name

        # Set KUBECONFIG environment variable for subprocesses (operator)
        os.environ["KUBECONFIG"] = kube_config_path

        # Load config for the python client in this process
        config.load_kube_config(config_file=kube_config_path)

        yield k3s

    except Exception as e:
        pytest.skip(f"Could not start K3s container (Docker required): {e}")
    finally:
        if k3s:
            with contextlib.suppress(Exception):
                k3s.stop()
        if kube_config_path and os.path.exists(kube_config_path):
            os.remove(kube_config_path)


@pytest.fixture(scope="session")
def k8s_client(k3s_cluster):
    """Returns a configured Kubernetes client."""
    return client.ApiClient()


@pytest.fixture(scope="session")
def setup_cluster(k3s_cluster, k8s_client):
    """Installs CRDs and base dependencies (Redis)."""
    k8s_api = client.CoreV1Api(k8s_client)

    # Create mcp-system namespace (for Redis)
    try:
        k8s_api.create_namespace(
            body=client.V1Namespace(metadata=client.V1ObjectMeta(name="mcp-system"))
        )
    except client.exceptions.ApiException as e:
        if e.status != 409:  # Conflict/AlreadyExists
            raise

    # Create mcp-test namespace (for tests)
    try:
        k8s_api.create_namespace(
            body=client.V1Namespace(metadata=client.V1ObjectMeta(name="mcp-test"))
        )
    except client.exceptions.ApiException as e:
        if e.status != 409:
            raise

    # Root of the repo
    root_dir = Path(__file__).parents[2]

    # Install CRDs
    crds_dir = root_dir / "manifests/base/crds"
    for crd_file in crds_dir.glob("*.yaml"):
        # print(f"Applying {crd_file}")
        with contextlib.suppress(utils.FailToCreateError):
            utils.create_from_yaml(k8s_client, str(crd_file))

    # Install Redis
    redis_file = root_dir / "manifests/base/redis.yaml"
    # print(f"Applying {redis_file}")
    utils.create_from_yaml(k8s_client, str(redis_file))

    # Wait a bit for CRDs to be ready
    time.sleep(2)

    return k8s_client


@pytest.fixture(scope="session")
def operator(setup_cluster):
    """Runs the MCP operator in a subprocess."""
    # We run kopf in standalone mode
    # Assuming we are at repo root when running pytest, or we need to find src/main.py
    root_dir = Path(__file__).parents[2]
    main_py = root_dir / "src/main.py"

    cmd = [
        "poetry",
        "run",
        "kopf",
        "run",
        str(main_py),
        "--standalone",
        "--all-namespaces",  # Monitor all namespaces
        # "--verbose"
    ]

    # Start the operator
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ.copy(),  # Inherits KUBECONFIG
        text=True,
    )

    # Give it a moment to start
    time.sleep(5)

    if process.poll() is not None:
        stdout, stderr = process.communicate()
        raise RuntimeError(f"Operator failed to start:\nSTDOUT: {stdout}\nSTDERR: {stderr}")

    yield process

    # Teardown
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
