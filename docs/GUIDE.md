# Bookworm user guide

This guide covers the concepts, a full walkthrough, every command, configuration, headless use and troubleshooting. For quick install steps, see [README.md](../README.md).

## Contents

1. [Concepts](#1-concepts)
2. [Walkthrough: from zero to a gated change](#2-walkthrough)
3. [Command reference](#3-command-reference)
4. [Writing good requests](#4-writing-good-requests)
5. [Configuration](#5-configuration)
6. [Headless and CI use](#6-headless-and-ci-use)
7. [What's in `.bookworm/`](#7-whats-in-bookworm)
8. [Safety model](#8-safety-model)
9. [Troubleshooting](#9-troubleshooting)
10. [FAQ](#10-faq)

---

## 1. Concepts

### Context: a unit of knowledge
A **context** documents one feature or area, for example `checkout`, `auth-session` or `detective-scan`. It has:
- a **router doc** (`<id>-context.md`): the purpose and boundary, how it works, reading routes ("changing X → open Y"), rules and invariants, and risks and unknowns;
- a **manifest** (`context.json`): the source files it watches (`--include` globs), **anchors** (key symbols and when to open them), dependencies on other contexts, and a version number;
- a **verification note**: what was checked against source, and how.

Contexts are grouped by folder, for example `features/checkout` or `components/ui-kit`. A context id is a plain slug you or learn-all chose. To change it later, use `/bookworm:context-rename <id> <new-id>`; links, task pins and versions stay valid. Task ids carry a number instead (`<n>-<slug>`), and the number alone works everywhere (`/bookworm:run 1`). The **overview** (`.bookworm/context.md`) holds the purpose of the workspace, a repo map, run and test commands, and one reading route per context. It's the entry point every command reads first.

### Staleness: knowing when docs lie
Every context records a hash of each file it watches. When any of those files changes, including a new untracked file that matches an include glob, the context becomes **stale**. Hashes are line-ending-normalized, so a CRLF-only rewrite does **not** count as drift. Bookworm tells you which files changed. `context-check` tells you *what* in the docs is now wrong, and `context-update` fixes it. When only a context it depends on published a new version, the context is marked **review** instead: worth a look, but it doesn't block tasks.

### Publishing: versioned knowledge
`publish` validates the contexts, bumps the version of each one that changed, and commits **only knowledge**. By default the commit goes to a private git repo in `.bookworm/.git`, so your project history stays clean. Every past version of the knowledge can be recovered.

### Tasks: plans and todos with pinned assumptions
A **task** (from `/bookworm:plan` or `/bookworm:do`) has a goal, ordered steps, **acceptance checks** (shell commands) and **pins**: the context versions it was planned against. **Readiness** is computed fresh every time:

| Readiness | Meaning | Typical fix |
|---|---|---|
| `ready` | Pinned contexts' own files are unchanged. Newer versions are re-pinned when the run starts; "review suggested" notes don't block | `/bookworm:run <id>` |
| `needs_review` | A pinned context is stale, or newer than the pin of a task that has already run | `/bookworm:context-update <ctx>` (dependencies first), then `/bookworm:todo-update <id>` |
| `blocked` | A pinned context was deleted | Re-plan or re-learn |

A **todo** is a plan deferred to a future session, with a `handoff.md` note (`/bookworm:plan-todo`).

### Runs: implementation with a completion gate
`/bookworm:run` records a **baseline**: a hash of every source file plus the result of every acceptance check *before* any change. It then implements the plan, re-runs the checks, maps each changed file to a context, refreshes the affected knowledge and calls the **gate**. The result is `done` only when all of these hold:
1. every step is ticked;
2. every check passed after the last source change;
3. every changed file maps to a context, or is excluded with a recorded reason;
4. every affected context was refreshed and published.

Files in a brand-new area don't need a separate `/bookworm:learn`: during maintenance the knowledge agent adds them to a nearby context, creates a new context for them, or excludes them with a reason (generated files, assets), all in the same run.

Otherwise the result is `needs_attention`, and every reason comes with the command that fixes it.

**Check modes:**
- `pass`: the command must exit 0.
- `no-new-failures`: the failures must match the baseline. Use this for lint or test suites that already carry known debt.

If you say a check "must pass", Bookworm keeps it as `pass`, even when it already fails, and reports honestly rather than claiming `done`.

### Learn-all: mapping a whole workspace
`/bookworm:learn-all` surveys the repo and drafts an **atlas**: one job per area that developers change together, each with a depth (`deep`, `light` or `skip`) and a **wave**. Foundations come first, then features, then leaf UI. After you confirm the atlas, parallel workers learn each job. The run then connects contexts with dependency edges, writes a coverage report and publishes everything in **one commit**. It's resumable if interrupted.

---

## 2. Walkthrough

The example is a React game repo; the same flow works for any stack.

**1. Initialize** (once per repo):
```text
/bookworm:init
```
This creates `.bookworm/` (hidden from your repo's `git status`), a private knowledge git and a draft overview with run and test commands. It's safe to re-run.

**2. Learn the feature you're about to touch:**
```text
/bookworm:learn how the detective scans two players and reveals = or ≠
```
Bookworm reads the code along the feature's path, writes a context (router plus verification note), adds a reading route to the overview and publishes `learn detective`. A typical run takes about 1–2 minutes and up to 25 tool calls.

**3. Code changes happen** (yours, a teammate's, a merge). Check whether the docs still hold:
```text
/bookworm:context-check detective
```
This step is read-only. It reports what's stale (for example, "allowance changed 99 → 1; the comment and code now agree") and caches the findings.

**4. Plan the change:**
```text
/bookworm:plan Harden submitDetectiveScan: reject scans outside the action phase, by non-detectives, or on eliminated/identical/self targets. Keep UI unchanged. Acceptance: npm run build and npm run lint pass.
```
The plan is saved as task `1-harden-detective-scan`, with checks `build (pass)` and `lint (pass)` and a pin on `detective v1`. Because the context is stale, readiness is `needs_review`, and the plan names the fix.

**5. Fix the knowledge, then re-pin:**
```text
/bookworm:context-update detective
/bookworm:todo-update 1-harden-detective-scan
```
The update uses the cached findings, so nothing found by the check is lost. The task gets revision 2, pinned to `detective v2`, and is `ready`.

**6. Run it:**
```text
/bookworm:run 1-harden-detective-scan
```
The steps are baseline → implement → checks → knowledge maintenance → gate. In the sample run, lint already had 7 errors before the change, so the honest result was:
```text
needs_attention: check lint (pass) failed: exit 1; it also failed at baseline (exit 1), pre-existing failures
```
You decide: fix the lint debt, switch the check to `no-new-failures` with `/bookworm:todo-update`, or accept the gap with `bw run finish <id> --accept "<reason>"`. The reason is recorded.

**Shortcut for steps 4–6:** `/bookworm:do <same request>` plans the task, shows one summary and asks "Run it?", refreshes the stale `detective` context, then runs to the gate. The guarantees and the result are the same; you just type one command. Use the separate steps when you want to review or change the plan first.

**7. Look around at any time** (one turn, no tool calls):
```text
/bookworm:todo
/bookworm:affected 1-harden-detective-scan
/bookworm:context detective
```

---

## 3. Command reference

Read-only commands never write to source or knowledge; this was verified by hash diff in the benchmark runs.

### Setup and knowledge

| Command | Arguments | What it does | Writes |
|---|---|---|---|
| `/bookworm:init` | `[--mode dedicated\|repo] [--policy auto\|manual]` | Creates `.bookworm/` and the knowledge git, and drafts the overview. Idempotent | config, overview |
| `/bookworm:learn` | `<feature or area>` | Learns one feature into a context and publishes it. If a context already covers it, updates that one instead | one context |
| `/bookworm:learn-all` | `[--resume] [--yes]` | Survey → atlas (you confirm) → parallel waves → edges → coverage → one publish | many contexts |
| `/bookworm:context` | `[context-id …] [question]` | Shows the context tree or contexts' details, or answers a question from their docs | read-only |
| `/bookworm:context-check` | `<context-id \| --all>` | Checks the docs against current source and caches the findings | `.cache` only |
| `/bookworm:context-update` | `<context-id \| --all>` | Fixes the docs using drift and cached findings, then publishes | context |
| `/bookworm:context-del` | `<context-id> [--yes]` | Deletes a context after showing its dependents. History stays in knowledge git | context |
| `/bookworm:context-rename` | `<context-id> <new-id> [--yes]` | Renames a context id: its folder and doc files, links in other contexts and the overview, and task pins. Commits on its own without a version bump, so readiness doesn't change. Refuses while a run uses it, during learn-all, or with unpublished knowledge. Prose mentions of the old id are listed, not rewritten | context |

### Work

| Command | Arguments | What it does | Writes |
|---|---|---|---|
| `/bookworm:plan` | `<change, incl. acceptance> [--yes]` | Saves a task: goal, steps, checks, pins, readiness. Doesn't touch code | task |
| `/bookworm:plan-todo` | `<task-id>` | Turns a plan into a todo with a handoff note for a later session | task |
| `/bookworm:todo` | `[open \| todo \| <word> \| <task-id> [question]]` | Lists tasks with status and readiness. With a task id, shows that task's plan and handoff and answers your question about it; ends with the `/bookworm:todo-update` line to run when a change came up | read-only |
| `/bookworm:todo-check` | `<task-id>` | Checks a task against current knowledge and code: readiness, drift, plan sanity | read-only |
| `/bookworm:todo-update` | `<task-id> [new intent]` | Creates a new revision (the old one goes to `history/`), re-pins knowledge and adjusts the plan | task |
| `/bookworm:todo-del` | `<task-id> [--yes]` | Deletes a task; its files move to `tasks/_deleted` | task |
| `/bookworm:run` | `<task-id> [proceed anyway] [--yes]` | Baseline → implement → checks → maintenance → gate. Refuses a task that isn't ready unless you say "proceed anyway" (recorded) | source, run, knowledge |
| `/bookworm:do` | `<change, incl. acceptance> [--yes]` | Shortcut for plan → run: saves the task, asks once, refreshes stale pinned contexts, then baseline → implement → checks → maintenance → gate. Without named checks it infers build/lint/test ones (`no-new-failures`, marked inferred) | task, source, run, knowledge |
| `/bookworm:affected` | `<task-id \| context-id>` | Shows the contexts, drift, dependents and run effects a task or context touches | read-only |

### The `bw` helper

All rules live in `bw`, a stdlib-Python CLI that is on PATH while the plugin is enabled. You rarely need it directly, but it's useful for scripting and diagnosis:

```bash
bw status                 # workspace, knowledge HEAD, stale contexts, active runs
bw ctx stale              # which contexts drifted, with a diff stat
bw check                  # validate manifests (routes, dependencies, cycles)
bw task show <id>         # task details and readiness
bw run finish <id>        # re-evaluate the gate; lists every reason
bw learn-all status       # learn-all jobs per wave
bw --help                 # every subcommand has --help with an example
```

Exit codes: `0` ok, `1` gate or check failed (or stale), `2` usage error.

---

## 4. Writing good requests

- **Learn:** name the behavior, not just a folder. "how checkout applies discounts and taxes" works better than "src/checkout". Mention the key files or symbols if you know them; Bookworm reads every file you name.
- **Plan:** include the acceptance commands, e.g. "Acceptance: `npm test` and `npm run lint` pass". Checks you state as "must pass" stay strict. Say "no new lint errors" if existing debt is acceptable; that becomes `no-new-failures`.
- **Do:** write it like a plan request. If you name no checks, it uses the build/lint/test commands from the overview as `no-new-failures` and marks them inferred in its summary; name your own when they must pass.
- **Scope:** state the non-goals ("keep the UI unchanged", "no new dependencies"). The planner won't add tests or files you didn't ask for unless it explains why.
- **Big repos:** run `/bookworm:learn-all` once, then `/bookworm:learn` for depth where you work most.

---

## 5. Configuration

### Modes (`/bookworm:init --mode …`)

| Mode | Knowledge commits go to | Your repo sees | Default policy |
|---|---|---|---|
| `dedicated` (default) | `.bookworm/.git`, a private repo | nothing (`.bookworm/` is added to `.git/info/exclude`) | `auto` |
| `repo` | your project repo, via a separate index (your staging area is never touched) | `.bookworm/` as tracked files, shareable with the team | `manual` |

Use `repo` mode when the team should share and review knowledge in pull requests.

### Policy (`--policy …`)
- `auto`: `publish` commits knowledge itself.
- `manual`: `publish` validates and prints the exact git commands; you commit.

### Environment variables

| Variable | Effect |
|---|---|
| `BOOKWORM_PYTHON` | Python interpreter to use (otherwise `python3`, then `python`; needs ≥ 3.9) |
| `BOOKWORM_MAX_PARALLEL` | Caps learn-all parallel workers (1–4, default 4). Use `2` on machines with ≤ 16 GB RAM |
| `BOOKWORM_ROOT` | Workspace root override (otherwise `CLAUDE_PROJECT_DIR` or the current directory) |
| `BW_DEBUG` | Print full tracebacks from `bw` |

### Config file
`.bookworm/bookworm.json` holds the mode, the policy, the repos (for multi-repo workspaces) and the excludes. Edit it only through `bw` commands where they exist.

---

## 6. Headless and CI use

Every command works with `claude -p`:

```bash
claude -p "/bookworm:context-check --all" --output-format json < /dev/null
claude -p "/bookworm:learn-all --yes" --output-format json < /dev/null
```

- Add `--yes` to commands that would otherwise ask (plan clarifications, the do confirmation, the learn-all atlas). Bookworm then picks safe defaults and says which ones it chose.
- Pass `< /dev/null` (or close stdin) so `claude -p` doesn't wait for input.
- Usage of a forked command (the read-only checks run in a sub-agent) is in the session transcript, not the top-level JSON. Sum `~/.claude/projects/<proj>/<session>.jsonl` and `<session>/subagents/*.jsonl` if you track cost.
- **Drift gate in CI:** `bw ctx stale` exits `1` when any context is stale. For example, fail a docs job or post a reminder when a PR changes watched code without updating the knowledge.

---

## 7. What's in `.bookworm/`

```text
.bookworm/
├── bookworm.json                 config (mode, policy, repos, excludes)
├── context.md                    workspace overview: purpose, repo map, run/test, reading routes, gaps
├── context/
│   ├── coverage.md               learn-all coverage report (gaps with reasons)
│   └── features/<id>/
│       ├── context.json          manifest: includes, anchors, depends_on, version, hashes
│       ├── <id>-context.md       router doc
│       └── <id>-verification.md  what was verified against source, and how
├── tasks/<n>-<slug>/
│   ├── task.json                 goal, steps, checks, pins, revision (edit via bw only)
│   ├── plan.md                   the plan
│   ├── handoff.md                todos only
│   └── history/r1/…              earlier revisions
├── runs/<task>-r<rev>-<n>/run.json   baseline, check results, effects, maintenance, result
├── .cache/                       findings, learn-all state (not committed)
└── .git/                         knowledge history (dedicated mode)
```

A typical feature context is a few KB. After the benchmark scenario the whole folder was about 33 KB (v0.0.1: 820 KB).

---

## 8. Safety model

Hooks and `bw`, not prompts, enforce these:

| Guarantee | Enforced by |
|---|---|
| Read-only commands write nothing | They run as the `bw-inspector` agent; the PreToolUse hook denies Write/Edit and non-read-only Bash |
| Knowledge agents can't edit source | The `bw-knowledge` agent may write only inside `.bookworm/` |
| No source git mutations | The guard blocks source `git commit/add/reset/stash/push` while a run is active; `bw` never stages or commits source |
| Gate files can't be forged | Direct edits of `task.json` and `run.json` are denied; state changes go through `bw` |
| Prompt injection in arguments | Skills never splice free text into shell commands; the hook denies `bw` chained with mutating commands |
| Your uncommitted edits survive | Runs record a baseline and never reset or stash |

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `bw: command not found` | The plugin's `bin/` is on PATH only while the plugin is enabled. Directly: `python <plugin>/scripts/bw.py …` |
| `bw: no Python >= 3.9 found` | Install Python or set `BOOKWORM_PYTHON`. On Windows, `python3` may be a Store stub; the shim falls back to `python` |
| `workspace locked by pid …` | Another `bw` write is running. If that process is gone: `bw lock release` (`--force` only removes a lock whose process is still alive) |
| Plan shows `needs_review` | The readiness lines name the command: `/bookworm:context-update <ctx>` (stale) or `/bookworm:todo-update <id>` (newer knowledge) |
| `publish refused` | `bw check` lists the problems: missing router, unknown `depends_on`, cycle |
| `refusing to rename …` | The message names the fix: publish pending knowledge first (`bw publish -m "…"`), finish the running task, or finish learn-all (`--resume`) |
| Run stays `needs_attention` | `bw run finish <id>` lists every reason with its fix. To accept a known gap: `bw run finish <id> --accept "<reason>"` (recorded) |
| Guard hook denied an action | The denial says what's allowed. The hooks only restrict Bookworm's agents, `task.json`/`run.json` edits and source git during a run |
| learn-all killed by low memory | Set `BOOKWORM_MAX_PARALLEL=2`, then `/bookworm:learn-all --resume` |
| learn-all says "already published" | That run finished. A re-run proposes only uncovered areas and stale contexts; if there are none, nothing happens (by design) |

---

## 10. FAQ

**Does Bookworm commit my code?** No. It never commits, stages, resets, stashes or pushes source. Knowledge commits go to `.bookworm/.git` (dedicated mode) or use a separate index (repo mode).

**What does it cost?** On the benchmark scenario, the full learn → check → plan → update → run flow took about 1.2M input tokens (mostly cached). That's about 1.2× plain Claude Code doing the same work without Bookworm. The extra pays for persisted, drift-tracked knowledge and a verified completion gate. Read-only views cost one turn each.

**Which languages are supported?** Any language. The survey understands imports for JS/TS, Python, Go and C#, and every language works for learn, check and run.

**Can I share knowledge with my team?** Use `--mode repo`, so `.bookworm/` is tracked in your repo and reviewed in PRs.

**What if the knowledge is wrong?** Run `/bookworm:context-check <id>`, then `/bookworm:context-update <id>`. Every claim in a router is meant to be source-backed, and the verification note says how it was checked.
