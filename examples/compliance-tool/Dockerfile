FROM golang:1.25-alpine AS builder

WORKDIR /app

COPY go.mod ./
RUN go mod download

COPY *.go ./
COPY data ./data

RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /compliance-tool .

FROM alpine:3.19

RUN apk add --no-cache ca-certificates
RUN adduser -D -u 1000 appuser
USER appuser

WORKDIR /app
COPY --from=builder /compliance-tool /compliance-tool
COPY --from=builder /app/data /app/data

ENV COMPLIANCE_RULES_PATH=/app/data/rules-snapshot.json

EXPOSE 8080

ENTRYPOINT ["/compliance-tool"]
