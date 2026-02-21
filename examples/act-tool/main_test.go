package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestHandleList(t *testing.T) {
	// Setup temporary .github/workflows directory
	tempDir, err := os.MkdirTemp("", "act-tool-test")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	// Mock file structure
	workflowsDir := filepath.Join(tempDir, ".github", "workflows")
	if err := os.MkdirAll(workflowsDir, 0755); err != nil {
		t.Fatalf("Failed to create workflows dir: %v", err)
	}

	// Change working directory to temp dir
	cwd, _ := os.Getwd()
	defer os.Chdir(cwd)
	os.Chdir(tempDir)

	workflowContent := `
name: Test Workflow
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo "Hello"
`
	if err := os.WriteFile(filepath.Join(workflowsDir, "ci.yml"), []byte(workflowContent), 0644); err != nil {
		t.Fatalf("Failed to write workflow file: %v", err)
	}

	req, err := http.NewRequest("POST", "/list", nil)
	if err != nil {
		t.Fatal(err)
	}

	rr := httptest.NewRecorder()
	handler := http.HandlerFunc(handleList)
	handler.ServeHTTP(rr, req)

	if status := rr.Code; status != http.StatusOK {
		t.Errorf("handler returned wrong status code: got %v want %v", status, http.StatusOK)
	}

	var resp ListResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
		t.Fatalf("Failed to unmarshal response: %v", err)
	}

	if len(resp.Workflows) != 1 {
		t.Errorf("Expected 1 workflow, got %d", len(resp.Workflows))
	} else {
		if resp.Workflows[0].Name != "Test Workflow" {
			t.Errorf("Expected workflow name 'Test Workflow', got '%s'", resp.Workflows[0].Name)
		}
	}
}

func TestHandleValidate(t *testing.T) {
	// Setup temporary .github/workflows directory
	tempDir, err := os.MkdirTemp("", "act-tool-test")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	workflowsDir := filepath.Join(tempDir, ".github", "workflows")
	if err := os.MkdirAll(workflowsDir, 0755); err != nil {
		t.Fatalf("Failed to create workflows dir: %v", err)
	}

	// Change working directory
	cwd, _ := os.Getwd()
	defer os.Chdir(cwd)
	os.Chdir(tempDir)

	workflowContent := `
name: Bad Workflow
jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: codecov/codecov-action@v3
`
	if err := os.WriteFile(filepath.Join(workflowsDir, "bad.yml"), []byte(workflowContent), 0644); err != nil {
		t.Fatalf("Failed to write workflow file: %v", err)
	}

	reqBody := []byte(`{"file": "bad.yml"}`)
	req, err := http.NewRequest("POST", "/validate", bytes.NewBuffer(reqBody))
	if err != nil {
		t.Fatal(err)
	}

	rr := httptest.NewRecorder()
	handler := http.HandlerFunc(handleValidate)
	handler.ServeHTTP(rr, req)

	if status := rr.Code; status != http.StatusOK {
		t.Errorf("handler returned wrong status code: got %v want %v", status, http.StatusOK)
	}

	var resp ValidateResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
		t.Fatalf("Failed to unmarshal response: %v", err)
	}

	// Expecting issues: windows-latest, codecov
	foundWindows := false
	foundCodecov := false

	for _, issue := range resp.Issues {
		if issue.Level == "warning" {
			if bytes.Contains([]byte(issue.Message), []byte("windows")) {
				foundWindows = true
			}
			if bytes.Contains([]byte(issue.Message), []byte("Codecov")) {
				foundCodecov = true
			}
		}
	}

	if !foundWindows {
		t.Error("Expected warning about windows-latest, not found")
	}
	if !foundCodecov {
		t.Error("Expected warning about Codecov, not found")
	}
}

func TestPathSanitization(t *testing.T) {
	// Setup temporary .github/workflows directory
	tempDir, err := os.MkdirTemp("", "act-tool-test")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	workflowsDir := filepath.Join(tempDir, ".github", "workflows")
	if err := os.MkdirAll(workflowsDir, 0755); err != nil {
		t.Fatalf("Failed to create workflows dir: %v", err)
	}

	// Create dummy file outside allowed path (e.g., in tempDir root)
	if err := os.WriteFile(filepath.Join(tempDir, "passwd"), []byte("secret"), 0644); err != nil {
		t.Fatalf("Failed to create dummy secret file: %v", err)
	}

	// Change working directory
	cwd, _ := os.Getwd()
	defer os.Chdir(cwd)
	os.Chdir(tempDir)

	// Attempt path traversal
	reqBody := []byte(`{"file": "../../passwd"}`)
	req, err := http.NewRequest("POST", "/validate", bytes.NewBuffer(reqBody))
	if err != nil {
		t.Fatal(err)
	}

	rr := httptest.NewRecorder()
	handler := http.HandlerFunc(handleValidate)
	handler.ServeHTTP(rr, req)

	// Should still return 200 OK but with error in body (per implementation)
	// Or implementation might change to return 400? Current implementation returns 200 with JSON error field.

	if status := rr.Code; status != http.StatusOK {
		t.Errorf("handler returned wrong status code: got %v want %v", status, http.StatusOK)
	}

	var resp ValidateResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
		t.Fatalf("Failed to unmarshal response: %v", err)
	}

	if resp.Error == "" {
		t.Error("Expected error for path traversal attempt, got none")
	}
}
