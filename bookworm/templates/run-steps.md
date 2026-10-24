2. `bw run start <task>`. It records the baseline and baseline check results, or resumes this revision's run. If it re-pinned contexts, run each printed `git … diff`; if a doc change contradicts the plan, stop and suggest `/bookworm:todo-update <task>`.
3. Read `plan.md` (and `handoff.md` for a todo) in the task folder, the routers of the pinned contexts, then the code you'll change.
4. Implement the steps with a minimal diff. Don't add files or tests the plan doesn't name. Never commit, stage, stash or reset. After each step: `bw task step <task> <S#> done`.
5. `bw run check <task>`. Fix failures you caused. Don't hide or "fix" pre-existing failures outside the plan.
6. `bw run effects <task>`. Launch one `bookworm:bw-knowledge` agent with: the run id, the full effects list (including `UNMAPPED` files), the affected context ids, and "do run maintenance".
7. Record each context the agent reports: `bw run maintain <task> <ctx> updated "<what>"` (also for `created`) or `no-change "<why>"`. For each file it reports as `exclude`: `bw run maintain <task> --file <path> excluded "<why>"`.
8. `bw run finish <task>`. It alone decides done vs needs_attention. Never pass `--accept` unless the user told you to.
9. If the result isn't done and this is a todo, update `handoff.md` with the state and next step.
