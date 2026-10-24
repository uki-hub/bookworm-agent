---
description: Show what a Bookworm task or context touches — contexts, drift, dependents, run effects. Read-only.
argument-hint: "<task-id | context-id>"
disable-model-invocation: true
allowed-tools: Bash(bw *)
---
!`bw affected $0 || true`

Present the output above to the user as it is, in a code block. Don't call any tools. If it lists a fix command, repeat it on the last line.
