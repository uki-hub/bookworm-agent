---
description: Plan a change as a Bookworm task — goal, steps, acceptance checks, and pinned knowledge — without changing code.
argument-hint: "<what to change, incl. acceptance> [--yes]"
disable-model-invocation: true
allowed-tools: Bash(bw *)
---
## Request
$ARGUMENTS

## State
!`bw status --brief || true`
!`bw ctx tree || true`

## Do
1. Read `.bookworm/context.md`, the routers of the contexts the request touches, then only the code you need to plan (≤ 8 reads). Don't edit source.
2. Ask the user only about consequential unknowns. If the request contains `--yes`, don't ask: choose the safest reading and state it in the plan.
3. Create the task with one command. It writes plan.md from the heredoc, pins the affected contexts and prints readiness:
   ```
   bw task new <slug> --goal "<one line>" --step "<step>" … --check NAME MODE "CMD" … --affects <ctx> --plan - <<'EOF'
   <plan.md: goal, non-goals, approach (symbols and contexts it relies on), risks; ≤ 50 lines>
   EOF
   ```
   - Checks: the acceptance commands the user named. If the user says a check must pass, its mode is `pass`, even if you expect existing failures. Never weaken a user's check yourself; note the expected failures under Risks, and offer `no-new-failures` as an option in your reply. Use `no-new-failures` only for lint/test checks the user didn't require to pass.
   - Steps: what to change, in order. Don't add tests or files the user didn't ask for unless the plan says why (the user can veto).
4. If readiness isn't `ready`, say why and give the fix commands in order.

## Reply (≤ 15 lines)
Task id, goal, steps, checks (with modes), pins, readiness and reasons, next command.
