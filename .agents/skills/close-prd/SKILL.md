---
name: close-prd
description: Clean up remote and local prd branches after a PRD's PR has been merged. Use when user says the PR is merged and they're ready to clean up, or invokes /close-prd.
---

# Close PRD

Clean up both remote and local `prd-<prd-number>/` work branches after the PRD's PR has been merged.

**Only delete `prd-*/` branches.** Never delete `feature/` branches — they serve as a permanent record of integration work.

## Process

1. Ask the user for the PRD number if not provided as an argument.
2. Confirm the PR for the PRD has been merged:

```bash
gh pr list --head "feature/<prd-number>-*" --state merged --json number,title
```

If no merged PR is found, warn the user and confirm they still want to proceed.

3. List both remote and local branches matching `prd-<prd-number>/`:

```bash
git branch -r --list 'origin/prd-<prd-number>/*'
git branch --list 'prd-<prd-number>/*'
```

4. If no `prd-<prd-number>/` branches exist (remote or local), report that there's nothing to clean up and exit.

5. Show the user which branches will be deleted (both remote and local) and ask for confirmation.

6. Delete the remote branches:

```bash
git branch -r --list 'origin/prd-<prd-number>/*' | sed 's|origin/||' | xargs -I {} git push origin --delete {}
```

7. Delete the local branches:

```bash
git branch --list 'prd-<prd-number>/*' | xargs git branch -D
```

8. Clean up local tracking references:

```bash
git remote prune origin
```

9. Report what was deleted (remote and local counts).
