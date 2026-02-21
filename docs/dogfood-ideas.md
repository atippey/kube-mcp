# Dogfooding Ideas

MCP tool ideas to exercise the operator while solving real project needs.

---

## 1. Documentation Tool (docs-tool)

**Goal**: K8s-style documentation site for the operator — API reference, concept pages, and task walkthroughs. Think ReadTheDocs or kubernetes.io/docs.

### Output: Static docs site (MkDocs Material or similar)

Three layers of content:

1. **API Reference** (auto-generated from CRD schemas)
   - Per-CRD pages: MCPServer, MCPTool, MCPPrompt, MCPResource
   - Field tables: name, type, required/optional, constraints, description
   - Nested objects expandable (like `kubectl explain --recursive` but rendered)
   - Source: `manifests/base/crds/*.yaml` OpenAPI schemas + `src/models/crds.py` Pydantic models

2. **Concept Pages** (semi-generated, human-edited)
   - "What is an MCPServer?" — purpose, what it manages (Deployment, Service, Ingress, ConfigMap, NetworkPolicy)
   - "How tool discovery works" — label selectors, ConfigMap aggregation, service resolution
   - "NetworkPolicy model" — fail-open → controller-managed egress, cross-namespace access
   - Source: CLAUDE.md architecture section, code comments, README

3. **Task Walkthroughs** (authored with generated YAML examples)
   - "Deploy your first MCP tool"
   - "Set up cross-namespace access"
   - "Configure multi-tool CRs"
   - "Monitor with Prometheus metrics"
   - Source: `examples/` directory, real working manifests

### MCP Tool Role: Docs pipeline / generator

The tool doesn't *serve* docs at runtime — it *generates and maintains* them:
- Parse CRD schemas → generate API reference Markdown
- Scaffold concept/walkthrough page templates
- Generate release notes from git tags/commits/PRs
- Regenerate on CRD schema changes (CI integration)

### Open Questions

- **Static site generator**: MkDocs Material (Python, ReadTheDocs feel) vs Hugo (Go, faster builds)?
- **Hosting**: GitHub Pages vs in-cluster serving?
- **Release notes**: Git-based (conventional commits) vs GitHub API (PR-based)?
- **Dev blog**: Part of this tool or separate concern?

---

## 2. Compliance Guardian (compliance-tool)

**Goal**: A general-purpose MCP tool (not kube-mcp specific) that any security-sensitive project can deploy to maintain SBOM state, enforce compliance profiles (FIPS 140-3, STIG, FedRAMP), and gate dependency changes with a `can-i` check before they land. Dogfoods the operator while building something independently useful.

### The Problem

Compliance is typically checked after the fact — you add a library, ship it, then an auditor flags it months later. For regulated environments (DoD, FedRAMP, healthcare), you need:
- Continuous knowledge of every component in your supply chain (SBOM)
- Proof that cryptographic operations use validated modules (FIPS)
- Evidence that hardening baselines are met (STIG)
- A way to prevent regression before merge, not after deploy

### Compliance Profiles

The tool enforces rules organized by compliance framework. A project declares its required profile(s) (e.g., in `compliance.yaml` or AGENTS.md), and the tool evaluates against them.

**FIPS 140-3** (Cryptographic module validation)
- Allowlist of FIPS-validated crypto libraries (e.g., OpenSSL 3.x FIPS provider, AWS-LC, BoringCrypto)
- Denylist of non-validated crypto (pure-Python crypto, PyCryptodome in non-FIPS mode, old OpenSSL)
- Flag transitive dependencies that pull in non-validated crypto (e.g., `paramiko` → `cryptography` → check OpenSSL linkage)
- Check container base image for FIPS-enabled runtime (e.g., UBI FIPS, Amazon Linux FIPS)

**STIG** (Security Technical Implementation Guides)
- Container hardening: non-root user, read-only root filesystem, no privileged escalation, dropped capabilities
- Image provenance: signed images, known base image, no `:latest` tags in production
- Network: deny-by-default NetworkPolicy, no host networking
- Secrets: no hardcoded credentials, secrets via K8s Secrets or external vault
- Logging: audit-level structured logging enabled

