---
description: Check one Bookworm context (or --all) against current source. Read-only; findings are cached for context-update.
argument-hint: "<context-id | --all>"
disable-model-invocation: true
context: fork
agent: bookworm:bw-inspector
allowed-tools: Bash(bw *)
---
## Drift
!`bw ctx stale $0 --diff || true`

## Context
!`bw ctx show $0 || true`

## Do
1. If no changed/added/deleted file or upstream change is listed above and the context isn't new to you, reply "current" with the evidence line and stop.
2. Read the context's docs (router and scopes in its folder), then the drifted code around the changed lines.
3. List every doc claim the drift made wrong: doc line → code fact.
4. Then review trust boundaries in the files it watches: for every message/event handler, list each type it accepts, on which side (e.g. host or client), and who may send it. Flag every accepted input that changes state without checks and isn't in the docs, plus other important behavior they miss. Budget: ≤ 12 tool calls in total.
5. Save the findings for context-update, one per line, each marked confirmed or suspected:
   `bw findings put <id> <<'EOF'` … `EOF`

## Reply (≤ 15 lines)
Verdict (current | stale), findings with evidence, next command (`/bookworm:context-update <id>` if anything is wrong or missing).
