FROM golang:1.22-alpine AS builder

WORKDIR /app

# Copy go mod files
COPY go.mod go.sum* ./
RUN go mod download

# Copy source
COPY *.go ./

# Build static binary
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /kubectl-explain .

# Final minimal image
FROM alpine:3.19

# Add ca-certificates for HTTPS
RUN apk add --no-cache ca-certificates

# Non-root user
RUN adduser -D -u 1000 appuser
USER appuser

COPY --from=builder /kubectl-explain /kubectl-explain

EXPOSE 8080

ENTRYPOINT ["/kubectl-explain"]
