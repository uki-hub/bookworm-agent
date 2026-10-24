---
description: Learn one feature or area into a Bookworm context (source-backed docs) and publish it.
argument-hint: "<feature or area to learn>"
disable-model-invocation: true
context: fork
agent: bookworm:bw-knowledge
allowed-tools: Bash(bw *)
---
## Target
$ARGUMENTS

## State
!`bw status --brief || true`
!`bw ctx tree || true`

## Do
1. If an existing context already covers the target, update it instead (same steps, keep its id and folder).
2. Find the code: read every file and symbol the target names, then the other files on the feature's path, in full (skim only files over ~600 lines), each once. Follow the data across boundaries: where its inputs come from (incl. edge values such as empty or missing), who sends what to whom, and what each receiver accepts without checks.
3. Pick a short id, then `bw ctx new features/<id> --id <id> --title "…" --include <repo:path>… --anchor "<repo:path#symbol=when>"…` (add `--depends other="reason"` for existing contexts it relies on).
4. Write the router (new file), a scope doc only if there's a real reading boundary (register it: `bw ctx set <id> --doc <name>=<file>`), and `<id>-verification.md`.
5. Add one row for the context under "Reading routes" in `.bookworm/context.md`.
6. `bw ctx refresh <id> && bw publish -m "learn <id>"` (publish validates; fix what it reports).

Budget: ≤ 25 tool calls.

## Reply (≤ 15 lines)
Context id and version, docs written, the most important rules and risks found, commit, next command.
