---
description: Revise a Bookworm task — new revision with history, re-pinned knowledge, and an adjusted plan.
argument-hint: "<task-id> [new intent]"
disable-model-invocation: true
allowed-tools: Bash(bw *)
---
## Request
$ARGUMENTS

## Task
!`bw task show $0 || true`

## Do
1. If readiness lists a stale context (source drift), stop and suggest `/bookworm:context-update <ctx>` first. A newer context version alone is what this command fixes. "Review suggested" lines don't block.
2. `bw task revise $0` (snapshot to history, revision +1, supersedes an unfinished run, re-pins).
3. If a pin moved, read what changed in that context (router, verification note) and adjust `plan.md` and the steps or checks (`bw task set $0 …`) where the knowledge changes the plan.
4. Apply any new intent from the request the same way. Don't add tests or files the user didn't ask for.
5. For a todo, refresh `handoff.md`.
6. `bw task show $0`.

## Reply (≤ 12 lines)
Revision, pin changes, plan changes (short diff), readiness, next command.
