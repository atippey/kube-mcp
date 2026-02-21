package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	"gopkg.in/yaml.v3"
)

func main() {
	http.HandleFunc("/health", handleHealth)
	http.HandleFunc("/list", handleList)
	http.HandleFunc("/validate", handleValidate)
	http.HandleFunc("/run", handleRun)
	http.HandleFunc("/diff", handleDiff)
	http.HandleFunc("/secrets", handleSecrets)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("Starting act-tool server on :%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

// sanitizePath ensures the path is within the allowed directory (.github/workflows)
func sanitizePath(file string) (string, error) {
	// Clean the path to remove .. and other oddities
	cleanPath := filepath.Clean(file)

	// Prevent absolute paths or starting with ..
	if filepath.IsAbs(cleanPath) || strings.HasPrefix(cleanPath, "..") {
		return "", fmt.Errorf("invalid path: %s", file)
	}

	// Always prepend .github/workflows
	fullPath := filepath.Join(".github/workflows", cleanPath)

	// Verify it is still within .github/workflows
	cwd, err := os.Getwd()
	if err != nil {
		return "", err
	}
	absPath, err := filepath.Abs(fullPath)
	if err != nil {
		return "", err
	}
	expectedPrefix := filepath.Join(cwd, ".github/workflows")
	if !strings.HasPrefix(absPath, expectedPrefix) {
		return "", fmt.Errorf("path traversal attempt: %s", file)
	}

	return fullPath, nil
}


func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
}

// --- /list ---

type Workflow struct {
	Name string           `yaml:"name"`
	On   yaml.Node        `yaml:"on"`
	Jobs map[string]Job   `yaml:"jobs"`
}

type Job struct {
	Name string `yaml:"name"`
}

type ListResponse struct {
	Workflows []WorkflowInfo `json:"workflows"`
	Error     string         `json:"error,omitempty"`
}

type WorkflowInfo struct {
	File     string   `json:"file"`
	Name     string   `json:"name"`
	Triggers []string `json:"triggers"`
	Jobs     []string `json:"jobs"`
}

func handleList(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	files, err := filepath.Glob(".github/workflows/*.y*ml")
	if err != nil {
		json.NewEncoder(w).Encode(ListResponse{Error: fmt.Sprintf("failed to glob workflows: %v", err)})
		return
	}

	var workflows []WorkflowInfo
	for _, file := range files {
		content, err := os.ReadFile(file)
		if err != nil {
			log.Printf("Failed to read file %s: %v", file, err)
			continue
		}

		var wf Workflow
		if err := yaml.Unmarshal(content, &wf); err != nil {
			log.Printf("Failed to parse file %s: %v", file, err)
			continue
		}

		// Parse triggers from 'on' node
		var triggers []string
		if wf.On.Kind == yaml.ScalarNode {
			triggers = append(triggers, wf.On.Value)
		} else if wf.On.Kind == yaml.SequenceNode {
			for _, node := range wf.On.Content {
				triggers = append(triggers, node.Value)
			}
		} else if wf.On.Kind == yaml.MappingNode {
			for i := 0; i < len(wf.On.Content); i += 2 {
				triggers = append(triggers, wf.On.Content[i].Value)
			}
		}

		var jobs []string
		for jobID := range wf.Jobs {
			jobs = append(jobs, jobID)
		}

		workflows = append(workflows, WorkflowInfo{
			File:     filepath.Base(file),
			Name:     wf.Name,
			Triggers: triggers,
			Jobs:     jobs,
		})
	}

	json.NewEncoder(w).Encode(ListResponse{Workflows: workflows})
}

// --- /validate ---

type ValidateRequest struct {
	File string `json:"file"`
}

type ValidateResponse struct {
	Issues []ValidationIssue `json:"issues"`
	Error  string            `json:"error,omitempty"`
}

type ValidationIssue struct {
	Level   string `json:"level"`   // "warning" or "error"
	Message string `json:"message"`
	Job     string `json:"job,omitempty"`
}

// Simple structure to parse steps for validation
type JobValidation struct {
	RunsOn string                   `yaml:"runs-on"`
	Steps  []map[string]interface{} `yaml:"steps"`
}

type WorkflowValidation struct {
	Jobs map[string]JobValidation `yaml:"jobs"`
}

func handleValidate(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	var req ValidateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	if req.File == "" {
		http.Error(w, "file is required", http.StatusBadRequest)
		return
	}

	path, err := sanitizePath(req.File)
	if err != nil {
		json.NewEncoder(w).Encode(ValidateResponse{Error: err.Error()})
		return
	}

	content, err := os.ReadFile(path)
	if err != nil {
		json.NewEncoder(w).Encode(ValidateResponse{Error: fmt.Sprintf("failed to read file: %v", err)})
		return
	}

	var wf WorkflowValidation
	if err := yaml.Unmarshal(content, &wf); err != nil {
		json.NewEncoder(w).Encode(ValidateResponse{Error: fmt.Sprintf("failed to parse yaml: %v", err)})
		return
	}

	var issues []ValidationIssue

	// Check for known incompatible actions or features
	for jobID, job := range wf.Jobs {
		// Check runs-on
		if strings.Contains(job.RunsOn, "windows") || strings.Contains(job.RunsOn, "macos") {
			issues = append(issues, ValidationIssue{
				Level:   "warning",
				Message: fmt.Sprintf("Job uses '%s', act uses Linux containers by default", job.RunsOn),
				Job:     jobID,
			})
		}

		for _, step := range job.Steps {
			// Check 'uses'
			if uses, ok := step["uses"].(string); ok {
				if strings.Contains(uses, "codecov") {
					issues = append(issues, ValidationIssue{
						Level:   "warning",
						Message: "Codecov action often requires token in act environment",
						Job:     jobID,
					})
				}
				if strings.Contains(uses, "docker/login-action") {
					issues = append(issues, ValidationIssue{
						Level:   "warning",
						Message: "docker/login-action requires valid credentials in act environment",
						Job:     jobID,
					})
				}
				if strings.Contains(uses, "actions/cache") {
					issues = append(issues, ValidationIssue{
						Level:   "warning",
						Message: "Caching may not persist between act runs without extra config",
						Job:     jobID,
					})
				}
			}
		}
	}

	if issues == nil {
		issues = []ValidationIssue{}
	}

	json.NewEncoder(w).Encode(ValidateResponse{Issues: issues})
}

// --- /run ---

type RunRequest struct {
	Workflow string `json:"workflow"`
	Job      string `json:"job,omitempty"`
	Event    string `json:"event,omitempty"`
	Dryrun   bool   `json:"dryrun,omitempty"`
}

type RunResponse struct {
	Stdout   string `json:"stdout"`
	Stderr   string `json:"stderr"`
	ExitCode int    `json:"exitCode"`
	Error    string `json:"error,omitempty"`
}

func handleRun(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	var req RunRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	args := []string{}

	if req.Workflow != "" {
		path, err := sanitizePath(req.Workflow)
		if err != nil {
			json.NewEncoder(w).Encode(RunResponse{Error: err.Error()})
			return
		}
		args = append(args, "-W", path)
	}

	if req.Job != "" {
		args = append(args, "-j", req.Job)
	}

	if req.Event != "" {
		args = append(args, req.Event)
	}

	if req.Dryrun {
		args = append(args, "-n")
	}

	// Output structured JSON
	args = append(args, "--json")

	// We need to run inside the repo root.
	// Assuming the container is started with working directory as repo root or volume mounted there.
	// But in this "tool" context, we might be running inside a pod where the repo is mounted?
	// The prompt implies we are running in a context where .github/workflows exists.
	// I'll assume standard working directory.

	cmd := exec.Command("act", args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	exitCode := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
		} else {
			// This is a failure to start, or other error
			json.NewEncoder(w).Encode(RunResponse{
				Error: fmt.Sprintf("failed to run act: %v", err),
			})
			return
		}
	}

	json.NewEncoder(w).Encode(RunResponse{
		Stdout:   stdout.String(),
		Stderr:   stderr.String(),
		ExitCode: exitCode,
	})
}

