# ---- Builder: export pinned requirements from poetry.lock ----
FROM python:3.12-alpine AS builder

WORKDIR /build

RUN pip install --no-cache-dir poetry poetry-plugin-export

COPY pyproject.toml poetry.lock ./

RUN poetry export -f requirements.txt --only main --without-hashes -o requirements.txt

# ---- Runtime: minimal Alpine image, no poetry ----
FROM python:3.12-alpine

WORKDIR /app

# Set PYTHONPATH so imports work correctly
ENV PYTHONPATH=/app

# Install pinned dependencies via pip (no poetry in final image)
COPY --from=builder /build/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    rm -rf /usr/local/lib/python3.12/site-packages/pip* \
           /usr/local/lib/python3.12/site-packages/setuptools* \
           /usr/local/bin/pip* \
           requirements.txt

# Copy source code
COPY src/ ./src/

# Run as non-root user
RUN adduser -D -u 1000 appuser
USER appuser

# Expose metrics and health ports
EXPOSE 9090 8080

# kopf operator entrypoint with health probe
ENTRYPOINT ["kopf", "run", "--standalone", "--all-namespaces", "--liveness=http://0.0.0.0:8080/healthz", "src/main.py"]
