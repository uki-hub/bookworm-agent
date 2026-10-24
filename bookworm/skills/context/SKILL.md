---
description: Show Bookworm knowledge — the context tree, one or more contexts, or answer a question from them. Read-only.
argument-hint: "[context-id …] [question]"
disable-model-invocation: true
allowed-tools: Bash(bw *), Read
---
## Request
$ARGUMENTS

## State
!`bw ctx show $0 || true`

## Do
- Only one id or none: present the output above as it is, in a code block. Don't call any tools. Then add one line: `/bookworm:context <id> [<id> …] [question]` shows contexts or answers from them; `/bookworm:context-check <id>` checks one against source.
- More ids or a question: `bw ctx show <every id in the request>` (no ids given: pick the relevant ones from `bw ctx tree`), then read each context's "read first" router and only the docs it routes to for the question. Answer from those docs, citing doc paths; say what they don't cover. Read-only: never edit, never read source unless the docs point to a symbol the question needs.
