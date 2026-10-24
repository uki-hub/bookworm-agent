# Changelog

## v0.0.2 (2026-10-22): Claude Code rewrite

Bookworm was rebuilt as a native Claude Code plugin. v0.0.1 ran on OpenCode. The design goal was the same behavior at a fraction of the cost: rules move out of prompts into a helper CLI and hooks, and prompts keep only judgment.

### Added
- **Claude Code plugin**: 15 `/bookworm:*` commands (17 with `/bookworm:do` and `/bookworm:context-rename`, both added 2026-10-24), 2 agents (`bw-knowledge` writes knowledge only; `bw-inspector` is read-only), an `authoring` guide and document templates.
- **`bw` helper**: a stdlib-Python (≥ 3.9) CLI that owns every rule: drift hashing, versioned knowledge-only publishing, task readiness, run baselines and the completion gate. Every subcommand has `--help` with an example; JSON inputs have `bw template …`.
- **Hooks**: a SessionStart status (≤ 6 lines); a PreToolUse guard that keeps the inspector read-only, keeps the knowledge agent out of source, blocks direct `task.json`/`run.json` edits and blocks source git mutations during a run.
- **`/bookworm:learn-all`**: survey → atlas you confirm → parallel waves in import order → dependency edges → coverage report → one publish. Resumable after a kill. A re-run proposes only uncovered or stale areas.
- **`no-new-failures` check mode**: pre-existing lint or test failures don't block completion, but new ones do.
- **Dedicated knowledge git** (default): knowledge commits go to `.bookworm/.git`, and `.bookworm/` is excluded from your repo's status. **Repo mode** commits knowledge into your repo through a separate index.
- **State injection**: commands start from `bw` output, so the model doesn't rediscover the state. Read-only views take one turn and no tool calls.
- `BOOKWORM_MAX_PARALLEL` caps learn-all workers on low-memory machines.

### Fixed (v0.0.1 failures)
| ID | v0.0.1 problem | v0.0.2 |
|---|---|---|
| K1 | `context-check` findings were lost before `context-update` | Findings are cached in `.cache/findings` and consumed by update |
| K2 | Line-ending-only changes were reported as drift | LF-normalized hashing; a CRLF-only rewrite stays `current` |
| K3 | 13 leftover draft and state files | No files outside the context, task, run and `.cache` folders |
| K4 | Agents read the helper's source 25 times | 0. Discoverable `--help`, templates and injected state |
| K5 | Pre-existing lint errors blocked completion | `no-new-failures` mode with recorded baseline evidence |
| K6 | `.bookworm/` showed up in source `git status` | Hidden (dedicated mode) |
| K7 | Headless runs ignored command routing | `claude -p "/bookworm:<cmd>"` runs the command as written |
| K8 | A missing Python dependency blocked the helper | Stdlib only |
| K9 | init committed an overview the docs said it wouldn't | Behavior matches the docs: init commits `.gitignore`; the overview ships with the first learn |

### Also fixed during v0.0.2 verification
- A learn-all re-run on an already-published run re-published it. `bw` now refuses a second publish of the same run and says the workspace is already learned.
- `learn-all connect --apply` no longer rewrites contexts whose edges didn't change.
- `learn-all coverage --write` keeps hand-written sections such as "Reasons for gaps".
- An empty skill argument expanded to the shell's path. `bw` now drops it.

### Fixed after live use (2026-10-23)
- **No more update loop before a run.** A context whose own files are unchanged but whose dependency published a new version is now `REVIEW` ("review suggested"), not `STALE`, and no longer blocks a task. Fix commands are listed dependencies first, and `/bookworm:context-update --all` follows the same order.
- **Re-pin without `todo-update`.** A task that hasn't run yet re-pins newer context versions at `/bookworm:run` start; the run prints each doc diff to check against the plan.
- Rewriting only a verification note no longer bumps the context version.
- The guard no longer blocks multi-line `bw` commands (`\` line continuations), or knowledge-agent writes after `cd /d/…` (Git Bash paths).
- The learn-all atlas is printed by `bw learn-all start --dry-run`: the same table every time, at most 80 columns, with a legend for depth and wave. `bw learn-all template atlas` lists the fields.
- `/bookworm:context A B <question>` answers from several contexts' docs, so you don't need `@` (which can't see `.bookworm/`). `bw ctx show` takes several ids.
- `/bookworm:todo <id> [question]` shows one task (plan, handoff) and answers questions about it, read-only. When the discussion calls for a change, it ends with `/bookworm:todo-update <id> as discussed above`.
- **A run that adds files in a new area finishes in one go.** Run maintenance maps unmapped files itself: it extends a nearby context (`bw ctx set <id> --add-include <glob>`, which appends instead of replacing), creates a new context, or excludes the files with a reason. No manual `/bookworm:learn` and second run.

### Added after live use (2026-10-24)
- **`/bookworm:do <change>`**: a shortcut for plan → run. It plans the change as a normal task, asks once (skipped with `--yes`), refreshes stale pinned knowledge, then runs it through the same baseline, checks, maintenance and gate. Best for small changes; larger ones work too. Use plan → todo → run when you want to review the plan first.
- `bw run start` refuses while another task is running, naming that task and how to finish or revise it.
- The run steps live in one template (`bw template run-steps`) shared by `/bookworm:run` and `/bookworm:do`.
- **`/bookworm:context-rename <id> <new-id>`** (`bw ctx rename`): renames a context's folder and doc files. It rewrites links in other manifests and docs (paths, relative links, `` `id` ``, link text), the overview route and task pins. It commits in one knowledge commit without a version bump, so readiness doesn't change. It refuses during a run that uses the context, during learn-all, or with unpublished knowledge. Prose mentions of the old id are listed, not rewritten.

### Results
On the fixed benchmark scenario (see [BENCHMARKS.md](BENCHMARKS.md)), compared with v0.0.1:
- 8.1× fewer input tokens (9.96M → 1.23M)
- 5.4× fewer tool calls (396 → 74)
- 4.4× faster (28.7 → 6.5 min)
- knowledge kept after update improved from 9/10 to 10/10 facts

### Known limitations
- Verified on Windows 11 (Git Bash) only. The Linux and macOS unit-test run is pending.
- The eval suite (`bookworm/evals`) loads but can't run on Windows, because `claude plugin eval` refuses a Bash grant without a sandbox backend. Run it on Linux or macOS.
- The v0.0.1 baseline used a different model and harness. The same-model comparison (B1) is pending, so the ratios above are indicative.
- The first `learn` of a feature can miss cross-boundary details. In the benchmark, every run caught the host accepting peer `GAME_STATE` at `context-check`, not at learn. Run `context-check` after the first learn of anything security-relevant.
- learn-all atlas size varies between runs (5–6 contexts on the same app).
- A run may publish knowledge twice in quick succession (manifest, then docs). This is harmless.

## v0.0.1: OpenCode prototype

The first version ran on OpenCode with a Python helper (`bookworm.py`). It proved the concept (source-backed contexts, pinned plans, gated runs) but cost about 10M input tokens per scenario. Its review is in `archives/v0.0.2-bench/baseline-v0.0.1/REVIEW-v0.0.1.md`.