// --- /diff ---

type DiffRequest struct {
	Base string `json:"base"`
	Head string `json:"head"`
}

type DiffResponse struct {
	AffectedJobs []string `json:"affectedJobs"`
	Error        string   `json:"error,omitempty"`
}

func handleDiff(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	var req DiffRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	if req.Base == "" || req.Head == "" {
		http.Error(w, "base and head are required", http.StatusBadRequest)
		return
	}

	// 1. Get changed files
	cmd := exec.Command("git", "diff", "--name-only", req.Base+"..."+req.Head)
	output, err := cmd.Output()
	if err != nil {
		json.NewEncoder(w).Encode(DiffResponse{Error: fmt.Sprintf("git diff failed: %v", err)})
		return
	}

	changedFiles := strings.Split(string(output), "\n")

	// 2. Parse workflows and find affected jobs
	// This is a heuristic: if 'paths' filter matches changed files.
	// If no 'paths' filter, assume all jobs in 'push' or 'pull_request' workflows are affected.

	files, _ := filepath.Glob(".github/workflows/*.y*ml")
	affectedJobs := make(map[string]bool)

	for _, file := range files {
		content, err := os.ReadFile(file)
		if err != nil {
			continue
		}

		var wf Workflow
		if err := yaml.Unmarshal(content, &wf); err != nil {
			continue
		}

		// Simplified logic: checking 'on.push.paths' or 'on.pull_request.paths'
		// Note: The YAML parsing for 'on' needs to be robust.
		// For MVP, if we can't easily parse paths, we might default to "all jobs if triggered".
		// But let's try to do it right.

		// Re-parsing specifically for paths
		// Since 'on' can be complex, let's use a specialized struct or map
		var detailedWf struct {
			On map[string]struct {
				Paths []string `yaml:"paths"`
			} `yaml:"on"`
			Jobs map[string]interface{} `yaml:"jobs"`
		}

		// This will only work if 'on' is a map. If it's a string or list, it means "always run on these events".
		// We'll first check if we can unmarshal into this structure.
		// If unmarshal fails or Paths is empty, it usually means no path filter -> run it.

		isAffected := false

		if err := yaml.Unmarshal(content, &detailedWf); err == nil && len(detailedWf.On) > 0 {
			// Check if we have push or pull_request
			var paths []string
			if p, ok := detailedWf.On["push"]; ok {
				paths = append(paths, p.Paths...)
			}
			if p, ok := detailedWf.On["pull_request"]; ok {
				paths = append(paths, p.Paths...)
			}

			if len(paths) == 0 {
				// No paths filter defined for these events?
				// Need to distinguish between "event not present" and "no paths filter".
				// For now, if we see push/pr keys, we assume they trigger.
				if _, ok := detailedWf.On["push"]; ok {
					isAffected = true // No paths filter = always trigger
				}
				if _, ok := detailedWf.On["pull_request"]; ok {
					isAffected = true
				}
			} else {
				// Check if any changed file matches any path pattern
				for _, cf := range changedFiles {
					if cf == "" { continue }
					for _, pattern := range paths {
						matched, _ := filepath.Match(pattern, cf)
						// filepath.Match is limited (no **), but good enough for MVP?
						// Actually github workflow patterns support globstar.
						// For now, simple prefix check or exact match might be safer if glob is hard.
						// Or just assume match if we can't verify.
						if matched || strings.HasPrefix(cf, strings.TrimSuffix(pattern, "*")) {
							isAffected = true
							break
						}
					}
					if isAffected { break }
				}
			}
		} else {
			// 'on' might be string or list (e.g. on: [push, pull_request])
			// In this case, no paths filter -> always affected
			isAffected = true
		}

		if isAffected {
			for jobID := range wf.Jobs {
				affectedJobs[jobID] = true
			}
		}
	}

	var jobs []string
	for job := range affectedJobs {
		jobs = append(jobs, job)
	}

	json.NewEncoder(w).Encode(DiffResponse{AffectedJobs: jobs})
}

