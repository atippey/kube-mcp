package main

import (
	"bufio"
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

type LockfileInput struct {
	Ecosystem string `json:"ecosystem"`
	Content   string `json:"content"`
}

type CheckRequest struct {
	Profile    string          `json:"profile"`
	Profiles   []string        `json:"profiles"`
	Lockfiles  []LockfileInput `json:"lockfiles"`
	Manifests  []string        `json:"manifests"`
	Dockerfile string          `json:"dockerfile"`
	Config     string          `json:"config"`
}

type CanIRequest struct {
	Action          string   `json:"action"`
	Ecosystem       string   `json:"ecosystem"`
	Package         string   `json:"package"`
	CurrentLockfile string   `json:"current_lockfile"`
	Profiles        []string `json:"profiles"`
	Dockerfile      string   `json:"dockerfile"`
	Config          string   `json:"config"`
}

type Finding struct {
	ID          string `json:"id"`
	Severity    string `json:"severity"`
	Category    string `json:"category"`
	Package     string `json:"package,omitempty"`
	Message     string `json:"message"`
	Remediation string `json:"remediation,omitempty"`
	Evidence    string `json:"evidence,omitempty"`
}

type Score struct {
	Passed   int `json:"passed"`
	Failed   int `json:"failed"`
	Exempted int `json:"exempted"`
	Total    int `json:"total"`
}

type CheckResponse struct {
	Compliant bool      `json:"compliant"`
	Profiles  []string  `json:"profiles"`
	Score     Score     `json:"score"`
	Findings  []Finding `json:"findings"`
	Mode      string    `json:"mode"`
}

type CanIResponse struct {
	Allowed       bool              `json:"allowed"`
	Package       string            `json:"package"`
	Reasons       []Finding         `json:"reasons"`
	Alternatives  []Alternative     `json:"alternatives,omitempty"`
	ProfileImpact map[string]Impact `json:"profile_impact"`
	Mode          string            `json:"mode"`
}

type Alternative struct {
	Package   string `json:"package"`
	Condition string `json:"condition"`
	Impact    string `json:"impact"`
}

type Impact struct {
	Before string `json:"before"`
	After  string `json:"after"`
}

type Config struct {
	Profiles           []string
	RequireIronBank    bool
	ApprovedRegistries []string
	Exemptions         []Exemption
}

type Exemption struct {
	Package string
	Rule    string
	Expires string
}

type RuleSourceStatus struct {
	Name        string `json:"name"`
	LastFetched string `json:"last_fetched,omitempty"`
	NextRefresh string `json:"next_refresh,omitempty"`
	Entries     int    `json:"entries,omitempty"`
	Version     string `json:"version,omitempty"`
	Status      string `json:"status"`
}

type RulesStatusResponse struct {
	RuleSources  []RuleSourceStatus `json:"rule_sources"`
	CacheBackend string             `json:"cache_backend"`
	TTLHours     int                `json:"ttl_hours"`
	Mode         string             `json:"mode"`
	IronBank     map[string]string  `json:"iron_bank"`
}

type RulesSnapshot struct {
	GeneratedAt             string              `json:"generated_at"`
	TTLHours                int                 `json:"ttl_hours"`
	IronBankImages          []string            `json:"iron_bank_images"`
	FIPSEnabledImages       []string            `json:"fips_enabled_images"`
	CMVPValidatedPackages   []string            `json:"cmvp_validated_packages"`
	KnownNativeNodePackages []string            `json:"known_native_node_packages"`
	DeniedPackages          map[string][]string `json:"denied_packages"`
}

type dependency struct {
	Name      string
	Version   string
	Ecosystem string
}

var (
	fromRe = regexp.MustCompile(`(?i)^\s*FROM\s+([^\s]+)`)
)

func main() {
	http.HandleFunc("/health", handleHealth)
	http.HandleFunc("/compliance/check", handleCheck)
	http.HandleFunc("/compliance/can-i", handleCanI)
	http.HandleFunc("/rules/status", handleRulesStatus)
	http.HandleFunc("/rules/export", handleRulesExport)
	http.HandleFunc("/rules/import", handleRulesImport)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("Starting compliance-tool server on :%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "healthy", "mode": evalMode()})
}

func handleRulesStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
		return
	}

	snap := loadSnapshot()
	now := time.Now().UTC()
	ttl := snap.TTLHours
	if ttl == 0 {
		ttl = 6
	}
	next := now.Add(time.Duration(ttl) * time.Hour).Format(time.RFC3339)

	status := RulesStatusResponse{
		RuleSources: []RuleSourceStatus{
			{Name: "Local CMVP snapshot", LastFetched: snap.GeneratedAt, NextRefresh: next, Entries: len(snap.CMVPValidatedPackages), Status: "ok"},
			{Name: "Local Iron Bank snapshot", LastFetched: snap.GeneratedAt, NextRefresh: next, Entries: len(snap.IronBankImages), Status: "ok"},
			{Name: "Local STIG ruleset", Version: "example-v1", Status: "ok"},
		},
		CacheBackend: "local-file",
		TTLHours:     ttl,
		Mode:         evalMode(),
		IronBank:     map[string]string{"token_configured": fmt.Sprintf("%t", os.Getenv("IRON_BANK_READ_API") != ""), "live_probe": "disabled"},
	}

	if os.Getenv("IRON_BANK_READ_API") != "" {
		if err := probeIronBank(); err != nil {
			status.IronBank["live_probe"] = "failed"
			status.IronBank["live_error"] = err.Error()
		} else {
			status.IronBank["live_probe"] = "ok"
		}
	}

	writeJSON(w, http.StatusOK, status)
}

