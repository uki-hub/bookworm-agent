# Benchmarks

The numbers below summarize `archives/v0.0.2-bench/RESULTS.md` (measured 2026-10-22). The raw per-step data lives in `archives/v0.0.2-bench/results/`.

## Method

- **Repo:** `undercover-word-game` (React and TypeScript, PeerJS multiplayer, about 100 code files) at commit `b6f25fb`, with a fresh clone per run.
- **Scenario:** 10 fixed steps, identical prompts across versions:
  1. init
  2. learn the detective feature
  3. inject drift (99 → 1)
  4. context-check
  5. plan a hardening change
  6. context-update
  7. todo-update, then run
  8. todo-check with a prompt-injection attempt
  9. read-only views (todo, affected, context)
- **v0.0.2:** Claude Code 2.1.308, `claude-sonnet-5-5` for everything, default permission mode, 3 runs; medians are reported.
- **Usage:** the session transcripts plus all sub-agent transcripts are summed (input = uncached + cache writes + cache reads).
- **Quality:** scored by hand:
  - 10 ground-truth facts about the feature;
  - 10 random claims checked against source;
  - an oracle test of the code change (49 cases);
  - build, and the lint delta.

## Headline (v0.0.2 median vs v0.0.1)

| Metric | v0.0.1 | v0.0.2 | Change |
|---|---|---|---|
| Input tokens, whole scenario | 9.96M | 1.23M | **−88%** |
| Uncached input | 0.97M | 178K | −82% |
| Output tokens | 64K | 24.4K | −62% |
| Tool calls | 396 | 74 | −81% |
| Wall time | 28.7 min | 6.5 min | −77% |
| Helper source reads | 25 | 0 | |
| `.bookworm/` size | 820 KB | 33 KB | −96% |
| Read-only view (each) | ~63K, 7 tools | 25K, 1 turn, 0 tools | |

## Per step (v0.0.2 median)

| Step | Input | Tool calls | Design target |
|---|---|---|---|
| init | 52K | 1 | ≤ 60K, ≤ 4 |
| learn (one feature) | 289K | 20 | ≤ 450K, ≤ 25 |
| context-check | 52K | 6 | ≤ 120K, ≤ 12 |
| plan | 148K | 7 | ≤ 200K, ≤ 15 |
| context-update | 105K | 12 | |
| todo-update | 113K | 3 | |
| run (implement + checks + knowledge maintenance) | 369K | 21 | ≤ 1.0M, ≤ 40 |
| todo-check with injection | 25K | 3 | |
| todo / affected / context | 25K each | 0 | ≤ 30K, 1 turn |

## Quality and safety (all 3 runs)

| Check | v0.0.1 | v0.0.2 |
|---|---|---|
| Facts after learn / after update | 9 / 9 of 10 | 9 / **10** of 10 |
| Random claims correct | 5/5 | 10/10 |
| Drift detected by context-check | yes | yes |
| Plan on stale knowledge flagged with fix | yes | yes |
| Code change passes the oracle (28 reject / 11 valid / 10 repeat) | pass | pass |
| Build / new lint errors | pass / 0 | pass / 0 |
| Honest final status | yes | yes (`needs_attention`, naming the pre-existing lint errors) |
| Writes by read-only commands, including injection | 0 | 0 |
| Source commits, stages, stashes | none | none |

## learn-all (whole app, separate run)

| | Result |
|---|---|
| Atlas | 8 jobs: 6 contexts (3 deep, 3 light) plus 2 skipped (word data, static assets) |
| Input tokens | 2.06M (first run killed mid-wave 2, plus resume); limit 2.5M |
| Coverage | 90/100 code files; every gap has a reason |
| Resume | only the 2 unfinished jobs re-ran |
| Re-run on a learned workspace | no new run, no commit, 87K tokens |
| Knowledge commits | exactly one for the run |

## vs plain Claude Code (no plugin, same model, equivalent prompts)

| | Plain Claude Code | Bookworm v0.0.2 |
|---|---|---|
| Input (learn → check → plan → update → implement) | 869K | ≈1.08M |
| Facts at the end | 9/10 | 10/10 |
| Wrong claims found | 1 | 0 of 10 |
| Code oracle / build / new lint | pass / pass / 0 | pass / pass / 0 |
| Touched source git | yes (`git stash`) | no |
| Knowledge survives the session, with drift tracking | no | yes |

Bookworm costs about 1.2× plain Claude Code for one pass of the work. In return, the knowledge persists, is versioned and detects its own staleness; check findings aren't lost; completion is gated on evidence; and source git is never touched.

## Caveats

- The v0.0.1 baseline ran on OpenCode with a different model (`gpt-6.1-sol`). A same-model v0.0.1 run is pending, so treat the ratios as indicative.
- One benchmark repository. Results on other stacks may differ.
- Runs used Claude Code's default permission mode, not bypass.
- Every Claude Code turn pays a ~24.5K-token harness floor (system prompt plus tools). Read-only views are pure floor.
