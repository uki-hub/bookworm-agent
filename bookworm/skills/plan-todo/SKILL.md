---
description: Turn a Bookworm plan into a deferred todo with a handoff note for a future session.
argument-hint: "<task-id>"
disable-model-invocation: true
allowed-tools: Bash(bw *)
---
## Task
!`bw task show $0 || true`

## Do
1. `bw task todo $0`.
2. Fill `handoff.md` in the task folder for a future session with no chat history: goal, what's done, the first concrete next step, blockers and decisions needed, what to read first. Use this conversation and the task above; ≤ 30 lines.

## Reply (≤ 6 lines)
Task id, now a todo, handoff path, next command (`/bookworm:run <id>` when ready).
