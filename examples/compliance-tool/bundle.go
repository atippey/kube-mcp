package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"time"
)

type BundleMetadata struct {
	Version     string `json:"version"`
	GeneratedAt string `json:"generated_at"`
	Signer      string `json:"signer"`
	Algorithm   string `json:"algorithm"`
}

type SignedRulesBundle struct {
	Metadata  BundleMetadata `json:"metadata"`
	Snapshot  RulesSnapshot  `json:"snapshot"`
	Signature string         `json:"signature"`
}

type RulesExportRequest struct {
	Signer string `json:"signer"`
}

type RulesExportResponse struct {
	Bundle SignedRulesBundle `json:"bundle"`
	Mode   string            `json:"mode"`
}

type RulesImportRequest struct {
	Bundle SignedRulesBundle `json:"bundle"`
}

type RulesImportResponse struct {
	Imported    bool   `json:"imported"`
	Path        string `json:"path"`
	GeneratedAt string `json:"generated_at"`
}

func handleRulesExport(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
		return
	}
	key := os.Getenv("COMPLIANCE_BUNDLE_HMAC_KEY")
	if key == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "COMPLIANCE_BUNDLE_HMAC_KEY is required"})
		return
	}

	var req RulesExportRequest
	_ = json.NewDecoder(r.Body).Decode(&req)
	if req.Signer == "" {
		req.Signer = "compliance-tool"
	}

	bundle := SignedRulesBundle{
		Metadata: BundleMetadata{
			Version:     "v1",
			GeneratedAt: time.Now().UTC().Format(time.RFC3339),
			Signer:      req.Signer,
			Algorithm:   "hmac-sha256",
		},
		Snapshot: loadSnapshot(),
	}
	bundle.Signature = signBundle(bundle, key)

	writeJSON(w, http.StatusOK, RulesExportResponse{Bundle: bundle, Mode: evalMode()})
}

func handleRulesImport(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
		return
	}
	key := os.Getenv("COMPLIANCE_BUNDLE_HMAC_KEY")
	if key == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "COMPLIANCE_BUNDLE_HMAC_KEY is required"})
		return
	}

	var req RulesImportRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
		return
	}

	if !verifyBundle(req.Bundle, key) {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "bundle signature verification failed"})
		return
	}

	path := rulesPath()
	b, err := json.MarshalIndent(req.Bundle.Snapshot, "", "  ")
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": fmt.Sprintf("marshal snapshot failed: %v", err)})
		return
	}
	if err := os.WriteFile(path, b, 0o644); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": fmt.Sprintf("write snapshot failed: %v", err)})
		return
	}

	writeJSON(w, http.StatusOK, RulesImportResponse{Imported: true, Path: path, GeneratedAt: req.Bundle.Snapshot.GeneratedAt})
}

func signBundle(bundle SignedRulesBundle, key string) string {
	h := hmac.New(sha256.New, []byte(key))
	_, _ = h.Write(bundleSignPayload(bundle))
	return hex.EncodeToString(h.Sum(nil))
}

func verifyBundle(bundle SignedRulesBundle, key string) bool {
	expected := signBundle(SignedRulesBundle{Metadata: bundle.Metadata, Snapshot: bundle.Snapshot}, key)
	return hmac.Equal([]byte(expected), []byte(bundle.Signature))
}

func bundleSignPayload(bundle SignedRulesBundle) []byte {
	payload := struct {
		Metadata BundleMetadata `json:"metadata"`
		Snapshot RulesSnapshot  `json:"snapshot"`
	}{
		Metadata: bundle.Metadata,
		Snapshot: bundle.Snapshot,
	}
	b, _ := json.Marshal(payload)
	return b
}

func rulesPath() string {
	path := os.Getenv("COMPLIANCE_RULES_PATH")
	if path == "" {
		path = "data/rules-snapshot.json"
	}
	return path
}
