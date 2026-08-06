---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
---

## Pre-flight check

Before starting the interview, check `git status`. If there are unstaged or uncommitted changes, warn the user:

> You have uncommitted changes. The downstream workflow (`/write-a-prd` → `/prd-to-issues` → `/orchestrate-prd`) will branch from the current HEAD. Do you want to commit or stash first, or is this fine?

Only proceed after the user confirms.

## Interview

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one.

If a question can be answered by exploring the codebase, explore the codebase instead.

### Question format

Ask **one question at a time**. For each question:

1. List the options as a numbered list (1, 2, 3, ...)
2. Give your recommendation with reasoning

## Handoff

When the interview is complete (all branches resolved, shared understanding reached), ask:

> Ready to write this up. Want me to `/write-a-prd`?
