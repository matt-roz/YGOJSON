---
name: orchestrate-prd
description: Orchestrate implementation of a PRD by working through its child issues respecting the dependency graph. Spawns parallel agents for unblocked issues, creates PRs, and tracks progress. Use when user wants to execute/implement a PRD, work through issues, or start building from a plan.
---

# Orchestrate PRD

Execute all child issues of a `prd-parent` issue using the dependency graph, then ship one PR.

## Branching strategy

```
BASE (e.g. main)
 └── feature/<prd-number>-<short-desc>              ← orchestrator creates at start
      ├── prd-<prd-number>/<child-number>-<short-slug>  ← agent 1 works here
      ├── prd-<prd-number>/<child-number>-<short-slug>  ← agent 2 works here
      └── prd-<prd-number>/<child-number>-<short-slug>  ← agent 3 works here
```

- `feature/` is the integration branch, created from BASE. Final PR targets BASE.
- `prd/` branches are per-issue branches from current `feature/` HEAD.
- After each issue, merge `prd/` into `feature/` and resolve conflicts.

## Process

### 1. Load the PRD and build the dependency graph

Ask for the parent PRD issue number if not provided. Then fetch parent + child issues:

```bash
gh issue view <number>
gh issue list --label prd-child --state open --json number,title,body,state --limit 100
```

For each child issue, parse: number/title, blockers, required skills, and acceptance criteria. Build an in-memory dependency graph from the "Blocked by" fields.

### 2. Create the feature branch

Read **Base branch** from the parent PRD body (from `/write-a-prd`). If missing, use current branch and confirm. Create:

```bash
git checkout <base-branch>
git checkout -b feature/<prd-number>-<short-desc>
```

Push the feature branch so agents can branch from it.

### 3. Choose execution mode

Ask user to choose execution mode:

1. **Parallel agents** — spawn background agents in isolated worktrees for all independent ready issues simultaneously. Maximizes throughput. Best when issues are truly independent and the user wants to review PRs after the fact.
2. **Sequential agents** — spawn one agent at a time in an isolated worktree. Each agent completes before the next starts. Good for when the user wants to review each result before moving on.
3. **Sequential in-context** — work through issues one at a time in the current conversation context (no sub-agents). The user sees all work happening live and can intervene. Best for smaller PRDs or when the user wants tight control.

Mode applies to the full run. Default to **parallel agents**.

### 4. Present the execution plan

Show graph state:

- Which issues are **done** (closed)
- Which issues are **ready** (all blockers closed)
- Which issues are **blocked** (waiting on open issues)

Ask user to confirm and choose:

- Execute all ready issues
- Pick specific issues to execute
- Skip certain issues

### 5. Execute ready issues

#### Batch discipline

**CRITICAL:** merge and push all work from batch N before launching batch N+1. Agents must start from the current `feature/` HEAD so they have all prior batch work.

#### Worktree base branch problem

Worktrees created with `isolation: "worktree"` do NOT automatically branch from the current checked-out branch. They may branch from `main` or another default, meaning agents in batch N+1 won't have batch N's merged work. This causes agents to recreate files that already exist, leading to merge conflicts.

**Fix:** Every agent prompt MUST include an explicit instruction to check out the feature branch before starting work:

```
git fetch origin && git checkout feature/<prd-number>-<short-desc> && git pull origin feature/<prd-number>-<short-desc>
```

This ensures the agent starts from the feature branch HEAD with all prior batch work included. Add this as step 0 in the agent prompt, before installing dependencies.

#### Parallel agents mode

For each ready AFK issue, spawn a background agent in an isolated worktree (`isolation: "worktree"`). Run independent issues in parallel. Branch name: `prd-<prd-number>/<child-number>-<short-slug>`.

#### Sequential agents mode

For each ready AFK issue (one at a time), spawn an agent in an **isolated worktree** (`isolation: "worktree"`). Wait for it to complete before starting the next.

#### Sequential in-context mode

For each ready AFK issue, implement directly in this conversation on branch `prd-<prd-number>/<child-number>-<short-slug>`, then merge into `feature/` before starting the next issue.

#### Final-sweep issues must run in-context

If an issue is blocked by all other issues (final cleanup/sweep), it **must** run sequential in-context (not worktree) after all other issues are merged.

---

Use this prompt for every issue (agent or in-context):

<agent-prompt-template>
You are implementing a vertical slice from a PRD. Work autonomously.

## Issue #{number}: {title}

{issue body}

## Instructions

0. **CRITICAL — Check out the feature branch first.** Worktrees do NOT start from the current branch. You MUST run this before anything else so you have all prior work:
   ```
   git fetch origin && git checkout feature/{prd-number}-{short-desc} && git pull origin feature/{prd-number}-{short-desc}
   ```
   Verify the checkout worked by checking that files from prior issues exist (e.g., `ls` the paths mentioned in "Blocked by" issues). If they don't exist, STOP and report the error — do not recreate them.
1. Run `pip install -e '.[dev,test]'` (worktrees need their own editable install).
2. Read and understand the issue and parent PRD context.
3. Explore the codebase to understand the current state before making changes.
4. Use these skills: {required skills from issue}
5. Implement all acceptance criteria.
6. Run `pre-commit run --all-files` frequently (black + isort + JSON formatting).
7. Confirm the CLI still imports and runs at the end: `python -m ygojson --help`.
8. Use `/git-commit`; commit messages must reference the issue.
   </agent-prompt-template>