func handleCheck(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
		return
	}

	var req CheckRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
		return
	}

	profiles := resolveProfiles(req.Profile, req.Profiles)
	cfg := parseConfig(req.Config)
	deps := parseLockfiles(req.Lockfiles)
	findings := evaluateCheck(profiles, cfg, deps, req.Manifests, req.Dockerfile)

	failed := len(findings)
	total := maxInt(1, len(profiles)*4)
	passed := total - failed
	if passed < 0 {
		passed = 0
	}

	resp := CheckResponse{
		Compliant: failed == 0,
		Profiles:  profiles,
		Score:     Score{Passed: passed, Failed: failed, Exempted: 0, Total: total},
		Findings:  findings,
		Mode:      evalMode(),
	}
	writeJSON(w, http.StatusOK, resp)
}

func handleCanI(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
		return
	}

	var req CanIRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
		return
	}
	if strings.TrimSpace(req.Package) == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "package is required"})
		return
	}

	profiles := req.Profiles
	if len(profiles) == 0 {
		profiles = []string{"fips-140-3"}
	}
	cfg := parseConfig(req.Config)
	candidateName := normalizePkgName(req.Package)
	snap := loadSnapshot()
	reasons := []Finding{}
	alternatives := []Alternative{}

	for _, profile := range profiles {
		if profile != "fips" && profile != "fips-140-3" {
			continue
		}

		if isDenied(candidateName, req.Ecosystem, snap) {
			reasons = append(reasons, Finding{
				ID:          "FIPS-CRYPTO-002",
				Severity:    "CRITICAL",
				Category:    "dependency",
				Package:     req.Package,
				Message:     fmt.Sprintf("%s is denied in %s FIPS profile", candidateName, req.Ecosystem),
				Remediation: "Use a validated alternative package or file an exemption with expiration.",
			})
		}

		canICtx := map[string]any{
			"needs_python_fips_guard": req.Ecosystem == "python" && (candidateName == "cryptography" || candidateName == "paramiko"),
			"python_fips_ready":       dockerfileSupportsFIPSPython(req.Dockerfile, cfg, snap),
			"needs_go_fips_guard":     req.Ecosystem == "go",
			"go_boringcrypto":         strings.Contains(strings.ToLower(req.Dockerfile), "goexperiment=boringcrypto"),
		}
		reasons = append(reasons, evaluateCELRules(canICtx, []CELRule{
			{
				ID:          "FIPS-PY-BUILD-001",
				Severity:    "HIGH",
				Category:    "build",
				Expr:        "needs_python_fips_guard && !python_fips_ready",
				Message:     "Python FIPS mode requires source builds and a FIPS-capable base image.",
				Evidence:    "Expected pip --no-binary :all: and FIPS-enabled base image in Dockerfile.",
				Remediation: "Use an Iron Bank/FIPS base image and force source builds.",
				Package:     req.Package,
			},
			{
				ID:          "FIPS-GO-001",
				Severity:    "HIGH",
				Category:    "build",
				Expr:        "needs_go_fips_guard && !go_boringcrypto",
				Message:     "Go FIPS mode expects GOEXPERIMENT=boringcrypto in build stage.",
				Remediation: "Set GOEXPERIMENT=boringcrypto for go build.",
				Package:     req.Package,
			},
		})...)

		for _, reason := range reasons {
			if reason.ID == "FIPS-PY-BUILD-001" {
				alternatives = append(alternatives, Alternative{
					Package:   req.Package,
					Condition: "Switch to a FIPS-enabled base image and add pip --no-binary :all:",
					Impact:    "Enables Python crypto linkage checks during build.",
				})
				break
			}
		}
	}

	resp := CanIResponse{
		Allowed:      len(reasons) == 0,
		Package:      req.Package,
		Reasons:      reasons,
		Alternatives: alternatives,
		ProfileImpact: map[string]Impact{
			"fips-140-3": {Before: "unknown", After: profileDelta(len(reasons))},
		},
		Mode: evalMode(),
	}
	writeJSON(w, http.StatusOK, resp)
}

