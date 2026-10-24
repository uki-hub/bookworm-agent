---
description: List Bookworm tasks (plans and todos), or show one task and answer questions about it. Read-only.
argument-hint: "[open | todo | <word> | <task-id> [question]]"
disable-model-invocation: true
allowed-tools: Bash(bw *), Read
---
## Request
$ARGUMENTS

## Tasks
!`bw task list $0 || true`

## Do
- No task id in the request (empty, `open`, `todo` or a filter word): present the output above as it is, in a code block. Don't call any tools. Then add one line: `/bookworm:todo <id> [question]` shows or discusses a task; `/bookworm:todo-check <id>` checks it; `/bookworm:run <id>` executes it.
- A task id or number: `bw task show <id>`, then read the `.md` files it lists (`plan.md`, `handoff.md`). With a question, also read the pinned contexts' routers, only where the question needs them. Show the task or answer, citing paths; say what the plan doesn't cover.
- Read-only: never edit the task, its files or `bw task set`. If the discussion points to a change, end with: `/bookworm:todo-update <id> as discussed above`.
