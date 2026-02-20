# Task: Review & Refine the Compliance Guardian (SBOM/FIPS Policy Tool)

## Context

We're designing a general-purpose MCP tool called **compliance-tool** that enforces SBOM state, FIPS 140-3, STIG, and FedRAMP compliance profiles. It's not specific to this project — any security-sensitive project can deploy it via the kube-mcp operator.

The full design spec is in [`docs/dogfood-ideas.md`](docs/dogfood-ideas.md) under **Section 2: Compliance Guardian**. Read that first.

## What We Need From You

Review the compliance-tool design with a critical eye. Specifically:

### 1. FIPS Enforcement Strategies (Per-Ecosystem)

We've discussed but not yet codified these ecosystem-specific FIPS enforcement approaches. Evaluate whether they're sound and identify gaps:

- **Python**: Force source build (`pip install --no-binary :all:`) on a FIPS-enabled base image (Iron Bank UBI or similar). If a package links against non-FIPS OpenSSL, the build itself fails. This makes the base image the enforcement mechanism — no need to maintain a package allowlist for Python.

- **Go**: Use `GOEXPERIMENT=boringcrypto` build flag. This replaces Go's stdlib `crypto/*` with BoringCrypto (FIPS-validated) at compile time. The tool should check that this flag is set in the build environment / Dockerfile.

- **Node**: Ban ALL binary/native dependencies (anything with `binding.gyp` or native addons) in FIPS mode. Node's crypto story for FIPS is too fragmented — the safest approach is no native deps at all. The tool should scan `package-lock.json` for packages known to have native bindings.

- **Rust**: Denylist `ring` and RustCrypto crates. Require `aws-lc-rs` (FIPS-validated, used by AWS) or `openssl` crate with FIPS feature flag. The tool should check `Cargo.lock` for denied crates and verify the approved alternative is present.

**Questions**: Are these strategies correct? What edge cases do they miss? Are there better approaches for any ecosystem?

### 2. Rule Engine Design

The current rule engine uses a pseudo-code `condition` syntax in YAML (see the spec). This needs to be actually implementable.

- Is a custom DSL the right call, or should we use an existing policy engine (OPA/Rego, CEL, CUE)?
- How complex do conditions actually need to be? Could we get away with a simpler allowlist/denylist model instead of arbitrary expressions?
- The `data_sources` field references external data (CMVP, Iron Bank) — how should the engine resolve these at evaluation time?

### 3. Iron Bank API

The spec assumes `registry1.dso.mil/v2/_catalog` for the Iron Bank catalog. This may not be the right API.

- What's the actual way to query Iron Bank for approved/hardened images programmatically?
- Is there a public API, or does it require Harbor registry API calls?
- How do you check if a specific image is STIG-compliant or FIPS-enabled?

### 4. Architecture & Language Choice

The spec says Go because Syft/Trivy are Go libraries. But consider:

- The lockfile parsers (TOML, JSON) are trivial in any language
- The rule engine might be simpler in Python (existing OPA/policy libraries, less boilerplate)
- The CLI wrapper being a single Go binary is nice, but `compliance-cli` could also be a Python package or even a shell script calling curl
- The operator ecosystem is Python (kopf) — would staying in Python reduce friction?

### 5. General Design Gaps

- Is the `can-i` endpoint too ambitious for MVP? It requires transitive dependency resolution and alternative suggestion logic.
- The package category database (`data/package-categories.yaml`) is a maintenance burden. Is there a better way to determine "does this package do crypto?"
- How should the tool handle multi-stage Dockerfiles for base image checks?
- The exemption system has `expires` dates — who enforces expiration? The tool at check time, or CI?

## Constraints

- This is a design review, not implementation. Don't write code — write feedback.
- Be specific about what's wrong and what would be better.
- If you think a section is solid, say so briefly and move on.
- The FIPS enforcement strategies are the highest priority review item.

## Reference Files

- [`docs/dogfood-ideas.md`](docs/dogfood-ideas.md) — Full spec (Section 2)
- [`manifests/base/network-policy.yaml`](manifests/base/network-policy.yaml) — Example of how this project does NetworkPolicy (for STIG context)
- [`.github/workflows/ci.yml`](.github/workflows/ci.yml) — Current CI (for CI integration context)
- [`Dockerfile`](Dockerfile) — Current Dockerfile (for base image/FIPS context)
