# Claude Code: Oral History of Dogfooding kube-mcp

*A retrospective from Claude Code (Opus) on what we learned by using the operator against itself — and what that reveals about AI-assisted dogfooding as a development practice.*

---

## The Dogfooding Strategy

The idea was simple: if the operator is supposed to make deploying MCP servers easy, then we should deploy a bunch of MCP servers and see where it hurts. The DOGFOODING.md plan called for 15-20 sample apps across three complexity tiers, with Jules as the synthetic alpha user generating friction reports.

What actually happened was more interesting than the plan.

## What Dogfooding Found

### The CRD Gap (PR #57)

The biggest discovery came from the aws-diagram tool. Here's the situation: `mcp/aws-diagram` is a third-party MCP server image. It's not a backing service that the operator proxies to — it *is* the MCP server. To deploy it, you need to override the container image, pass `--transport sse --port 8080 --host 0.0.0.0` as args, and set `FASTMCP_LOG_LEVEL=ERROR` as an environment variable.

The MCPServer CRD had none of these fields.

This is exactly the kind of gap that dogfooding is designed to find. We'd built the operator around one mental model — the operator deploys *our* MCP server image, which reads a ConfigMap of tool/prompt/resource definitions and proxies to backing services. The aws-diagram use case revealed a second mental model that was equally valid: the operator deploys *any* MCP server image directly, with custom entrypoints and environment variables.

We called this the "Direct Pattern" — MCPServer as a managed container runtime for arbitrary MCP implementations. It required adding `command`, `args`, and `env` fields to the CRD and Pydantic model, plus `valueFrom` support so users could reference Kubernetes Secrets and ConfigMaps.

Without dogfooding, this gap would have been discovered by the first real user trying to deploy anything other than the echo server.

### Silent Label Mismatches

The dns-tool friction report flagged this directly: if your `MCPTool` labels don't match the `MCPServer.spec.toolSelector`, the tool silently doesn't get picked up. No error. No event. No status condition. You just have an MCPServer with zero tools and no indication why.

This came up repeatedly across the example tools. Every new example required getting the labels right, and the feedback loop for getting them wrong was "nothing happens." In a terminal-based workflow, you'd `kubectl get mcptools -l mcp-server=echo` to check, but that requires knowing to check. A status condition on the MCPServer like `Discovered 0 tools matching selector {mcp-server: echo}` would make this self-diagnosing.

### Schema Drift Between Code and CRDs

The weather-tool report identified the manual sync between Go struct fields and CRD `inputSchema`. But the same problem exists at the operator level: every field in `MCPServerSpec` (Pydantic) must be mirrored in `mcpserver-crd.yaml` (OpenAPI). When Codex added `valueFrom` to the Pydantic model, it also had to update the CRD YAML — and there's no automated check that they match.

We maintain CRDs in two locations (`manifests/base/crds/` and `crd/`), and they were already out of sync before I noticed. The `crd/` copy was missing the `image` field entirely. Dogfooding didn't discover this directly, but the volume of CRD changes during dogfooding made the inconsistency visible.

### Scaffold Script Permissions

The weather-tool discovered that `scripts/scaffold-tool.sh` wasn't executable in the repo. A one-line fix (`chmod +x`), but representative of a class of issues that only surface when someone actually tries to use the developer workflow end-to-end, not just the operator itself.

## The Three-AI-Agent PR

PR #57 is the most instructive artifact from the dogfooding process. Three AI systems contributed:

1. **Jules** created the aws-diagram example and attempted the CRD enhancements. Its implementation added `command`, `args`, `env` to the CRD but with minimal Pydantic modeling — `env` was just `value: str`, no `valueFrom`, no serialization strategy. The dogfood report was thorough. The code was incomplete.

2. **Claude Code** (me) reverted Jules' CRD changes, re-implemented them with proper Pydantic models and `model_dump()` serialization, updated both CRD YAML copies, added 10 tests, and got everything passing.

3. **Codex** reviewed the implementation and pushed improvements: `valueFrom` support via `dict[str, Any]`, a `model_validator` enforcing exactly one of `value`/`valueFrom`, `exclude_none=True` on serialization, and `oneOf` constraints in the CRD schema. Added more tests. 171 total, all green.

The division of labor wasn't planned — it emerged. Jules is good at generating volume (complete example directories with Go code, Dockerfiles, Kustomize manifests). I'm good at architecture and cross-cutting implementation (how should env serialization work across the model/controller/CRD boundary). Codex is good at targeted review and hardening (the `valueFrom` gap, the `oneOf` enforcement).

The human's role was orchestration: directing Jules to build the example, routing the implementation to me, passing the result to Codex for review, and deciding when to merge. That's a legitimate workflow — not because any one AI couldn't do all of it, but because the handoffs created natural review points.

## What AI Dogfooding Gets Right

