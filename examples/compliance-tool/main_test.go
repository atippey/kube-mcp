package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestParseLockfiles_AllEcosystems(t *testing.T) {
	lockfiles := []LockfileInput{
		{Ecosystem: "python", Content: `[[package]]
name = "requests"
version = "2.31.0"

[[package]]
name = "pycryptodome"
version = "3.20.0"`},
		{Ecosystem: "go", Content: `github.com/google/uuid v1.6.0 h1:abc
github.com/google/uuid v1.6.0/go.mod h1:def`},
		{Ecosystem: "node", Content: `{"packages":{"":{"name":"app"},"node_modules/bcrypt":{"version":"5.1.1"}}}`},
		{Ecosystem: "rust", Content: `[[package]]
name = "ring"
version = "0.17.8"`},
	}

	deps := parseLockfiles(lockfiles)
	if len(deps) < 4 {
		t.Fatalf("expected at least 4 deps, got %d", len(deps))
	}

	want := []string{"requests", "pycryptodome", "github.com/google/uuid", "bcrypt", "ring"}
	for _, name := range want {
		if !containsDep(deps, name) {
			t.Fatalf("expected dependency %q to be present", name)
		}
	}
}

func TestCanI_PythonParamikoWithoutFIPSBaseDenied(t *testing.T) {
	req := CanIRequest{
		Action:    "add-dependency",
		Ecosystem: "python",
		Package:   "paramiko==3.4.0",
		Profiles:  []string{"fips-140-3"},
		Dockerfile: `FROM python:3.12-alpine
RUN pip install paramiko`,
	}

	rr := postJSON(t, handleCanI, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}

	var resp CanIResponse
	decodeJSON(t, rr.Body.Bytes(), &resp)
	if resp.Allowed {
		t.Fatalf("expected denied response")
	}
	if !containsFindingID(resp.Reasons, "FIPS-PY-BUILD-001") {
		t.Fatalf("expected FIPS-PY-BUILD-001 in reasons")
	}
}

func TestCanI_PythonParamikoWithFIPSBaseAllowed(t *testing.T) {
	req := CanIRequest{
		Action:    "add-dependency",
		Ecosystem: "python",
		Package:   "paramiko==3.4.0",
		Profiles:  []string{"fips-140-3"},
		Dockerfile: `FROM registry1.dso.mil/ironbank/opensource/python/python:3.12
RUN pip install --no-binary :all: paramiko`,
	}

	rr := postJSON(t, handleCanI, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}

	var resp CanIResponse
	decodeJSON(t, rr.Body.Bytes(), &resp)
	if !resp.Allowed {
		t.Fatalf("expected allowed response, reasons=%v", resp.Reasons)
	}
}

func TestCheck_FIPSWithExemptionPasses(t *testing.T) {
	cfg := `{
  "profiles": ["fips-140-3"],
  "exemptions": [
    {
      "package": "pycryptodome",
      "rule": "FIPS-CRYPTO-002",
      "expires": "2099-01-01"
    }
  ]
}`

	req := CheckRequest{
		Profiles: []string{"fips-140-3"},
		Lockfiles: []LockfileInput{
			{Ecosystem: "python", Content: `[[package]]
name = "pycryptodome"
version = "3.20.0"`},
		},
		Dockerfile: `FROM registry1.dso.mil/ironbank/opensource/python/python:3.12
RUN pip install --no-binary :all: -r requirements.txt`,
		Config: cfg,
	}

	rr := postJSON(t, handleCheck, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}

	var resp CheckResponse
	decodeJSON(t, rr.Body.Bytes(), &resp)
	if !resp.Compliant {
		t.Fatalf("expected compliant response, findings=%v", resp.Findings)
	}
}

func TestCheck_STIGFindingsDetected(t *testing.T) {
	req := CheckRequest{
		Profiles: []string{"stig-container"},
		Manifests: []string{`apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
      - name: app
        image: ghcr.io/example/app:latest`},
	}

	rr := postJSON(t, handleCheck, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}

	var resp CheckResponse
	decodeJSON(t, rr.Body.Bytes(), &resp)
	if resp.Compliant {
		t.Fatalf("expected non-compliant response")
	}
	if !containsFindingID(resp.Findings, "STIG-CTR-001") {
		t.Fatalf("expected STIG-CTR-001 finding")
	}
	if !containsFindingID(resp.Findings, "STIG-IMG-001") {
		t.Fatalf("expected STIG-IMG-001 finding")
	}
}

