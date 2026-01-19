FROM python:3.12-slim

WORKDIR /app

# Install poetry
RUN pip install --no-cache-dir poetry

# Copy dependency files first for better layer caching
COPY pyproject.toml poetry.lock ./

# Install dependencies (no dev dependencies, no virtualenv in container)
RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main --no-root

# Copy source code
COPY src/ ./src/

# Run as non-root user
RUN useradd --create-home --uid 1000 --user-group appuser
USER appuser

# Set PYTHONPATH so imports work correctly
ENV PYTHONPATH=/app

# kopf operator entrypoint
ENTRYPOINT ["kopf", "run", "--standalone", "--all-namespaces", "src/main.py"]
