---
description: Shortcut for plan → run — plan the change as a Bookworm task, confirm once, refresh stale knowledge, implement, check, and pass the completion gate.
argument-hint: "<what to change, incl. acceptance> [--yes]"
disable-model-invocation: true
allowed-tools: Bash(bw *), Read
---
## Request
$ARGUMENTS

## State
!`bw status --brief || true`
!`bw ctx stale || true`

## Do
`--yes` in the request: don't ask; pick the default named in each step and state it in the reply.
1. If the state above says there's no workspace or no overview, stop: `/bookworm:init`, then `/bookworm:learn <feature>` or `/bookworm:learn-all`.
2. Plan like `/bookworm:plan`: read `.bookworm/context.md`, the routers of the contexts the request touches, then only the code you need (≤ 8 reads; for a STALE context above, trust the code over its docs). Don't edit source. Create the task with one command:
   ```
   bw task new <slug> --goal "<one line>" --step "<step>" … --check NAME MODE "CMD" … --affects <ctx> --plan - <<'EOF'
   <plan.md: goal, non-goals, approach (symbols and contexts it relies on), risks; ≤ 50 lines>
   EOF
   ```
   - Checks the user named: mode `pass`, even if you expect existing failures. Never weaken them; note expected failures under Risks.
   - None named: take build/lint/test/typecheck commands from the overview's run/test section (never dev/start/serve/watch), mode `no-new-failures`, and call them inferred. None there: no checks; say so.
3. If readiness is `blocked`, stop with its reasons and fix commands.
4. Confirm (skip with `--yes`): goal, steps, checks (mode, user or inferred), affected contexts, stale pins to refresh. Ask "Run it? (y/n)" and wait. On n: stop; the task stays planned (`/bookworm:todo-update <id>`, `/bookworm:run <id>`).
5. If readiness lists STALE pins (`/bookworm:context-update <id>`), launch one `bookworm:bw-knowledge` agent with those ids in the order listed and: "for each: `bw ctx stale <id> --diff`, `bw findings get <id>`, read its docs and the drifted code, fix wrong claims, add confirmed findings, overwrite the verification note, `bw ctx refresh <id>`; then `bw check` and one `bw publish -m \"<task>: refresh <ids>\" <ids>`". Skip pins that are only "review suggested".
6. Run the task: follow the run steps below with `<task>` = the new task id.

## Run steps
!`bw template run-steps || true`

## Reply (≤ 15 lines)
Result line from `bw run finish` (verbatim) first, task id, what changed, check results (inferred ones marked), contexts refreshed or updated, knowledge commit, each remaining reason with the command that fixes it. If a user `pass` check failed with pre-existing failures: offer `no-new-failures` via `/bookworm:todo-update <id>` or `--accept`; never apply either yourself.