**FedRAMP / NIST 800-53** (broader controls)
- Supply chain: all dependencies have known provenance, SBOM is current
- Vulnerability management: no known CVEs above threshold (CRITICAL/HIGH)
- Access control: RBAC least privilege, service account scoping

### Design Decisions

- **Multi-ecosystem from day one**: Python (`poetry.lock`, `requirements.txt`), Go (`go.sum`), Node (`package-lock.json`), Rust (`Cargo.lock`). Each is just a lockfile parser — the hard part is the rule engine, not the parsing.
- **Always in-cluster**: Runs as an MCP tool on the operator. A thin CLI wrapper (`compliance-cli`) and Makefile targets provide the human/CI interface, calling the in-cluster service.
- **Rules fetched at runtime, cached with TTL**: Rule databases (CMVP, CVE, STIG checklists) fetched from upstream sources on startup and refreshed every 6 hours (configurable). Cached in Redis (already available via the operator's Redis instance).
- **Iron Bank integration**: Access to `registry1.dso.mil` for authoritative "is this base image approved" checks. Iron Bank images are pre-hardened and STIG-compliant — the tool can validate that a project's Dockerfile `FROM` references an Iron Bank image.

### Project Configuration

Each project declares compliance requirements in `.compliance.yaml` at the repo root:

```yaml
# .compliance.yaml
version: "1"
profiles:
  - fips-140-3
  - stig-container

ecosystems:
  - python    # reads poetry.lock / requirements.txt
  - go        # reads go.sum
  # - node    # reads package-lock.json
  # - rust    # reads Cargo.lock

thresholds:
  max_critical_cves: 0
  max_high_cves: 5

base_images:
  # Approved base images for this project
  approved_registries:
    - registry1.dso.mil      # Iron Bank
    - ghcr.io/atippey         # org images
  require_iron_bank: false    # true = only Iron Bank images allowed

exemptions:
  - package: urllib3
    version: "<2.0"
    profiles: [fips-140-3]
    reason: "Pinned by kubernetes client, tracked in issue #42"
    expires: 2025-06-01
    approved_by: "atippey"

  - rule: STIG-IMG-001
    reason: "Using :latest in dev overlay only, production uses pinned tags"
    scope: "manifests/overlays/dev/"
    expires: 2025-12-31
```

### Lockfile Parsers

Each ecosystem has a parser that produces a normalized dependency list:

```
Dependency {
  name: string
  version: string
  ecosystem: "python"|"go"|"node"|"rust"
  direct: bool              # direct vs transitive
  source: string            # registry URL or VCS
  hashes: []string          # integrity hashes from lockfile
  license: string           # SPDX identifier (resolved from registry metadata)
  categories: []string      # ["crypto", "network", "serialization", ...] — for rule matching
}
```

**Parser specifics**:
- **Python** (`poetry.lock`): TOML format, has `[metadata.files]` with hashes, `category` field distinguishes main/dev. Also parse `requirements.txt` (pip freeze format, no tree).
- **Go** (`go.sum`): Has cryptographic hashes per module. Cross-reference `go.mod` for direct vs indirect. Go's module proxy (`proxy.golang.org`) provides metadata.
- **Node** (`package-lock.json`): JSON, v3 format has `resolved` URLs and `integrity` SRI hashes. `dev`/`optional` flags for filtering.
- **Rust** (`Cargo.lock`): TOML v3 format, has `checksum` per package. Cross-reference `Cargo.toml` for direct deps.

### Tool Endpoints

```
POST /sbom/generate
  Input: {
    lockfiles: [                              # one or more lockfile contents
      { ecosystem: "python", content: "..." },
      { ecosystem: "go", content: "..." }
    ],
    format: "spdx"|"cyclonedx",              # output format
    include_transitive: true                  # include full dep tree
  }
  Output: SBOM document in requested format
  - Parses each lockfile into normalized dependencies
  - Resolves license metadata from registry APIs (cached)
  - Outputs SPDX 2.3 or CycloneDX 1.5 JSON

POST /sbom/diff
  Input: {
    base: { ecosystem: "python", content: "<poetry.lock from main>" },
    head: { ecosystem: "python", content: "<poetry.lock from PR branch>" }
  }
  Output: {
    added:   [{ name: "pyjwt", version: "2.8.0", license: "MIT", categories: ["crypto"] }],
    removed: [{ name: "old-lib", version: "1.0" }],
    changed: [{ name: "requests", from: "2.30", to: "2.31" }],
    risk_summary: {
      new_crypto_deps: 1,         # flag for FIPS review
      license_changes: [],
      cve_introductions: []
    }
  }

POST /compliance/check
  Input: {
    profile: "fips"|"stig"|"fedramp"|"all",
    lockfiles: [{ ecosystem: "python", content: "..." }],
    manifests: ["<deployment YAML>", ...],     # K8s manifests for STIG checks
    dockerfile: "FROM python:3.12-alpine...",   # for base image checks
    config: "<.compliance.yaml content>"        # project config with exemptions
  }
  Output: {
    compliant: false,
    profile: "fips-140-3",
    score: { passed: 14, failed: 2, exempted: 1, total: 17 },
    findings: [
      {
        id: "FIPS-CRYPTO-002",
        severity: "CRITICAL",
        category: "dependency",
        package: "pycryptodome==3.20",
        message: "Non-FIPS-validated crypto library",
        remediation: "Replace with 'cryptography' package using FIPS provider",
        references: ["https://csrc.nist.gov/projects/cryptographic-module-validation-program"]
      }
    ],
    exemptions_applied: [
      { rule: "FIPS-CRYPTO-001", package: "urllib3", reason: "...", expires: "2025-06-01" }
    ]
  }

POST /compliance/can-i
  Input: {
    action: "add-dependency",
    ecosystem: "python",
    package: "paramiko==3.4",
    current_lockfile: "...",                   # current state
    profiles: ["fips-140-3", "stig-container"],
    config: "<.compliance.yaml>"
  }
  Output: {
    allowed: false,
    package: "paramiko==3.4",
    reasons: [
      {
        profile: "fips-140-3",
        rule: "FIPS-CRYPTO-001",
        message: "paramiko depends on cryptography which requires FIPS-validated OpenSSL. Your base image (python:3.12-alpine) does not include FIPS OpenSSL provider.",
        transitive_chain: ["paramiko", "cryptography", "OpenSSL (system)"],
        severity: "HIGH"
      }
    ],
    alternatives: [
      {
        package: "paramiko==3.4",
        condition: "Switch base image to registry1.dso.mil/ironbank/opensource/python/python:3.12 (includes FIPS OpenSSL)",
        impact: "FIPS-compliant, but increases image size ~200MB"
      },
      {
        package: "fabric==3.2",
        condition: "Uses paramiko internally — same FIPS constraint applies",
        impact: "No improvement"
      }
    ],
    profile_impact: {
      "fips-140-3": { before: "87%", after: "80%" },
      "stig-container": { before: "100%", after: "100%" }
    }
  }

POST /compliance/can-i
  Input: {
    action: "change-base-image",
    current: "python:3.12-alpine",
    proposed: "registry1.dso.mil/ironbank/opensource/python/python:3.12",
    profiles: ["fips-140-3", "stig-container"]
  }
  Output: {
    allowed: true,
    improvements: [
      { profile: "fips-140-3", rule: "FIPS-BASE-001", message: "Iron Bank image includes FIPS-validated OpenSSL 3.x" },
      { profile: "stig-container", rule: "STIG-IMG-002", message: "Iron Bank images are pre-hardened and STIG-compliant" }
    ],
    profile_impact: {
      "fips-140-3": { before: "80%", after: "95%" },
      "stig-container": { before: "90%", after: "100%" }
    }
  }

POST /compliance/report
  Input: {
    profiles: ["fips-140-3", "stig-container"],
    format: "markdown"|"json"|"sarif",
    lockfiles: [...],
    manifests: [...],
    config: "<.compliance.yaml>"
  }
  Output: Full compliance report suitable for auditor review
  - Executive summary with pass/fail/exempted counts per profile
  - Per-control findings with evidence and references
  - Exemption inventory with expiration dates
  - Remediation roadmap (ordered by severity × effort)
  - SARIF format option for GitHub Code Scanning integration

POST /rules/status
  Input: {}
  Output: {
    rule_sources: [
      { name: "NIST CMVP", last_fetched: "2025-02-16T10:00:00Z", next_refresh: "2025-02-16T16:00:00Z", entries: 4231 },
      { name: "OSV.dev", last_fetched: "2025-02-16T10:00:00Z", entries: 289341 },
      { name: "Iron Bank catalog", last_fetched: "2025-02-16T10:00:00Z", approved_images: 812 },
      { name: "STIG checklists", version: "V2R1", entries: 87 }
    ],
    cache_backend: "redis",
    ttl_hours: 6
  }

POST /rules/refresh
  Input: { source: "all"|"cmvp"|"osv"|"ironbank"|"stig" }
  Output: { refreshed: true, duration: "12s", changes: { added: 3, updated: 15, removed: 0 } }
```

### Rule Engine

Rules are declarative YAML. Shipped with the tool image as defaults, but overridable via ConfigMap mount at `/etc/compliance/rules/`.

```yaml
# rules/fips-140-3.yaml
profile: fips-140-3
version: "1.0"
description: "FIPS 140-3 cryptographic module validation"
rules:

  - id: FIPS-CRYPTO-001
    severity: HIGH
    description: "Crypto libraries must use FIPS-validated module"
    check: dependency
    match:
      categories: ["crypto"]
    condition: |
      package.name in cmvp_validated_packages
      OR (package.name == "cryptography" AND base_image in fips_enabled_images)
    remediation: "Use FIPS-validated crypto. See https://csrc.nist.gov/projects/cmvp"

  - id: FIPS-CRYPTO-002
    severity: CRITICAL
    description: "Non-validated crypto libraries are not permitted"
    check: dependency
    denylist:
      - { name: "pycryptodome", unless: "fips_mode == true" }
      - { name: "pynacl", reason: "uses libsodium, not FIPS-validated" }
      - { name: "pyaes", reason: "pure Python AES, not validated" }
      - { name: "tink", reason: "Google Tink not on CMVP list" }
    remediation: "Replace with 'cryptography' package using FIPS provider"

  - id: FIPS-BASE-001
    severity: HIGH
    description: "Container base image must support FIPS crypto"
    check: dockerfile
    condition: |
      base_image in ironbank_catalog
      OR base_image matches ".*-fips$"
      OR base_image in fips_enabled_images
    data_sources: [ironbank_catalog, fips_enabled_images]
    remediation: "Use an Iron Bank base image from registry1.dso.mil"

  - id: FIPS-TLS-001
    severity: HIGH
    description: "TLS libraries must use FIPS-validated implementations"
    check: dependency
    match:
      categories: ["tls", "ssl"]
    condition: |
      NOT (package.name in ["pyOpenSSL"] AND openssl_version < "3.0")
    remediation: "Ensure OpenSSL >= 3.0 with FIPS provider enabled"

# rules/stig-container.yaml
profile: stig-container
version: "V2R1"
description: "DISA STIG for Container Deployment"
source: "https://public.cyber.mil/stigs/"
rules:

  - id: STIG-CTR-001
    severity: CAT-I    # STIG uses CAT-I/II/III instead of HIGH/MEDIUM/LOW
    stig_id: "V-242391"
    description: "Container must not run as root"
    check: manifest
    path: spec.template.spec.securityContext
    condition: "runAsNonRoot == true AND runAsUser > 0"
    fix_id: "F-45612r863839_fix"

  - id: STIG-CTR-002
    severity: CAT-I
    stig_id: "V-242392"
    description: "Privilege escalation must be disabled"
    check: manifest
    path: spec.template.spec.containers[*].securityContext
    condition: "allowPrivilegeEscalation == false"

  - id: STIG-CTR-003
    severity: CAT-I
    stig_id: "V-242395"
    description: "Container must use approved base image"
    check: dockerfile
    condition: |
      base_image_registry in approved_registries
    data_sources: [ironbank_catalog]
    remediation: "Use Iron Bank image from registry1.dso.mil"

  - id: STIG-CTR-004
    severity: CAT-II
    stig_id: "V-242396"
    description: "Container image must be signed"
    check: image
    condition: "image.signatures.length > 0 OR image.cosign_verified == true"
    remediation: "Sign image with cosign: cosign sign <image>"

  - id: STIG-CTR-005
    severity: CAT-II
    stig_id: "V-242400"
    description: "Containers must drop all capabilities"
    check: manifest
    path: spec.template.spec.containers[*].securityContext.capabilities
    condition: "drop contains 'ALL'"

  - id: STIG-NET-001
    severity: CAT-II
    stig_id: "V-242410"
    description: "NetworkPolicy must exist with deny-by-default"
    check: manifest
    kind: NetworkPolicy
    condition: "policyTypes contains 'Ingress' AND policyTypes contains 'Egress'"

  - id: STIG-IMG-001
    severity: CAT-II
    description: "Production images must not use :latest tag"
    check: manifest
    path: spec.template.spec.containers[*].image
    condition: "tag != 'latest' AND tag != ''"
    scope: "production"   # only enforced when scope matches
```

### Package Category Database

The rule engine needs to know "does this package do crypto?" to evaluate FIPS rules. Maintained as a categorized lookup:

```yaml
# data/package-categories.yaml (fetched + cached, community-maintained)
python:
  cryptography: [crypto, tls]
  pycryptodome: [crypto]
  pynacl: [crypto]
  paramiko: [ssh, crypto]       # transitive crypto via cryptography
  pyOpenSSL: [tls, crypto]
  certifi: [tls]                # CA bundle only, no crypto operations
  requests: [http]              # no direct crypto
  urllib3: [http, tls]          # uses system OpenSSL

go:
  crypto/tls: [crypto, tls]     # stdlib
  golang.org/x/crypto: [crypto]
  github.com/cloudflare/circl: [crypto]

node:
  crypto: [crypto]              # builtin
  node-forge: [crypto]
  bcrypt: [crypto]

rust:
  ring: [crypto]
  rustls: [tls, crypto]
  openssl: [crypto, tls]
```

### Iron Bank Integration

The tool queries Iron Bank's catalog to validate base images:

```
Iron Bank API: registry1.dso.mil/v2/_catalog
Authentication: via robot account or service account token (mounted as K8s Secret)

Cached data structure:
{
  "images": {
    "ironbank/opensource/python/python:3.12": {
      "approved": true,
      "stig_compliant": true,
      "fips_enabled": true,
      "last_scan": "2025-02-15",
      "cves": { "critical": 0, "high": 0 }
    },
    ...
  },
  "last_refreshed": "2025-02-16T10:00:00Z"
}
```

For projects that set `require_iron_bank: true`, every `FROM` in the Dockerfile must reference a `registry1.dso.mil` image.

### CI Integration

**GitHub Actions** — compliance gate on PRs:

```yaml
# .github/workflows/compliance.yml
name: Compliance Check
on:
  pull_request:
    paths:
      - 'poetry.lock'
      - 'go.sum'
      - 'package-lock.json'
      - 'Cargo.lock'
      - 'Dockerfile'
      - 'manifests/**'

jobs:
  compliance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0    # need full history for diff

      - name: Compliance diff check
        run: |
          # Collect changed lockfiles
          CHANGED=$(git diff --name-only origin/main -- poetry.lock go.sum package-lock.json Cargo.lock)

          for lockfile in $CHANGED; do
            ECOSYSTEM=$(compliance-cli detect-ecosystem "$lockfile")
            BASE_CONTENT=$(git show origin/main:"$lockfile" 2>/dev/null || echo "")
            HEAD_CONTENT=$(cat "$lockfile")

            compliance-cli sbom-diff \
              --ecosystem "$ECOSYSTEM" \
              --base "$BASE_CONTENT" \
              --head "$HEAD_CONTENT" \
              --profiles fips-140-3,stig-container \
              --config .compliance.yaml \
              --fail-on-violation
          done

      - name: Full compliance report
        if: always()
        run: |
          compliance-cli check \
            --profiles all \
            --config .compliance.yaml \
            --format sarif \
            --output compliance-results.sarif

      - name: Upload SARIF
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: compliance-results.sarif
```

**CLI wrapper** (`compliance-cli`) — thin HTTP client that calls the in-cluster service:

```bash
# Check if you can add a dependency
compliance-cli can-i add-dep paramiko==3.4 --ecosystem python --profile fips

# Generate SBOM from local lockfiles
compliance-cli sbom generate --lockfile poetry.lock --format spdx

# Run full compliance check
compliance-cli check --profiles all --config .compliance.yaml

# Check rule database freshness
compliance-cli rules status
```

**Makefile targets**:
```makefile
compliance-check:    ## Run compliance check against all profiles
	compliance-cli check --profiles all --config .compliance.yaml

compliance-sbom:     ## Generate SBOM from lockfiles
	compliance-cli sbom generate --lockfile poetry.lock --format spdx -o sbom.spdx.json

compliance-can-i:    ## Check if a dependency addition is compliant (usage: make compliance-can-i PKG=paramiko==3.4)
	compliance-cli can-i add-dep $(PKG) --ecosystem python --profile fips
```

**AGENTS.md instruction**:
> Before adding any new dependency to any ecosystem, check compliance:
> `compliance-cli can-i add-dep <package>==<version> --ecosystem <python|go|node|rust> --profile fips`
> If the tool reports `allowed: false`, do not add the dependency without an approved exemption in `.compliance.yaml`.

### Data Sources & Caching

All external data is fetched at startup and cached in Redis with configurable TTL (default 6 hours):

| Source | URL / Method | Data | Refresh |
|--------|-------------|------|---------|
| NIST CMVP | `csrc.nist.gov/projects/cmvp` API | Validated crypto modules list | 6h |
| OSV.dev | `api.osv.dev/v1/query` | CVE/vulnerability database | 6h |
| Iron Bank catalog | `registry1.dso.mil/v2/_catalog` | Approved hardened images | 6h |
| DISA STIG checklists | Bundled YAML (versioned with tool) | Container/K8s STIG rules | On image release |
| Package categories | Bundled YAML + community feed | Ecosystem → category mapping | 6h |
| PyPI/npm/crates.io | Registry APIs | License metadata | 24h |

Redis cache keys:
```
compliance:cmvp:validated_modules    → JSON list, TTL 6h
compliance:osv:python:*              → per-package CVE data, TTL 6h
compliance:ironbank:catalog          → approved images, TTL 6h
compliance:categories:python         → package categories, TTL 6h
compliance:licenses:python:requests  → license info, TTL 24h
```

### Architecture

```
┌──────────────────────────────────────────────────┐
│  compliance-tool pod                              │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │  HTTP server (Go, :8080)                    │ │
│  │                                             │ │
│  │  ┌──────────┐ ┌──────────┐ ┌─────────────┐│ │
│  │  │ Lockfile  │ │ Rule     │ │ Report      ││ │
│  │  │ Parsers   │ │ Engine   │ │ Generator   ││ │
│  │  │ py/go/    │ │ evaluate │ │ md/json/    ││ │
│  │  │ node/rust │ │ rules vs │ │ sarif       ││ │
│  │  └──────────┘ │ deps     │ └─────────────┘│ │
│  │               └──────────┘                 │ │
│  │                    │                       │ │
│  │  ┌─────────────────▼────────────────────┐ │ │
│  │  │  Cache Layer (Redis)                 │ │ │
│  │  │  CMVP | OSV | Iron Bank | Categories │ │ │
│  │  └─────────────────────────────────────-┘ │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  ConfigMap mount: /etc/compliance/rules/          │
│  Secret mount: /etc/compliance/secrets/           │
│    (Iron Bank robot account, registry creds)      │
└──────────────────────────────────────────────────┘
         │
         ▼ Redis (mcp-redis in same namespace)
```

**Language: Go** — Syft and Trivy are both Go libraries, and the lockfile parsers are straightforward. The CLI wrapper is also Go (single binary distribution).

### Dogfooding Value

Exercises the operator while building a standalone product:
- **Multi-tool CR**: 7 endpoints (sbom/generate, sbom/diff, compliance/check, compliance/can-i, compliance/report, rules/status, rules/refresh)
- **Stateful**: Redis cache for rule databases, CMVP lookups, Iron Bank catalog
- **Secret management**: Iron Bank credentials via K8s Secrets
- **CI integration**: Tests the tool-as-a-service pattern from outside the cluster
- **Independently deployable**: Any team with the operator can drop this in to gate their own projects
- **Enterprise credibility**: Compliance + Iron Bank + STIG is exactly what regulated shops need

### MVP Scope

**Phase 1** (MVP):
- Lockfile parsers: Python + Go
- `can-i` endpoint with FIPS profile
- `compliance/check` with FIPS + STIG-container profiles
- `.compliance.yaml` config with exemptions
- CMVP + OSV data sources with Redis caching
- CLI wrapper with `can-i` and `check` commands
- Basic SBOM generation (SPDX)

**Phase 2**:
- Node + Rust lockfile parsers
- Iron Bank integration
- SARIF output for GitHub Code Scanning
- `sbom/diff` endpoint
- Full STIG checklist (not just container)
- Compliance report generation (auditor-ready markdown)

**Phase 3**:
- FedRAMP / NIST 800-53 profile
- Image scanning mode (Syft integration for container layer analysis)
- Cosign signature verification
- Custom profile support (bring your own rules)
- Dashboard / Prometheus metrics on compliance posture

---

## 3. Local CI Runner (act-tool)

**Goal**: An MCP tool wrapping [nektos/act](https://github.com/nektos/act) to run GitHub Actions workflows locally. Stop pushing to find out your CI is broken.

### The Problem

The feedback loop for CI changes is painful:
- Push → wait for GitHub runners → read logs → fix → push again
- Workflow syntax errors, missing env vars, wrong paths — all discoverable locally
- Testing workflow changes on a branch pollutes commit history with "fix CI" commits
- `act` exists but has enough flags and quirks that people don't reach for it

### Tool Endpoints

```
POST /ci/run
  Input: {
    workflow: ".github/workflows/ci.yml",   # or "ci" to fuzzy-match
    job: "test",                             # optional, run specific job
    event: "push",                           # push, pull_request, etc.
    secrets: { "GITHUB_TOKEN": "..." },      # optional, from K8s Secret
    env: { "PYTHON_VERSION": "3.12" },       # override env vars
    platform: "ubuntu-latest=catthehacker/ubuntu:act-latest",
    dryrun: false
  }
  Output: {
    success: true,
    jobs: [
      { name: "test", status: "pass", duration: "45s",
        steps: [
          { name: "Run unit tests", status: "pass", duration: "30s" },
          ...
        ]},
    ],
    logs: "...",              # full output
    artifacts: [...]          # any uploaded artifacts
  }

POST /ci/list
  Input: { path: ".github/workflows/" }
  Output: {
    workflows: [
      { file: "ci.yml", name: "CI", jobs: ["lint", "typecheck", "test", "build-operator", ...],
        triggers: ["push:main", "pull_request:main", "tags:v*"] },
      ...
    ]
  }
  - Parses workflow YAML, shows what's available without running anything

POST /ci/validate
  Input: { workflow: ".github/workflows/ci.yml" }
  Output: {
    valid: true,
    warnings: [
      "Job 'build-operator' uses 'needs: [lint, typecheck, test]' — will run sequentially in act",
      "Action 'docker/build-push-action@v6' may behave differently locally (no GHCR push)"
    ],
    unsupported: [
      "codecov/codecov-action@v5 — requires CODECOV_TOKEN, will be skipped"
    ]
  }
  - Static analysis of the workflow for act compatibility issues
  - Flags actions known to need real GitHub context

POST /ci/diff
  Input: { base: "main", head: "HEAD" }
  Output: {
    workflows_changed: [".github/workflows/ci.yml"],
    jobs_affected: ["build-operator", "build-echo-server"],
    recommendation: "Run 'build-operator' job locally — Dockerfile changed"
  }
  - Looks at what files changed and maps to affected workflow jobs
  - Smart about trigger paths (e.g., "src/ changed → test job matters")

POST /ci/secrets
  Input: { workflow: "ci.yml" }
  Output: {
    required: ["GITHUB_TOKEN"],
    optional: ["CODECOV_TOKEN"],
    available: ["GITHUB_TOKEN"],     # from mounted K8s Secret
    missing: ["CODECOV_TOKEN"]
  }
  - Introspects workflow for secrets references
  - Checks what's available in the tool's environment
```

### Architecture

The tool server needs Docker access (act runs workflows in containers):

```
┌─────────────────────────────┐
│  act-tool pod               │
│  ┌───────────────────────┐  │
│  │ HTTP server (:8080)   │  │
│  │  - parses requests    │  │
│  │  - invokes act CLI    │  │
│  │  - streams output     │  │
│  └───────┬───────────────┘  │
│          │ exec              │
│  ┌───────▼───────────────┐  │
│  │ act binary            │  │
│  │  - reads .github/     │  │
│  │  - pulls action imgs  │  │
│  │  - runs in DinD/DooD  │  │
│  └───────────────────────┘  │
└─────────────────────────────┘
```

**Docker access options**:
- **DinD (Docker-in-Docker)**: Sidecar container running dockerd. Isolated, no host access. Heavier.
- **DooD (Docker-outside-of-Docker)**: Mount host's `/var/run/docker.sock`. Lighter, but requires host trust.
- **Buildkit only**: For workflows that just build images, use buildkit daemon instead.

**Repo access**: Mount the repo as a volume or clone from a Git URL. For in-cluster use, could watch a PVC or use a git-sync sidecar.

### Smart Features

**Workflow-to-file mapping** — knows which jobs to suggest based on changed files:
```yaml
# Inferred from workflow trigger paths + step commands
mappings:
  "src/**/*.py":        [lint, typecheck, test]
  "tests/**":           [test, integration-test]
  ".github/workflows/": [lint]  # validate the workflow itself
  "Dockerfile":         [build-operator, security-scan]
  "poetry.lock":        [test, build-operator]
  "manifests/**":       []      # no CI job for manifests currently
  "charts/**":          []      # TODO: helm lint job
```

**Act quirks handled transparently**:
- Matrix strategies: expand and show which combos will run
- Service containers: map to act's `--container-architecture`
- Caching: `actions/cache` doesn't work in act — tool warns and suggests `--reuse`
- Secrets: auto-inject from K8s Secrets if available, prompt for missing

### Dogfooding Value

- **Docker-in-Docker**: Exercises the operator's ability to handle privileged/sidecar workloads
- **Volume mounts**: Tests ConfigMap + PVC patterns (repo checkout, act cache)
- **Practical daily use**: Every push to this project could be pre-validated locally
- **NetworkPolicy challenge**: act needs to pull container images — tests egress rules for registries
- **Multi-tool CR**: list, run, validate, diff, secrets endpoints

### Open Questions

- **Docker access model**: DinD sidecar (safer) vs host socket mount (simpler)?
- **Repo source**: Git clone at runtime vs mounted workspace vs both?
- **Streaming**: act output can be long-running — SSE/WebSocket for live logs, or poll?
- **Resource limits**: act can consume significant CPU/memory — how to cap?
- **Language**: Go (act is Go, could embed as library) vs shell wrapper?

---

## 4. (next idea)

---
