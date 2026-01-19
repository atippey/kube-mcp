#!/bin/bash
# k3d Cluster Management Script for MCP Operator

set -e

CLUSTER_NAME="mcp-operator"
CONFIG_FILE="k3d-config.yaml"

function create_cluster() {
    echo "Creating k3d cluster: ${CLUSTER_NAME}..."
    k3d cluster create --config ${CONFIG_FILE}
    echo "Cluster created successfully!"
    echo ""
    echo "Registry available at: localhost:5000"
    echo "MCP Server accessible via: localhost:8080"
}

function delete_cluster() {
    echo "Deleting k3d cluster: ${CLUSTER_NAME}..."
    k3d cluster delete ${CLUSTER_NAME}
    echo "Cluster deleted successfully!"
}

function start_cluster() {
    echo "Starting k3d cluster: ${CLUSTER_NAME}..."
    k3d cluster start ${CLUSTER_NAME}
    echo "Cluster started successfully!"
}

function stop_cluster() {
    echo "Stopping k3d cluster: ${CLUSTER_NAME}..."
    k3d cluster stop ${CLUSTER_NAME}
    echo "Cluster stopped successfully!"
}

function status() {
    echo "k3d clusters:"
    k3d cluster list
    echo ""
    echo "kubectl context:"
    kubectl config current-context
    echo ""
    echo "Nodes:"
    kubectl get nodes
}

function install_crds() {
    echo "Installing MCP CRDs..."
    kubectl apply -f manifests/crds/
    echo "CRDs installed successfully!"
}

function install_redis() {
    echo "Installing Redis..."
    kubectl create namespace mcp-system --dry-run=client -o yaml | kubectl apply -f -
    kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-redis
  namespace: mcp-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcp-redis
  template:
    metadata:
      labels:
        app: mcp-redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-redis
  namespace: mcp-system
spec:
  selector:
    app: mcp-redis
  ports:
  - port: 6379
    targetPort: 6379
EOF
    echo "Redis installed successfully!"
}

function build_and_push() {
    echo "Building and pushing operator image to local registry..."
    docker build -t localhost:5000/mcp-operator:latest .
    docker push localhost:5000/mcp-operator:latest
    echo "Image built and pushed successfully!"
}

function deploy_operator() {
    echo "Deploying MCP Operator to k3d cluster..."
    kubectl apply -f manifests/rbac/
    kubectl apply -f manifests/operator-deployment.yaml
    echo "Operator deployment complete!"
}

function run_local() {
    echo "Running operator locally (dev mode)..."
    kopf run --standalone src/main.py
}

function deploy_examples() {
    echo "Deploying example resources..."
    kubectl apply -f crd/examples.yaml
    echo "Examples deployed!"
}

function logs() {
    COMPONENT=${1:-operator}
    echo "Showing logs for ${COMPONENT}..."
    case ${COMPONENT} in
        operator)
            kubectl logs -l app=mcp-operator -n mcp-system --tail=100 -f
            ;;
        redis)
            kubectl logs -l app=mcp-redis -n mcp-system --tail=100 -f
            ;;
        server)
            kubectl logs -l app=mcp-server -n mcp-system --tail=100 -f
            ;;
        *)
            echo "Unknown component: ${COMPONENT}"
            echo "Valid components: operator, redis, server"
            ;;
    esac
}

function help() {
    echo "k3d Cluster Management for MCP Operator"
    echo ""
    echo "Usage: ./k3d-cluster.sh [command]"
    echo ""
    echo "Commands:"
    echo "  create        Create the k3d cluster"
    echo "  delete        Delete the k3d cluster"
    echo "  start         Start the cluster"
    echo "  stop          Stop the cluster"
    echo "  status        Show cluster status"
    echo "  crds          Install MCP CRDs"
    echo "  redis         Install Redis in cluster"
    echo "  build         Build and push operator image to local registry"
    echo "  deploy        Deploy operator to cluster"
    echo "  run-local     Run operator locally (dev mode with kopf)"
    echo "  examples      Deploy example MCP resources"
    echo "  logs [comp]   Show logs (operator, redis, server)"
    echo "  help          Show this help message"
    echo ""
    echo "Example workflow:"
    echo "  ./k3d-cluster.sh create"
    echo "  ./k3d-cluster.sh crds"
    echo "  ./k3d-cluster.sh redis"
    echo "  ./k3d-cluster.sh run-local   # Dev mode"
    echo "  ./k3d-cluster.sh examples"
    echo ""
    echo "Production deployment:"
    echo "  ./k3d-cluster.sh build"
    echo "  ./k3d-cluster.sh deploy"
}

# Main script
case "${1:-help}" in
    create)
        create_cluster
        ;;
    delete)
        delete_cluster
        ;;
    start)
        start_cluster
        ;;
    stop)
        stop_cluster
        ;;
    status)
        status
        ;;
    crds)
        install_crds
        ;;
    redis)
        install_redis
        ;;
    build)
        build_and_push
        ;;
    deploy)
        deploy_operator
        ;;
    run-local)
        run_local
        ;;
    examples)
        deploy_examples
        ;;
    logs)
        logs ${2:-operator}
        ;;
    help|*)
        help
        ;;
esac