### 6. Merge completed work into feature branch

When an issue completes:

1. **Verify acceptance criteria** — check each criterion; if any fail, go to step 8.
2. **Push to remote** — Push the worktree branch under its logical name: `git push -u origin <worktree-branch>:prd-<prd-number>/<child-number>-<short-slug>`
3. **Merge from remote** — `git fetch origin && git merge origin/prd-<prd-number>/<child-number>-<short-slug> --no-edit`; resolve conflicts.
4. **Remove worktree and branch** — Remove the worktree first (so the branch is no longer locked), then delete the branch: `git worktree remove <worktree-path> && git branch -D <worktree-branch>`
5. **Push feature branch** — Push the updated `feature/` branch to remote.
6. **Update the issue on GitHub:**
   - Check off each acceptance criterion individually after verifying it was met (`gh issue edit <number> --body "..."`).
   - Add a comment with the branch name and summary: `gh issue comment <number> --body "Branch: \`prd-<prd-number>/<child-number>-<short-slug>\`\n\n<summary from agent>"`
7. **Report progress** — tell user what completed.
8. **On failure** — report details and ask: retry, skip, or manual.

#### Merge conflict strategy

Conflict defaults:

- **Duplicate files** (agent recreated an existing module): keep `--ours` (the canonical version already on the feature branch)
- **Command files** with both structural changes (ours) and new features (theirs): manually integrate — keep our structure, add their new functionality (flags, imports, code blocks)
- **Test files** that reference old APIs: fix assertions to match the canonical module's API (e.g. error message casing)
- **main.ts** registration conflicts: resolve by keeping all valid registrations, removing duplicates and deleted commands

### 7. Update progress and loop

After **ALL agents in the current batch** complete and are merged:

1. Recompute graph (new issues may be unblocked).
2. Show done / ready / blocked.
3. If newly ready issues exist, confirm next batch and return to step 5.
4. If all done, continue to end-to-end validation.
5. If only HITL remain, inform user and stop.

### 8. End-to-end validation

**HIGHEST-PRIORITY GATE (MUST PASS):** This is the most critical step in the entire skill.
Do not declare success, do not create a final handoff, and do not treat the PRD as complete until this gate passes.

When all issues are complete, run final validation on `feature/`:

1. Checkout the feature branch
2. Run `pip install -e '.[dev,test]'`
3. Run `pre-commit run --all-files` (black, isort, JSON formatting, merge-conflict checks)
4. Run `python -m ygojson --help` to confirm the CLI still loads
5. If the PRD's changes touch the data pipeline or `schema/`, run `python test/validate_data.py` against a generated database (`ygojson` run output under `data/`). This is expensive — ask the user whether to run a full pipeline or reuse an existing `data/` directory before starting.

If validation fails, STOP and fix before proceeding:

- Identify which issue's changes introduced the failure
- Use `SendMessage` to resume the original agent for that issue with the error output and request a fix
- If the agent is no longer available, spawn a new agent with the error context
- Commit fixes to the feature branch directly
- Re-run validation after fixes
- Repeat until all checks pass

**Completion is blocked until `pre-commit run --all-files` passes** and the CLI loads.

**CRITICAL:** Do not skip schema validation when the PRD touches `schema/` or the pipeline — a clean `pre-commit` run alone is NOT sufficient there.

### 9. Create the PR

After validation passes, create **one PR** from `feature/` to BASE via `gh pr create`:

- Reference the parent PRD issue in the title (example: `feat: CLI DX overhaul with styx:// URI scheme (#1)`)
- Use the following body template:

```markdown
## Summary

<high-level summary of all changes>

## Issues

| Issue                   | Branch                                         | Status                 |
| ----------------------- | ---------------------------------------------- | ---------------------- |
| #<child-number> <title> | `prd-<prd-number>/<child-number>-<short-slug>` | Closes #<child-number> |
| ...                     | ...                                            | ...                    |

## Test plan

- [ ] `pre-commit run --all-files` passes
- [ ] `python -m ygojson --help` runs
- [ ] `python test/validate_data.py` passes (if schema or pipeline changed)
```

Report PR URL. After merge, user can run `/close-prd` to clean up remote `prd-<prd-number>/` branches.

### 10. Handle HITL issues

HITL issues are not autonomous. When unblocked:

- Notify user it needs input
- Show the issue details and acceptance criteria
- Wait for the user to resolve it before continuing

## Rules

- **One PR per PRD** — all child issues merge into the feature branch, submitted as one PR against BASE.
- **Never merge the PR** — only create it. The user merges.
- **Always use isolated worktrees** when spawning agents to avoid conflicts between parallel work.
- **Always validate** — agents must run `pre-commit run --all-files` and confirm the CLI loads.
- **Respect the graph** — never start an issue whose blockers are still open.
- **Respect batch boundaries** — merge ALL agents from batch N before launching batch N+1.
- **Final-sweep in-context** — issues blocked by all others must run in sequential in-context mode, not as worktree agents.
- **Report, don't guess** — if an agent fails, surface the error rather than retrying silently.
- **Orchestrator resolves merge conflicts** — when merging `prd/` branches into `feature/`, the orchestrator handles conflicts, not the agents.
