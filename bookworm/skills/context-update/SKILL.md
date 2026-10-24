---
description: Update a Bookworm context (or --all stale ones) to match current source, using cached check findings, and publish.
argument-hint: "<context-id | --all>"
disable-model-invocation: true
context: fork
agent: bookworm:bw-knowledge
allowed-tools: Bash(bw *)
---
## Drift
!`bw ctx stale $0 --diff || true`

## Cached findings from context-check
!`bw findings get $0 || true`

## Context
!`bw ctx show $0 || true`

## Do
1. With `--all`, handle each stale context listed above in turn.
2. Read the context's docs, then the code behind each drift item and each cached finding.
3. Fix every claim that is now wrong. Add every cached finding you confirm in code, with its symbol, in the doc that owns that topic. Note rejected findings in the verification note.
4. Overwrite `<id>-verification.md`: source state checked, what changed, what wasn't checked.
5. `bw ctx refresh <id>`, `bw check`, then `bw publish -m "update <id>: <what changed>" <id>` (this clears the findings).

## Reply (≤ 15 lines)
Context id and new version, claims fixed, findings added or rejected, commit, next command.
