---
description: Set up Bookworm in this repo (.bookworm/ with config, overview, knowledge git) and draft the workspace overview. Safe to re-run.
argument-hint: "[--mode dedicated|repo] [--policy auto|manual]"
disable-model-invocation: true
allowed-tools: Bash(bw *)
---
## Init result
!`bw init $ARGUMENTS || true`

## Repo survey
!`bw survey || true`

## Do
1. If the init result says "nothing changed" and "overview: present", reply "already set up" and stop.
2. Otherwise create `.bookworm/context.md` with one Write, using only the survey above (don't read files):
   - Purpose and users: 2–4 sentences from the README excerpt.
   - Repo map: one row per main area (e.g. `app:src/components`, `app:src/context`), with entry points.
   - Run and test: the package scripts.
   - Reading routes: a table with header `| Changing… | Open | Why |` and no rows yet; `learn` adds them.
   - Known gaps: what the survey can't tell (e.g. no tests found).
3. Don't publish. The first `learn` publishes the overview with its context.

## Reply (≤ 8 lines)
Mode and policy, what init created, that the overview was drafted, next: `/bookworm:learn <feature>` or `/bookworm:learn-all`.
