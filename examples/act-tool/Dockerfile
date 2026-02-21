FROM golang:1.25-alpine AS builder

WORKDIR /app

# Copy go mod files
COPY go.mod go.sum* ./
RUN go mod download

# Copy source
COPY *.go ./

# Build static binary
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /act-tool .

# Final minimal image
FROM alpine:3.21

# Add dependencies:
# - ca-certificates for HTTPS
# - docker-cli for DinD communication
# - git for diff and checkout
# - curl for healthchecks (optional but good)
RUN apk add --no-cache ca-certificates docker-cli git curl

# Download act
ARG ACT_VERSION=0.2.84
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "arm64" ]; then ARCH="arm64"; else ARCH="x86_64"; fi && \
    wget -O act.tar.gz https://github.com/nektos/act/releases/download/v${ACT_VERSION}/act_Linux_${ARCH}.tar.gz && \
    tar -xf act.tar.gz -C /usr/local/bin act && \
    rm act.tar.gz

# Use root user for Docker socket access
# RUN adduser -D -u 1000 appuser
# USER appuser

COPY --from=builder /act-tool /act-tool

ENV PATH=$PATH:/usr/local/bin
EXPOSE 8080

ENTRYPOINT ["/act-tool"]
