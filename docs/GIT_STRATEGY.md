# Git Strategy

Modified trunk-based development with lazy branching.

## Workflow

```
main ──●──●──●──●──●──●──●──●──●──●──●──●──●──●──●──●──●──●──●──●──●
       │        │              │                          │
       │     v0.1.0         v0.2.0                     v1.0.0
       │     (tag)          (tag)                      (tag)
       │                                                  │
       │                                           release/v1 ──●──●
       │                                                        │
       │                                                     v1.0.1
       │                                                     (tag)
```

## Rules

### 1. All Changes via PR
- Every change goes through a Pull Request
- CI must pass (lint, typecheck, test, build)
- No approval required - merge when green
- Squash merge to keep history clean

### 2. Tag Naming
| Tag | Meaning | Creates Branch? |
|-----|---------|-----------------|
| `v1.0.0` | Major release | Yes → `release/v1` |
| `v1.1.0` | Minor release | No (unless patch needed) |
| `v1.1.1` | Patch release | Created from `release/v1.1` if needed |

### 3. Release Branches
- Only created when needed (backport/patch)
- Named `release/v{major}` or `release/v{major}.{minor}`
- Never merge back to main (cherry-pick instead)

### 4. CI/CD Triggers

| Event | CI | Release |
|-------|-----|---------|
| PR to main | ✓ Run tests | ✗ |
| Push to main | ✓ Run tests | ✗ |
| Push tag `v*` | ✓ Run tests | ✓ Build & push images |

## Branch Protection (GitHub Settings)

Configure for `main` branch:

- [x] Require a pull request before merging
- [ ] Require approvals (disabled - no approval needed)
- [x] Require status checks to pass before merging
  - `Lint & Format`
  - `Type Check`
  - `Test`
  - `Build Operator Image`
  - `Build Echo Server Image`
- [x] Require branches to be up to date before merging
- [ ] Require conversation resolution (optional)
- [x] Do not allow bypassing the above settings

## Releasing

```bash
# Tag a release (triggers build + push)
git tag v0.1.0
git push origin v0.1.0

# For major releases, also create branch
git checkout -b release/v1
git push origin release/v1
```

## Hotfix on Old Version

```bash
# 1. Create release branch if doesn't exist
git checkout v1.1.0
git checkout -b release/v1.1
git push origin release/v1.1

# 2. Cherry-pick fix from main
git cherry-pick <commit-sha>

# 3. Tag the patch
git tag v1.1.1
git push origin v1.1.1 release/v1.1
```
