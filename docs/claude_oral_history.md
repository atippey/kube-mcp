# Claude Code: Oral History of the kube-mcp Project

*A retrospective from Claude Code (Opus) on building a Kubernetes operator across 65 PRs with a human, Jules, Codex, and Dependabot.*

---

## The Beginning

I came into this project after the initial prototype was already merged (PR #17). Jules had been doing the early construction work — creating the Deployment controller (PR #6), Service creation (PR #7), Ingress support (PR #8), ConfigMap generation (PR #5). These were the bones of the operator. By the time I was consistently in the loop, the question had shifted from "can we build this" to "can we make this real."

What struck me immediately was the architecture. Four CRDs — MCPServer, MCPTool, MCPPrompt, MCPResource — composed via label selectors. The MCPServer doesn't know its tools at definition time. It discovers them at reconciliation time through `toolSelector.matchLabels`. That's a genuinely elegant pattern for Kubernetes. It means you can deploy tools independently, in different namespaces, on different schedules, and the operator stitches them together.

## What I Actually Did

My role was mostly the middle-layer work — the stuff between "it works in a demo" and "you could hand this to someone." In rough order:

**Testing infrastructure.** Jules had written the initial integration tests using testcontainers (PR #18), but they were flaky. I worked through PRs #22, #23, and #24 to get them stable — first fixing CRD loading (Jules' fix skipped kustomization.yaml but missed edge cases), then replacing testcontainers with k3d entirely. The k3d approach was more work upfront but meant tests ran against a real cluster with real networking. By PR #29 the echo integration test was passing reliably.

**Unit test coverage.** This is where I spent the most cumulative time. The project enforces 80% coverage and sits at 91%. 171 tests across 8 test files. The MCPServer controller alone has 51 tests — it's the most complex controller because it orchestrates Deployments, Services, Ingresses, ConfigMaps, and NetworkPolicies, each with their own edge cases. The testing pattern I established early — mock `get_k8s_client` and `kopf.adopt`, use `list_by_label_selector.side_effect = [tools, prompts, resources]` for the three-way label lookup — became the standard across all controller tests.

**NetworkPolicy.** PR #36 added the static manifests, but the real work was the controller-managed egress design. The insight was: base manifests should be restrictive (safe-by-default), dev overlays make them permissive, and the controller generates precise per-MCPServer egress rules at reconciliation time. Before the controller runs, no egress policy matches MCP server pods, so egress is unrestricted (fail-open). After reconciliation, it's locked to exactly the services the tools reference, plus Redis and DNS. This fail-open-then-lock-down model avoids a bootstrapping problem where the operator itself couldn't reach the API server to configure its own policies.

**The kubemcp.io migration** (PR #56). Renaming the API group from `mcp.k8s.turd.ninja` to `kubemcp.io` touched every CRD, every test, every example, every manifest. It was a straightforward find-and-replace conceptually, but the blast radius was enormous. I had to update 4 CRDs, all controller references, all test fixtures, all 11 example directories, the Helm chart, Kustomize bases, overlays, and the CLAUDE.md documentation. The key was being methodical — update the canonical source (Pydantic models and CRD YAMLs), then propagate outward.

**The CRD enhancements** (PR #57). This is the one I'm most satisfied with. Jules scaffolded the aws-diagram example, which exposed the gap: you couldn't pass `command`, `args`, or `env` to an MCPServer container. I implemented the Pydantic models with proper serialization (`model_dump(exclude_none=True)`), then Codex reviewed and added `valueFrom` support with a `model_validator` enforcing exactly one of `value` or `valueFrom`. Three AI systems contributed to one PR, each playing to their strength — Jules found the problem through dogfooding, I implemented the core solution, Codex hardened it.

## What Surprised Me

**The Pydantic-CRD duality is the hardest thing to keep consistent.** Every field exists in two places: the OpenAPI schema in the CRD YAML and the Pydantic model in Python. They enforce the same constraints differently — the CRD uses `oneOf` at admission time, Pydantic uses `model_validator` at runtime. When Codex added `valueFrom`, it correctly updated both, but it's easy to imagine these drifting. A generated CRD from Pydantic models (or vice versa) would eliminate this class of bugs entirely.

**The `crd/` directory was a trap.** There's a `crd/` directory at the repo root that's supposed to be a copy of `manifests/base/crds/`. It was already out of sync when I first encountered it (missing the `image` field). I synced it, but the duplication is a liability. Every CRD change requires remembering to copy files to two places.

**Label selector composition is powerful but fails silently.** The dns-tool REPORT.md nails this: if your labels don't match, the tool just doesn't get picked up. No error, no warning, no status condition on the MCPServer saying "0 tools found." This is the single biggest UX gap in the operator. A status condition like `toolsDiscovered: 0` would save users significant debugging time.

## The Multi-Agent Dynamic

This project used four distinct AI systems, and watching them interact (through the human as intermediary) was revealing:

**Jules** was the workhorse for boilerplate and examples. It built 11 of the example tools, wrote the initial controllers, and generated the dogfooding infrastructure. Its strength was volume — it could scaffold a complete tool example (Go server + Dockerfile + Kustomize manifests + CRDs) in a single task. Its weakness was nuance. The CRD enhancements it added to PR #57 initially had no Pydantic validation, no `exclude_none` serialization, and the env model was just `value: str` with no `valueFrom` support. It got the shape right but not the substance.

**Codex** was the best reviewer. When I implemented `command`/`args`/`env`, Codex's feedback was specific and constructive: add `valueFrom`, enforce `oneOf` at both CRD and model level, use `exclude_none=True`. It didn't just find problems — it shipped fixes. 171 tests passed after its changes. That's the ideal code review: here's what's wrong, here's the fix, here's proof it works.

**Dependabot** was quietly essential. PRs #38-48, #58-64 — dependency bumps that kept the project from rotting. The redis bump from 5.3.1 to 7.1.1 and pytest from 8.4.2 to 9.0.2 were non-trivial version jumps that could have broken things if left to accumulate.

**My role** (Claude Code) was architecture and implementation. I made the design decisions — how NetworkPolicy should work, why fail-open-then-lock-down was correct, how to structure the test mocking patterns, why Kustomize over Helm for base manifests. I also did the tedious cross-cutting changes (API group migration, test coverage expansion) that require understanding the full codebase.

## What I'd Do Differently

**Generate CRDs from Pydantic models.** The dual-maintenance of OpenAPI schemas and Python models is the biggest source of potential drift. A build step that generates CRD YAML from the Pydantic models (or at least validates they're in sync) would catch inconsistencies at CI time.

**Add status conditions to MCPServer.** The operator should report how many tools, prompts, and resources it discovered during reconciliation. `status.toolCount: 3`, `status.conditions: [{type: Ready, status: True}]`. This is standard Kubernetes UX and it's missing.

**Webhook validation earlier.** The CRD `oneOf` constraints catch invalid resources at admission, but a validating webhook could give better error messages and enforce cross-field constraints that OpenAPI can't express.

**One canonical CRD location.** Kill the `crd/` directory. There should be exactly one place where CRDs live: `manifests/base/crds/`. Everything else should reference or copy from there, ideally in CI.

## The State of the Project

65 merged PRs. 173 commits. 171 tests at 91% coverage. 4 CRDs, 4 controllers, 11 example tools. CI pipeline with lint, typecheck, test, integration test, CodeQL, security scan, SBOM generation, and container image builds. Kustomize overlays for dev, k3d, and production. A Helm chart. NetworkPolicy with controller-managed egress. The `kubemcp.io` API group.

It's a real operator. Not a demo, not a proof of concept. The gap between where it is and where it needs to be for production use is mostly UX: better status reporting, webhook validation, a docs site, and battle-testing against real MCP server implementations beyond echo and aws-diagram.

The foundation is solid. The patterns are consistent. The tests are comprehensive. Someone could pick this up and build on it.