func evaluateCheck(profiles []string, cfg Config, deps []dependency, manifests []string, dockerfile string) []Finding {
	snap := loadSnapshot()
	findings := []Finding{}
	for _, profile := range profiles {
		switch profile {
		case "fips", "fips-140-3":
			findings = append(findings, evaluateFIPS(cfg, deps, dockerfile, snap)...)
		case "stig", "stig-container":
			findings = append(findings, evaluateSTIG(cfg, manifests, dockerfile)...)
		case "all":
			findings = append(findings, evaluateFIPS(cfg, deps, dockerfile, snap)...)
			findings = append(findings, evaluateSTIG(cfg, manifests, dockerfile)...)
		}
	}
	return dedupeFindings(findings)
}

func evaluateFIPS(cfg Config, deps []dependency, dockerfile string, snap RulesSnapshot) []Finding {
	findings := []Finding{}

	for _, dep := range deps {
		if isDenied(dep.Name, dep.Ecosystem, snap) && !isExempt(dep.Name, "FIPS-CRYPTO-002", cfg) {
			findings = append(findings, Finding{
				ID:          "FIPS-CRYPTO-002",
				Severity:    "CRITICAL",
				Category:    "dependency",
				Package:     dep.Name + "==" + dep.Version,
				Message:     "Non-validated crypto package found.",
				Remediation: "Replace package with a validated crypto implementation.",
			})
		}
	}

	buildCtx := map[string]any{
		"has_python":        hasEcosystem(deps, "python"),
		"python_fips_ready": dockerfileSupportsFIPSPython(dockerfile, cfg, snap),
		"has_go":            hasEcosystem(deps, "go"),
		"go_boringcrypto":   strings.Contains(strings.ToLower(dockerfile), "goexperiment=boringcrypto"),
	}
	findings = append(findings, evaluateCELRules(buildCtx, []CELRule{
		{
			ID:          "FIPS-PY-BUILD-001",
			Severity:    "HIGH",
			Category:    "build",
			Expr:        "has_python && !python_fips_ready",
			Message:     "Python FIPS strategy is incomplete.",
			Evidence:    "Missing source-build flag and/or FIPS-capable base image.",
			Remediation: "Use pip --no-binary :all: and an approved FIPS-enabled base image.",
		},
		{
			ID:          "FIPS-GO-001",
			Severity:    "HIGH",
			Category:    "build",
			Expr:        "has_go && !go_boringcrypto",
			Message:     "GOEXPERIMENT=boringcrypto not found in Dockerfile/build instructions.",
			Remediation: "Set GOEXPERIMENT=boringcrypto for build stage and verify with runtime attestation.",
		},
	})...)

	if hasEcosystem(deps, "node") {
		for _, dep := range deps {
			if dep.Ecosystem != "node" {
				continue
			}
			if isKnownNativeNodePackage(dep.Name, snap) {
				findings = append(findings, Finding{
					ID:          "FIPS-NODE-001",
					Severity:    "HIGH",
					Category:    "dependency",
					Package:     dep.Name + "@" + dep.Version,
					Message:     "Native Node dependency present in FIPS mode.",
					Remediation: "Avoid native addons in FIPS mode or run a controlled exemption flow.",
				})
			}
		}
	}

	if hasEcosystem(deps, "rust") {
		hasApproved := false
		for _, dep := range deps {
			if dep.Ecosystem != "rust" {
				continue
			}
			if dep.Name == "aws-lc-rs" || dep.Name == "openssl" {
				hasApproved = true
			}
		}
		if !hasApproved {
			findings = append(findings, Finding{
				ID:          "FIPS-RUST-001",
				Severity:    "HIGH",
				Category:    "dependency",
				Message:     "Rust project has no approved crypto backend dependency.",
				Remediation: "Use aws-lc-rs or openssl crate with FIPS-enabled runtime.",
			})
		}
	}

	return findings
}

