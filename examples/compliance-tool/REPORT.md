# Compliance Tool Report

## What Was Implemented
- New Go example tool at `examples/compliance-tool`.
- Endpoints:
  - `POST /compliance/can-i`
  - `POST /compliance/check`
  - `GET|POST /rules/status`
  - `GET /health`
- Lockfile parsing for Python, Go, Node, Rust (lightweight parsers).
- Local-first evaluation mode (`COMPLIANCE_ALLOW_REMOTE=false` by default).
- Bundled rules snapshot: `data/rules-snapshot.json`.
- Optional Iron Bank probe using `IRON_BANK_READ_API`.
- Signed offline bundle workflow:
  - `POST /rules/export` signs current rules snapshot with HMAC.
  - `POST /rules/import` verifies signature and updates local snapshot.
- Kubernetes manifests and MCPTool resources in `manifests/base`.

## Local-Only / ITAR Posture
- Policy checks do not require network access.
- External connectivity is not used for `check` or `can-i`.
- `rules/status` only probes Iron Bank if `IRON_BANK_READ_API` is set.
- Rule data can be refreshed out-of-band and mounted as a local snapshot.

## Rule Engine Update
- Core FIPS/STIG boolean policy checks now run through CEL expressions for deterministic behavior.
- Dependency denylist checks remain data-driven (snapshot-backed), with CEL used for control logic and guardrail conditions.

## Known Limits (MVP)
- Rule evaluation is deterministic but heuristic (not full OPA/CEL).
- YAML parsing for `.compliance.yaml` is intentionally minimal.
- Node native dependency detection uses a known package list, not full npm metadata resolution.
- Rust FIPS verification cannot prove feature flags from `Cargo.lock` alone.
- STIG checks use content heuristics, not full YAML AST semantic validation.
- CEL expressions are compiled per evaluation (good enough for MVP, not yet optimized/cached).

## Suggested Next Hardening Steps
1. Replace ad-hoc YAML parsing with robust parser and schema validation.
2. Add signed snapshot import/export flow for air-gapped rule updates.
3. Move rule logic to CEL/Rego with precompiled policies.
4. Add evidence artifacts per finding (rule id + parsed source location).
5. Add integration tests with golden lockfiles and manifest fixtures.
