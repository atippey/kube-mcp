# Hybrid Human/AI Dogfooding Strategy

## Overview

Use Jules (Anthropic's async coding agent) as a synthetic alpha user to build sample applications against the kube-mcp operator. This surfaces bugs, friction points, and documentation gaps before real users encounter them.

## Process

### Phase 1: Human-AI Sample Apps (2-3 apps)
Build initial sample applications collaboratively (human + Claude) to:
- Establish patterns and conventions
- Identify obvious issues early
- Create templates for Jules tasks

### Phase 2: Jules Sample App Generation (15-20 apps)
Assign Jules tasks to build diverse sample applications:
- Each app lives in a separate repo: `kube-mcp-samples`
- Jules documents friction points using structured template
- Apps become integration tests and user documentation

### Phase 3: Triage and Prioritize
Review Jules feedback to:
- Identify patterns (repeated friction = high priority)
- Filter Jules-specific issues from user-relevant ones
- Create actionable issues in kube-mcp repo

## Sample App Categories

### Simple (5-7 apps)
- Single tool with basic service reference
- Single prompt with variables
- Single resource with inline content
- Minimal MCPServer configuration

### Intermediate (5-7 apps)
- Multiple tools with different HTTP methods
- Prompts with complex variable substitution
- Resources with HTTP operations
- MCPServer with ingress configuration

### Advanced (5-6 apps)
- Cross-namespace service references
- Label selector with matchExpressions
- Large payloads / binary resources
- Multiple MCPServers sharing tools
- Concurrent updates / race conditions

## Friction Report Template

Jules should document issues in each sample app's README:

```markdown
## Friction Points

### [FP-001] Brief title
- **Severity**: blocker | major | minor | enhancement
- **Category**: documentation | api | validation | error-message | other
- **What I tried**: [action taken]
- **What happened**: [actual result]
- **What I expected**: [expected result]
- **Workaround used**: [if any]
- **Suggested fix**: [optional]
```

## Success Metrics

- **Coverage**: All CRD fields exercised across sample apps
- **Issue discovery**: 10+ actionable issues from 20 apps
- **Documentation gaps**: README improvements identified
- **Error messages**: Unclear errors flagged for improvement

## Repository Structure

```
kube-mcp-samples/
├── README.md                    # Overview and index
├── CONTRIBUTING.md              # Guidelines for Jules tasks
├── apps/
│   ├── 01-hello-tool/           # Simplest possible tool
│   ├── 02-echo-prompt/          # Basic prompt
│   ├── 03-static-resource/      # Inline content
│   ├── ...
│   └── 20-stress-test/          # Edge cases
└── .github/
    └── ISSUE_TEMPLATE/
        └── friction-report.md   # Template for friction issues
```

## Timeline

1. **Setup**: Create kube-mcp-samples repo, CI/CD for kube-mcp
2. **Phase 1**: 2-3 human-AI sample apps (establish patterns)
3. **Phase 2**: Assign 15-20 Jules tasks (parallel execution)
4. **Phase 3**: Triage feedback, prioritize fixes
5. **Iterate**: Fix issues, assign more Jules tasks
