---
description: Execute a Bookworm task — baseline, implement, run acceptance checks, maintain knowledge, and pass the completion gate.
argument-hint: "<task-id> [proceed anyway] [--yes]"
disable-model-invocation: true
allowed-tools: Bash(bw *)
---
## Request
$ARGUMENTS

## Task
!`bw task show $0 || true`

## Do
`<task>` below is the task id `$0`.
1. If readiness above isn't `ready`, stop: give the reasons and the fix commands. Continue only if the user explicitly says to proceed anyway, with `bw run start $0 --override "<their words>"`.
!`bw template run-steps || true`

## Reply (≤ 15 lines)
Result line from finish (verbatim), what changed, check results, knowledge commit, each remaining reason with the command that fixes it.