func TestRulesStatus_LocalOnly(t *testing.T) {
	_ = os.Unsetenv("IRON_BANK_READ_API")
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/rules/status", nil)
	handleRulesStatus(rr, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}

	var resp RulesStatusResponse
	decodeJSON(t, rr.Body.Bytes(), &resp)
	if resp.Mode != "local-only" {
		t.Fatalf("expected local-only mode, got %s", resp.Mode)
	}
	if len(resp.RuleSources) < 2 {
		t.Fatalf("expected rule sources in status")
	}
}

func TestDockerfileBaseImages_Multistage(t *testing.T) {
	dockerfile := `FROM golang:1.25-alpine AS builder
FROM registry1.dso.mil/ironbank/redhat/ubi/ubi9:9.4`
	images := dockerfileBaseImages(dockerfile)
	if len(images) != 2 {
		t.Fatalf("expected 2 images, got %d", len(images))
	}
	if images[1] != "registry1.dso.mil/ironbank/redhat/ubi/ubi9:9.4" {
		t.Fatalf("unexpected second image: %s", images[1])
	}
}

func TestRulesExportImportSignedBundle(t *testing.T) {
	tmp := t.TempDir()
	rulesPath := filepath.Join(tmp, "rules-snapshot.json")
	t.Setenv("COMPLIANCE_RULES_PATH", rulesPath)
	t.Setenv("COMPLIANCE_BUNDLE_HMAC_KEY", "test-hmac-key")

	seed := defaultSnapshot()
	seed.GeneratedAt = "2026-02-20T00:00:00Z"
	seedBytes, err := json.Marshal(seed)
	if err != nil {
		t.Fatalf("marshal seed snapshot: %v", err)
	}
	if err := os.WriteFile(rulesPath, seedBytes, 0o644); err != nil {
		t.Fatalf("write seed snapshot: %v", err)
	}

	exportRR := postJSON(t, handleRulesExport, RulesExportRequest{Signer: "unit-test"})
	if exportRR.Code != http.StatusOK {
		t.Fatalf("expected 200 export, got %d", exportRR.Code)
	}
	var exportResp RulesExportResponse
	decodeJSON(t, exportRR.Body.Bytes(), &exportResp)
	if exportResp.Bundle.Signature == "" {
		t.Fatalf("expected non-empty bundle signature")
	}

	importReq := RulesImportRequest{Bundle: exportResp.Bundle}
	importReq.Bundle.Snapshot.GeneratedAt = "2026-02-20T12:00:00Z"
	importReq.Bundle.Signature = signBundle(
		SignedRulesBundle{Metadata: importReq.Bundle.Metadata, Snapshot: importReq.Bundle.Snapshot},
		"test-hmac-key",
	)
	importRR := postJSON(t, handleRulesImport, importReq)
	if importRR.Code != http.StatusOK {
		t.Fatalf("expected 200 import, got %d", importRR.Code)
	}

	b, err := os.ReadFile(rulesPath)
	if err != nil {
		t.Fatalf("read imported snapshot: %v", err)
	}
	var snap RulesSnapshot
	decodeJSON(t, b, &snap)
	if snap.GeneratedAt != "2026-02-20T12:00:00Z" {
		t.Fatalf("expected imported snapshot generated_at to update, got %s", snap.GeneratedAt)
	}
}

func postJSON(t *testing.T, handler http.HandlerFunc, body any) *httptest.ResponseRecorder {
	t.Helper()
	b, err := json.Marshal(body)
	if err != nil {
		t.Fatalf("marshal body: %v", err)
	}
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	handler(rr, req)
	return rr
}

func decodeJSON(t *testing.T, b []byte, out any) {
	t.Helper()
	dec := json.NewDecoder(bytes.NewReader(b))
	if err := dec.Decode(out); err != nil {
		t.Fatalf("decode json: %v; body=%s", err, string(b))
	}
}

func containsDep(deps []dependency, name string) bool {
	needle := strings.ToLower(name)
	for _, dep := range deps {
		if strings.EqualFold(dep.Name, needle) {
			return true
		}
	}
	return false
}

func containsFindingID(findings []Finding, id string) bool {
	for _, f := range findings {
		if f.ID == id {
			return true
		}
	}
	return false
}