func evaluateSTIG(cfg Config, manifests []string, dockerfile string) []Finding {
	findings := []Finding{}
	all := strings.Join(manifests, "\n---\n")
	lower := strings.ToLower(all)

	stigCtx := map[string]any{
		"has_run_as_non_root":                  strings.Contains(lower, "runasnonroot: true"),
		"has_allow_privilege_escalation_false": strings.Contains(lower, "allowprivilegeescalation: false") && !strings.Contains(lower, "allowprivilegeescalation: true"),
		"has_latest_tag":                       strings.Contains(lower, ":latest"),
		"has_network_policy":                   strings.Contains(lower, "kind: networkpolicy") && strings.Contains(lower, "policytypes") && strings.Contains(lower, "ingress") && strings.Contains(lower, "egress"),
	}
	findings = append(findings, evaluateCELRules(stigCtx, []CELRule{
		{
			ID:          "STIG-CTR-001",
			Severity:    "CAT-I",
			Category:    "manifest",
			Expr:        "!has_run_as_non_root",
			Message:     "Containers must set runAsNonRoot: true.",
			Remediation: "Set pod/container securityContext.runAsNonRoot=true and non-zero runAsUser.",
		},
		{
			ID:          "STIG-CTR-002",
			Severity:    "CAT-I",
			Category:    "manifest",
			Expr:        "!has_allow_privilege_escalation_false",
			Message:     "Privilege escalation must be disabled.",
			Remediation: "Set allowPrivilegeEscalation: false in every container securityContext.",
		},
		{
			ID:          "STIG-IMG-001",
			Severity:    "CAT-II",
			Category:    "manifest",
			Expr:        "has_latest_tag",
			Message:     "Production images should not use :latest tags.",
			Remediation: "Pin immutable image tags or digests in production.",
		},
		{
			ID:          "STIG-NET-001",
			Severity:    "CAT-II",
			Category:    "manifest",
			Expr:        "!has_network_policy",
			Message:     "Deny-by-default NetworkPolicy evidence is missing.",
			Remediation: "Include NetworkPolicy resources with Ingress and Egress policyTypes.",
		},
	})...)

	if cfg.RequireIronBank {
		for _, img := range dockerfileBaseImages(dockerfile) {
			if !strings.HasPrefix(img, "registry1.dso.mil/") {
				findings = append(findings, Finding{
					ID: "STIG-CTR-003", Severity: "CAT-I", Category: "dockerfile",
					Message:     "require_iron_bank=true but Dockerfile uses non-Iron-Bank base image.",
					Evidence:    img,
					Remediation: "Use registry1.dso.mil base images for all Dockerfile stages.",
				})
			}
		}
	}

	return findings
}

