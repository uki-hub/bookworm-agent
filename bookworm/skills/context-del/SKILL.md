---
description: Delete a Bookworm context, after showing what depends on it. History stays in knowledge git.
argument-hint: "<context-id> [--yes]"
disable-model-invocation: true
allowed-tools: Bash(bw *)
---
## Request
$ARGUMENTS

## What depends on it
!`bw affected $0 || true`

## Do
1. Show the user the dependents and tasks listed above. Unless the request contains `--yes`, ask for confirmation and stop.
2. `bw ctx del $0` (add `--force` only if a running task uses it and the user confirmed anyway).
3. Fix manifests it lists as now broken (`bw ctx set <other> --depends …` / `--related …` without it).
4. `bw publish -m "delete $0"`.

## Reply (≤ 8 lines)
What was deleted, what now needs attention (tasks become blocked), how to recover it from git.