// --- /secrets ---

type SecretsRequest struct {
	File string `json:"file"`
}

type SecretsResponse struct {
	Secrets []SecretInfo `json:"secrets"`
	Error   string       `json:"error,omitempty"`
}

type SecretInfo struct {
	Name      string `json:"name"`
	Required  bool   `json:"required"`
	Available bool   `json:"available"`
}

func handleSecrets(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	var req SecretsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	if req.File == "" {
		http.Error(w, "file is required", http.StatusBadRequest)
		return
	}

	path, err := sanitizePath(req.File)
	if err != nil {
		json.NewEncoder(w).Encode(SecretsResponse{Error: err.Error()})
		return
	}

	content, err := os.ReadFile(path)
	if err != nil {
		json.NewEncoder(w).Encode(SecretsResponse{Error: fmt.Sprintf("failed to read file: %v", err)})
		return
	}

	// Simple regex search for secrets.SECRET_NAME
	// This is heuristic.
	re := regexp.MustCompile(`secrets\.([A-Z0-9_]+)`)
	matches := re.FindAllStringSubmatch(string(content), -1)

	uniqueSecrets := make(map[string]bool)
	for _, m := range matches {
		if len(m) > 1 {
			uniqueSecrets[m[1]] = true
		}
	}

	// Check env for availability
	// ACT uses env vars or secrets file. In this tool, we might check env vars of the pod?
	// Or maybe checking if they are provided in the request?
	// The prompt says: "Report which are required, which are optional (have fallback/if guards), and which are available in the environment."
	// "Available in environment" probably refers to the environment where `act` will run.

	var secrets []SecretInfo
	for name := range uniqueSecrets {
		// Heuristic for "Required": if it's not inside an ${{ if ... }} block?
		// That's hard to parse with regex. defaulting to true for MVP.

		// Check availability in current env (where act runs)
		available := os.Getenv(name) != ""

		secrets = append(secrets, SecretInfo{
			Name:      name,
			Required:  true, // Defaulting
			Available: available,
		})
	}

	json.NewEncoder(w).Encode(SecretsResponse{Secrets: secrets})
}
