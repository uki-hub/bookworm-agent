---
description: Delete a Bookworm task (files move to tasks/_deleted, history kept).
argument-hint: "<task-id> [--yes]"
disable-model-invocation: true
allowed-tools: Bash(bw *)
---
## Request
$ARGUMENTS

## Task
!`bw task show $0 || true`

## Do
1. Unless the request contains `--yes`, show the task's goal and status and ask for confirmation; then stop.
2. `bw task del $0` (`--force` only if it's running and the user confirmed anyway).

## Reply (≤ 4 lines)
Deleted task id and where its files are kept.