func parseLockfiles(lockfiles []LockfileInput) []dependency {
	deps := []dependency{}
	for _, lf := range lockfiles {
		eco := strings.ToLower(strings.TrimSpace(lf.Ecosystem))
		switch eco {
		case "python":
			deps = append(deps, parsePythonLock(lf.Content)...)
		case "go":
			deps = append(deps, parseGoSum(lf.Content)...)
		case "node":
			deps = append(deps, parseNodeLock(lf.Content)...)
		case "rust":
			deps = append(deps, parseCargoLock(lf.Content)...)
		}
	}
	return uniqueDeps(deps)
}

func parsePythonLock(content string) []dependency {
	deps := []dependency{}
	if strings.Contains(content, "[[package]]") {
		var name, version string
		s := bufio.NewScanner(strings.NewReader(content))
		flush := func() {
			if name != "" {
				deps = append(deps, dependency{Name: strings.ToLower(name), Version: version, Ecosystem: "python"})
			}
			name, version = "", ""
		}
		for s.Scan() {
			line := strings.TrimSpace(s.Text())
			if line == "[[package]]" {
				flush()
				continue
			}
			if strings.HasPrefix(line, "name = ") {
				name = strings.Trim(line[len("name = "):], "\"'")
			}
			if strings.HasPrefix(line, "version = ") {
				version = strings.Trim(line[len("version = "):], "\"'")
			}
		}
		flush()
		return deps
	}

	s := bufio.NewScanner(strings.NewReader(content))
	for s.Scan() {
		line := strings.TrimSpace(s.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		parts := strings.SplitN(line, "==", 2)
		if len(parts) == 2 {
			deps = append(deps, dependency{Name: strings.ToLower(strings.TrimSpace(parts[0])), Version: strings.TrimSpace(parts[1]), Ecosystem: "python"})
		}
	}
	return deps
}

func parseGoSum(content string) []dependency {
	deps := []dependency{}
	s := bufio.NewScanner(strings.NewReader(content))
	seen := map[string]struct{}{}
	for s.Scan() {
		fields := strings.Fields(strings.TrimSpace(s.Text()))
		if len(fields) < 2 {
			continue
		}
		name := strings.ToLower(fields[0])
		version := fields[1]
		key := name + "@" + version
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		deps = append(deps, dependency{Name: name, Version: version, Ecosystem: "go"})
	}
	return deps
}

func parseNodeLock(content string) []dependency {
	type nodePackage struct {
		Version string `json:"version"`
	}
	type lockV3 struct {
		Packages map[string]nodePackage `json:"packages"`
	}
	deps := []dependency{}
	var lock lockV3
	if err := json.Unmarshal([]byte(content), &lock); err != nil {
		return deps
	}
	for key, pkg := range lock.Packages {
		name := strings.TrimPrefix(key, "node_modules/")
		if name == "" || name == "." {
			continue
		}
		deps = append(deps, dependency{Name: strings.ToLower(name), Version: pkg.Version, Ecosystem: "node"})
	}
	return deps
}

func parseCargoLock(content string) []dependency {
	deps := []dependency{}
	var name, version string
	s := bufio.NewScanner(strings.NewReader(content))
	flush := func() {
		if name != "" {
			deps = append(deps, dependency{Name: strings.ToLower(name), Version: version, Ecosystem: "rust"})
		}
		name, version = "", ""
	}
	for s.Scan() {
		line := strings.TrimSpace(s.Text())
		if line == "[[package]]" {
			flush()
			continue
		}
		if strings.HasPrefix(line, "name = ") {
			name = strings.Trim(line[len("name = "):], "\"'")
		}
		if strings.HasPrefix(line, "version = ") {
			version = strings.Trim(line[len("version = "):], "\"'")
		}
	}
	flush()
	return deps
}

func parseConfig(content string) Config {
	cfg := Config{ApprovedRegistries: []string{}, Exemptions: []Exemption{}}
	if strings.TrimSpace(content) == "" {
		return cfg
	}

	// Support JSON config directly to keep API deterministic.
	var jsonCfg map[string]any
	if err := json.Unmarshal([]byte(content), &jsonCfg); err == nil {
		cfg = parseJSONConfig(jsonCfg)
		return cfg
	}

	// Lightweight YAML scanner for key settings used by this example.
	s := bufio.NewScanner(strings.NewReader(content))
	section := ""
	inExemptions := false
	currentEx := Exemption{}

	for s.Scan() {
		line := strings.TrimSpace(s.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		if strings.HasPrefix(line, "profiles:") {
			section = "profiles"
			inExemptions = false
			continue
		}
		if strings.HasPrefix(line, "base_images:") {
			section = "base_images"
			inExemptions = false
			continue
		}
		if strings.HasPrefix(line, "approved_registries:") {
			section = "approved_registries"
			continue
		}
		if strings.HasPrefix(line, "exemptions:") {
			section = "exemptions"
			inExemptions = true
			continue
		}

		if strings.HasPrefix(line, "require_iron_bank:") {
			cfg.RequireIronBank = strings.Contains(strings.ToLower(line), "true")
			continue
		}

		if strings.HasPrefix(line, "- ") {
			val := strings.TrimSpace(strings.TrimPrefix(line, "- "))
			switch section {
			case "profiles":
				cfg.Profiles = append(cfg.Profiles, strings.Trim(val, `"'`))
			case "approved_registries":
				cfg.ApprovedRegistries = append(cfg.ApprovedRegistries, strings.Trim(val, `"'`))
			case "exemptions":
				if currentEx.Package != "" || currentEx.Rule != "" {
					cfg.Exemptions = append(cfg.Exemptions, currentEx)
				}
				currentEx = Exemption{}
				if strings.HasPrefix(val, "package:") {
					currentEx.Package = strings.TrimSpace(strings.TrimPrefix(val, "package:"))
				}
			}
			continue
		}

		if inExemptions {
			if strings.HasPrefix(line, "package:") {
				currentEx.Package = strings.Trim(strings.TrimSpace(strings.TrimPrefix(line, "package:")), `"'`)
			}
			if strings.HasPrefix(line, "rule:") {
				currentEx.Rule = strings.Trim(strings.TrimSpace(strings.TrimPrefix(line, "rule:")), `"'`)
			}
			if strings.HasPrefix(line, "expires:") {
				currentEx.Expires = strings.Trim(strings.TrimSpace(strings.TrimPrefix(line, "expires:")), `"'`)
			}
		}
	}

	if currentEx.Package != "" || currentEx.Rule != "" {
		cfg.Exemptions = append(cfg.Exemptions, currentEx)
	}
	return cfg
}

func parseJSONConfig(data map[string]any) Config {
	cfg := Config{ApprovedRegistries: []string{}, Exemptions: []Exemption{}}

	if profiles, ok := data["profiles"].([]any); ok {
		for _, p := range profiles {
			if s, ok := p.(string); ok {
				cfg.Profiles = append(cfg.Profiles, s)
			}
		}
	}

	if bi, ok := data["base_images"].(map[string]any); ok {
		if req, ok := bi["require_iron_bank"].(bool); ok {
			cfg.RequireIronBank = req
		}
		if regs, ok := bi["approved_registries"].([]any); ok {
			for _, r := range regs {
				if s, ok := r.(string); ok {
					cfg.ApprovedRegistries = append(cfg.ApprovedRegistries, s)
				}
			}
		}
	}

	if exs, ok := data["exemptions"].([]any); ok {
		for _, e := range exs {
			obj, ok := e.(map[string]any)
			if !ok {
				continue
			}
			ex := Exemption{}
			if v, ok := obj["package"].(string); ok {
				ex.Package = v
			}
			if v, ok := obj["rule"].(string); ok {
				ex.Rule = v
			}
			if v, ok := obj["expires"].(string); ok {
				ex.Expires = v
			}
			cfg.Exemptions = append(cfg.Exemptions, ex)
		}
	}

	return cfg
}

func resolveProfiles(single string, multiple []string) []string {
	profiles := []string{}
	if len(multiple) > 0 {
		profiles = append(profiles, multiple...)
	}
	if single != "" {
		profiles = append(profiles, single)
	}
	if len(profiles) == 0 {
		profiles = []string{"all"}
	}

	norm := map[string]struct{}{}
	out := []string{}
	for _, p := range profiles {
		p = strings.TrimSpace(strings.ToLower(p))
		if p == "" {
			continue
		}
		if _, ok := norm[p]; ok {
			continue
		}
		norm[p] = struct{}{}
		out = append(out, p)
	}
	return out
}

func dockerfileBaseImages(content string) []string {
	if strings.TrimSpace(content) == "" {
		return nil
	}
	images := []string{}
	s := bufio.NewScanner(strings.NewReader(content))
	for s.Scan() {
		line := strings.TrimSpace(s.Text())
		m := fromRe.FindStringSubmatch(line)
		if len(m) < 2 {
			continue
		}
		img := m[1]
		img = strings.Split(img, " AS ")[0]
		img = strings.Split(img, " as ")[0]
		images = append(images, strings.TrimSpace(img))
	}
	return images
}

func dockerfileSupportsFIPSPython(dockerfile string, cfg Config, snap RulesSnapshot) bool {
	if strings.TrimSpace(dockerfile) == "" {
		return false
	}
	lower := strings.ToLower(dockerfile)
	hasSourceBuild := strings.Contains(lower, "--no-binary :all:")
	if !hasSourceBuild {
		return false
	}
	baseImages := dockerfileBaseImages(dockerfile)
	for _, img := range baseImages {
		if isFIPSEnabledImage(img, cfg, snap) {
			return true
		}
	}
	return false
}

func isFIPSEnabledImage(img string, cfg Config, snap RulesSnapshot) bool {
	if img == "" {
		return false
	}
	for _, approved := range snap.FIPSEnabledImages {
		if strings.EqualFold(img, approved) {
			return true
		}
	}
	if strings.Contains(strings.ToLower(img), "fips") {
		return true
	}
	if strings.HasPrefix(strings.ToLower(img), "registry1.dso.mil/") {
		return true
	}
	for _, reg := range cfg.ApprovedRegistries {
		if strings.HasPrefix(strings.ToLower(img), strings.ToLower(reg)+"/") {
			return true
		}
	}
	return false
}

func loadSnapshot() RulesSnapshot {
	path := rulesPath()
	b, err := os.ReadFile(path)
	if err != nil {
		return defaultSnapshot()
	}
	var snap RulesSnapshot
	if err := json.Unmarshal(b, &snap); err != nil {
		return defaultSnapshot()
	}
	if snap.TTLHours == 0 {
		snap.TTLHours = 6
	}
	if snap.GeneratedAt == "" {
		snap.GeneratedAt = time.Now().UTC().Format(time.RFC3339)
	}
	return snap
}

func defaultSnapshot() RulesSnapshot {
	now := time.Now().UTC().Format(time.RFC3339)
	return RulesSnapshot{
		GeneratedAt:             now,
		TTLHours:                6,
		IronBankImages:          []string{"registry1.dso.mil/ironbank/opensource/python/python:3.12"},
		FIPSEnabledImages:       []string{"registry1.dso.mil/ironbank/opensource/python/python:3.12", "ubi9/ubi:9.4-fips"},
		CMVPValidatedPackages:   []string{"openssl", "aws-lc-rs", "cryptography"},
		KnownNativeNodePackages: []string{"bcrypt", "better-sqlite3", "canvas", "sharp", "ffi-napi"},
		DeniedPackages: map[string][]string{
			"python": {"pycryptodome", "pynacl", "pyaes", "tink"},
			"rust":   {"ring", "aes", "sha2", "rsa", "ed25519-dalek"},
		},
	}
}

func probeIronBank() error {
	token := strings.TrimSpace(os.Getenv("IRON_BANK_READ_API"))
	if token == "" {
		return fmt.Errorf("token missing")
	}
	client := &http.Client{Timeout: 3 * time.Second}
	req, err := http.NewRequest(http.MethodGet, "https://registry1.dso.mil/v2/", nil)
	if err != nil {
		return err
	}

	if strings.Contains(token, ":") {
		req.Header.Set("Authorization", "Basic "+base64.StdEncoding.EncodeToString([]byte(token)))
	} else {
		req.Header.Set("Authorization", "Bearer "+token)
	}

	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return fmt.Errorf("iron bank probe status %d", resp.StatusCode)
	}
	return nil
}

func isDenied(name, ecosystem string, snap RulesSnapshot) bool {
	name = strings.ToLower(strings.TrimSpace(name))
	ecosystem = strings.ToLower(strings.TrimSpace(ecosystem))
	denied := snap.DeniedPackages[ecosystem]
	for _, d := range denied {
		if name == strings.ToLower(d) {
			return true
		}
	}
	return false
}

func isKnownNativeNodePackage(name string, snap RulesSnapshot) bool {
	for _, p := range snap.KnownNativeNodePackages {
		if strings.EqualFold(name, p) {
			return true
		}
	}
	return false
}

func normalizePkgName(pkg string) string {
	name := strings.TrimSpace(strings.ToLower(pkg))
	for _, sep := range []string{"==", "@", ":"} {
		parts := strings.SplitN(name, sep, 2)
		if len(parts) == 2 {
			return strings.TrimSpace(parts[0])
		}
	}
	return name
}

func isExempt(pkgName, rule string, cfg Config) bool {
	now := time.Now().UTC()
	for _, ex := range cfg.Exemptions {
		matchRule := strings.EqualFold(ex.Rule, rule) || ex.Rule == ""
		matchPkg := strings.EqualFold(ex.Package, pkgName) || ex.Package == ""
		if !matchRule || !matchPkg {
			continue
		}
		if ex.Expires == "" {
			return true
		}
		exp, err := time.Parse("2006-01-02", ex.Expires)
		if err != nil {
			continue
		}
		if exp.After(now) {
			return true
		}
	}
	return false
}

func uniqueDeps(in []dependency) []dependency {
	out := []dependency{}
	seen := map[string]struct{}{}
	for _, d := range in {
		key := d.Ecosystem + ":" + d.Name + "@" + d.Version
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		out = append(out, d)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}

func dedupeFindings(in []Finding) []Finding {
	out := []Finding{}
	seen := map[string]struct{}{}
	for _, f := range in {
		key := f.ID + ":" + f.Package + ":" + f.Message
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		out = append(out, f)
	}
	return out
}

func hasEcosystem(deps []dependency, ecosystem string) bool {
	for _, d := range deps {
		if d.Ecosystem == ecosystem {
			return true
		}
	}
	return false
}

func evalMode() string {
	if strings.EqualFold(os.Getenv("COMPLIANCE_ALLOW_REMOTE"), "true") {
		return "hybrid"
	}
	return "local-only"
}

func profileDelta(reasonCount int) string {
	if reasonCount == 0 {
		return "no-risk-increase"
	}
	return "risk-increases-" + strconv.Itoa(reasonCount)
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	buf := &bytes.Buffer{}
	enc := json.NewEncoder(buf)
	enc.SetIndent("", "  ")
	if err := enc.Encode(v); err != nil {
		http.Error(w, `{"error":"json encode failure"}`+err.Error(), http.StatusInternalServerError)
		return
	}
	_, _ = w.Write(buf.Bytes())
}
