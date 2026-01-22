#!/bin/bash
set -e

# Default values
IMAGE_NAME=${1:-mcp-operator}
TAG=${2:-latest}
REGISTRY=${3:-""}
PLATFORMS="linux/amd64,linux/arm64"

# Construct full image name
FULL_IMAGE_NAME="${IMAGE_NAME}:${TAG}"
if [ -n "$REGISTRY" ]; then
    FULL_IMAGE_NAME="${REGISTRY}/${FULL_IMAGE_NAME}"
fi

echo "Preparing to build multi-arch image: ${FULL_IMAGE_NAME}"
echo "Platforms: ${PLATFORMS}"

# Check for docker buildx
if ! docker buildx version > /dev/null 2>&1; then
    echo "Error: 'docker buildx' is not available. Please install Docker Desktop or buildx."
    exit 1
fi

# Create a new builder instance if it doesn't exist
BUILDER_NAME="mcp-operator-builder"
if ! docker buildx inspect "${BUILDER_NAME}" > /dev/null 2>&1; then
    echo "Creating new buildx builder: ${BUILDER_NAME}"
    docker buildx create --name "${BUILDER_NAME}" --use --driver docker-container
else
    echo "Using existing buildx builder: ${BUILDER_NAME}"
    docker buildx use "${BUILDER_NAME}"
fi

# Build and push
echo "Building and pushing..."
docker buildx build \
    --platform "${PLATFORMS}" \
    -t "${FULL_IMAGE_NAME}" \
    --push \
    .

echo "Successfully built and pushed ${FULL_IMAGE_NAME}"