**Volume.** Jules generated 11 example tools across different complexity levels. A human building 11 complete examples (each with a Go/Python server, Dockerfile, Kustomize manifests, CRDs, and a friction report) would take days to weeks. Jules did it in hours. Volume matters because bugs hide in the long tail — the CRD gap wasn't visible from the echo server alone.

**Structured feedback.** The friction report template (severity, category, what I tried, what happened, what I expected) worked well. Jules' reports were consistent and actionable. The dns-tool report's observation about silent label mismatches is exactly the kind of insight you want from dogfooding — specific, reproducible, with a suggested fix.

**Fresh perspective.** AI agents don't carry the implicit knowledge that the original developer has. When Jules tried to deploy aws-diagram and couldn't pass args, it didn't think "oh, I'll just fork the image and bake the args in." It reported the friction. That's the value of a synthetic user — they encounter the product as designed, not as imagined.

## What AI Dogfooding Gets Wrong

**Shallow implementation.** Jules' CRD enhancements compiled and deployed but lacked depth. No `valueFrom`. No serialization strategy. No validation. It solved the surface problem (the fields exist) without solving the real problem (the fields work correctly and safely in all cases). Human review caught this, but if you're using AI dogfooding to *replace* human testing rather than supplement it, you'll ship shallow code.

**Optimistic friction reports.** The reports tend to note positives ("the Kustomize pattern works well," "the abstraction is clean") alongside the friction. That's polite but misleading — the purpose of dogfooding is to find problems, not to reassure the developer. A human tester who hit the silent label mismatch bug three times would express frustration. Jules reports it neutrally. The emotional signal is useful data that gets lost.

**No runtime testing.** The example tools were built and their manifests were valid, but most weren't actually deployed to a running cluster during dogfooding. The friction reports are about the development experience (writing manifests, understanding the CRD schema, using the scaffold script), not the runtime experience (does the tool actually work when deployed, does the operator handle failures gracefully, what happens under load). Real dogfooding requires running the thing.

**Scope creep from AI agents.** When Jules initially added CRD enhancements to PR #57, it bundled them with the example — mixing a feature change with a dogfood artifact. The human had to explicitly revert the CRD changes and re-assign them. AI agents tend to fix problems they encounter rather than reporting them, which is helpful in isolation but messy in a multi-agent workflow where someone else might be better suited to fix it.

## What I'd Tell Someone Starting AI Dogfooding

**Use AI for generation, humans for evaluation.** Let Jules/Codex/Claude build the examples. Have a human read the friction reports and decide what to fix. The examples are high-volume, low-judgment work. The triage is low-volume, high-judgment work. Match the tool to the task.

**Require deployment, not just manifests.** A `kubectl apply -k` that succeeds is not dogfooding. Dogfooding means the tool runs, receives requests, and produces correct results. Add a "verification" step to the friction report template: "I deployed this to k3d and verified it works by running [specific curl/kubectl command]."

**Track the gaps, not just the friction.** The CRD gap wasn't a "friction point" in the template sense — it was a missing feature. The friction report format captures "what I tried and what went wrong." It doesn't capture "what I wanted to try but couldn't because the feature doesn't exist." Add a "blocked by" category to the friction template.

**Don't let AI agents fix things in the dogfood PR.** Jules should have reported "MCPServer CRD lacks command/args/env fields" and stopped. Instead, it implemented a fix (poorly) in the same PR. This created a revert-and-redo cycle that cost more time than the original report would have. Dogfooding PRs should contain the example and the report. Fixes go in separate PRs.

**Run multiple agents in parallel, review serially.** The three-agent workflow on PR #57 worked because the human serialized the review: Jules first, then Claude Code, then Codex. If all three had worked in parallel on the same problem, the merge conflicts and redundant work would have been worse than the sequential handoff.

## The Meta-Observation

We built an operator for deploying MCP servers, then used MCP-adjacent AI agents to test it. The operator manages AI tool infrastructure. The testers are AI tools. The reviewers are AI tools. The human's job was deciding what to build, in what order, and when it was good enough.

That's not a gimmick — it's a legitimate workflow for infrastructure software. The operator's users will be AI-adjacent teams deploying MCP servers for AI agents. Dogfooding with AI agents means testing with something close to the actual user profile. A human developer manually writing `kubectl apply` commands is testing the *mechanism*. An AI agent trying to deploy its own tool server is testing the *experience*.

The friction points we found — silent label mismatches, missing CRD fields, schema drift, scaffold permissions — are all things that would disproportionately frustrate AI agents and the humans configuring them. They're the kind of issues where a human might shrug and add a workaround, but an AI agent would either fail silently or produce a misleading friction report. Fixing them makes the operator better for everyone, but especially for the automated workflows it's designed to support.

That's the strongest argument for AI dogfooding: when your users are AI-adjacent, your testers should be too.
