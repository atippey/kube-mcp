FROM golang:1.22-alpine AS builder

WORKDIR /app

# Copy go mod files
COPY go.mod go.sum* ./
RUN go mod download

# Copy source
COPY *.go ./

# Build static binary
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /time-tool .

# Final minimal image
FROM alpine:3.19

# Add ca-certificates for HTTPS and tzdata for timezones
RUN apk add --no-cache ca-certificates tzdata

# Non-root user
RUN adduser -D -u 1000 appuser
USER appuser

COPY --from=builder /time-tool /time-tool

EXPOSE 8080

ENTRYPOINT ["/time-tool"]
