.PHONY: help install dev lint format test test-fast test-integration check fix run \
        k3d-create k3d-delete k3d-start k3d-stop k3d-status \
        k3d-crds k3d-redis k3d-examples k3d-build k3d-deploy \
        kustomize-dev kustomize-k3d kustomize-prod \
        docker-build-multiarch \
        sample-build sample-push sample-deploy

# Image configuration
IMAGE ?= mcp-operator
TAG ?= latest
REGISTRY ?= ghcr.io/atippey

# Default target
help:
	@echo "MCP Operator - Development Commands"
	@echo ""
	@echo "Python (via poe):"
	@echo "  make install      Install dependencies with Poetry"
	@echo "  make dev          Install with dev dependencies"
	@echo "  make lint         Run ruff linter"
	@echo "  make format       Format code with ruff"
	@echo "  make test         Run unit tests with coverage"
	@echo "  make test-fast    Run unit tests without coverage"
	@echo "  make test-integration  Run integration tests (requires cluster)"
	@echo "  make check        Run all checks (lint, format, typecheck)"
	@echo "  make fix          Auto-fix lint and format issues"
	@echo "  make run          Run operator locally (kopf)"
	@echo ""
	@echo "k3d Cluster:"
	@echo "  make setup-k3d    Install k3d (brew on Mac, curl on Linux/CI)"
	@echo "  make k3d-create   Create k3d cluster"
	@echo "  make k3d-delete   Delete k3d cluster"
	@echo "  make k3d-start    Start k3d cluster"
	@echo "  make k3d-stop     Stop k3d cluster"
	@echo "  make k3d-status   Show cluster status"
	@echo "  make k3d-crds     Install CRDs"
	@echo "  make k3d-redis    Install Redis"
	@echo "  make k3d-examples Deploy example resources"
	@echo "  make k3d-build    Build and push operator image"
	@echo "  make k3d-deploy   Deploy operator to cluster"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build-multiarch  Build and push multi-arch image (amd64, arm64)"
	@echo ""
	@echo "Sample Echo Server:"
	@echo "  make sample-build   Build echo-server image locally"
	@echo "  make sample-push    Build and push echo-server to registry"
	@echo "  make sample-deploy  Deploy sample resources to cluster"
	@echo ""
	@echo "Kustomize:"
	@echo "  make kustomize-dev   Apply dev overlay"
	@echo "  make kustomize-k3d   Apply k3d overlay"
	@echo "  make kustomize-prod  Apply production overlay"

# =============================================================================
# Python / Poetry / Poe
# =============================================================================

install:
	poetry install --without dev

dev:
	poetry install

lint:
	poetry run poe lint

format:
	poetry run poe format

test:
	poetry run poe test

test-fast:
	poetry run poe test-fast

test-integration:
	poetry run poe test-integration

check:
	poetry run poe check

fix:
	poetry run poe fix

run:
	poetry run poe run

# =============================================================================
# k3d Setup & Cluster Management
# =============================================================================

# Install k3d - works on macOS (brew), Linux, and CI
setup-k3d:
	@if command -v k3d >/dev/null 2>&1; then \
		echo "k3d already installed: $$(k3d version | head -1)"; \
	elif command -v brew >/dev/null 2>&1; then \
		echo "Installing k3d via Homebrew..."; \
		brew install k3d; \
	else \
		echo "Installing k3d via install script..."; \
		curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash; \
	fi

k3d-create:
	./scripts/k3d-cluster.sh create

k3d-delete:
	./scripts/k3d-cluster.sh delete

k3d-start:
	./scripts/k3d-cluster.sh start

k3d-stop:
	./scripts/k3d-cluster.sh stop

k3d-status:
	./scripts/k3d-cluster.sh status

k3d-crds:
	./scripts/k3d-cluster.sh crds

k3d-redis:
	./scripts/k3d-cluster.sh redis

k3d-examples:
	./scripts/k3d-cluster.sh examples

k3d-build:
	REGISTRY=localhost:5000 IMAGE=$(IMAGE) TAG=$(TAG) ./scripts/k3d-cluster.sh build

k3d-deploy:
	./scripts/k3d-cluster.sh deploy

# =============================================================================
# Kustomize Deployments
# =============================================================================

kustomize-dev:
	kubectl apply -k manifests/overlays/dev

kustomize-k3d:
	kubectl apply -k manifests/overlays/k3d

kustomize-prod:
	kubectl apply -k manifests/overlays/production

# =============================================================================
# Docker Builds
# =============================================================================

docker-build-multiarch:
	./scripts/build_multiarch.sh $(IMAGE) $(TAG) $(REGISTRY)

# =============================================================================
# Sample Echo Server
# =============================================================================

SAMPLE_IMAGE ?= mcp-echo-server
SAMPLE_TAG ?= latest
SAMPLE_REGISTRY ?= $(REGISTRY)

sample-build:
	docker build -t $(SAMPLE_IMAGE):$(SAMPLE_TAG) examples/echo-server/

sample-push:
	docker buildx build --platform linux/arm64,linux/amd64 \
		-t $(SAMPLE_REGISTRY)/$(SAMPLE_IMAGE):$(SAMPLE_TAG) \
		--push examples/echo-server/

sample-deploy:
	kubectl apply -k examples/echo-server/manifests/
