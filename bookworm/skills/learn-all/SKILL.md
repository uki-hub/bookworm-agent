---
description: Map the whole workspace into Bookworm contexts — survey, atlas you confirm, parallel learning waves, connections, coverage, one publish. Resumable.
argument-hint: "[--resume] [--yes]"
disable-model-invocation: true
allowed-tools: Bash(bw *)
---
## Request
$ARGUMENTS

## State
!`bw status --brief || true`
!`bw learn-all status || true`

## Survey
!`bw survey || true`

## Do
1. With `--resume`: `bw learn-all start --resume`, then go to step 5.
2. Draft the atlas from the survey (read at most 5 more files). One job per thing a developer changes together, not per folder. Foundations others import → wave 1, features → wave 2, leaf UI and pages → last. A UI kit or generated client → one `light` job. Data, vendored code, assets → `skip` with a reason. Split jobs over ~3K lines. If contexts exist, propose only uncovered areas plus jobs for stale contexts (same `context_id` and folder). Format: `bw learn-all template atlas`.
3. Write it to `.bookworm/.cache/atlas.json`, run `bw learn-all start --atlas .bookworm/.cache/atlas.json --dry-run` and show its output as is in a code block (don't redraw it). Unless `--yes`, stop and wait for the user to confirm or edit it; apply edits to the file and show the preview again.
4. `bw learn-all start --atlas .bookworm/.cache/atlas.json`.
5. Loop until `bw learn-all next` says all jobs finished: launch every job it lists as a `bookworm:bw-knowledge` agent, all in one message, each with exactly the prompt it prints. When they're back, `bw learn-all status`. For a job still running or failed: `bw learn-all fail <job> "<why>"` (add `--include` to narrow a retry). Keep only the agents' short replies; don't open their files.
6. `bw learn-all connect`; if the edges look right, `bw learn-all connect --apply`.
7. `bw learn-all cards`, then rewrite `.bookworm/context.md`: purpose and users, repo map, run and test, one reading route per context, known gaps.
8. `bw learn-all coverage --write`. If gaps lack a reason, add one in `.bookworm/context/coverage.md`.
9. Spot-check: one `bookworm:bw-inspector` agent checks 3 claims in each of 2 contexts against source. Fix wrong claims with one `bookworm:bw-knowledge` agent (no publish).
10. `bw check`, then `bw publish -m "learn-all <run>: <N> contexts, <X>% coverage" --learn-all <run>`.

## Reply (≤ 15 lines)
Run id, contexts by depth, coverage and the main gaps, spot-check result, commit, anything left to resume.
