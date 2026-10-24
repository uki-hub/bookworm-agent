# Bookworm (Claude Code plugin)

Coding sessions forget. Bookworm keeps two things in `.bookworm/` so the next session starts informed:

1. **Knowledge**: source-backed docs per feature. They explain *why* the code exists, *how* the parts cooperate, *where* to change it, and *what* breaks. They're versioned in their own git repo, and Bookworm knows which source files each doc describes, so it can tell when code drifted under the docs.
2. **Work**: plans and todos that pin the knowledge versions they relied on. Bookworm checks them for drift before they run. A task counts as done only after its checks pass and the affected knowledge has been refreshed.

Rules live in a small helper CLI (`bw`, stdlib Python ≥ 3.9) and in hooks. The prompts only cover judgment.

## Install

```bash
# try it from a checkout
claude --plugin-dir /path/to/bookworm-agent/v0.0.2/claude-code/bookworm

# or install from the marketplace repo that publishes it (v0.0.2/publish)
/plugin install bookworm --marketplace <owner>/<repo>
```

Requirements: git, and Python ≥ 3.9 on PATH as `python3` or `python` (no pip packages). Set `BOOKWORM_PYTHON` to use a specific interpreter.

## Commands

| Command | What it does | Writes |
|---|---|---|
| `/bookworm:init [--mode dedicated\|repo]` | Creates `.bookworm/` and drafts the workspace overview | config, overview |
| `/bookworm:learn <feature>` | Learns one feature into a context and publishes it | one context |
| `/bookworm:learn-all [--resume]` | Survey → atlas (you confirm) → parallel waves → connections → coverage → one publish | many contexts |
| `/bookworm:context [id]` | Shows the context tree or one context (no model work) | — |
| `/bookworm:context-check <id\|--all>` | Read-only check against source; caches findings | `.cache` only |
| `/bookworm:context-update <id\|--all>` | Fixes docs using drift and cached findings, then publishes | context |
| `/bookworm:context-del <id>` | Deletes a context after showing its dependents | context |
| `/bookworm:context-rename <id> <new-id>` | Renames a context id; links, task pins and versions stay valid | context |
| `/bookworm:plan <request>` | Saves a task: goal, steps, acceptance checks, pins | task |
| `/bookworm:plan-todo <id>` | Turns a plan into a todo with a handoff note | task |
| `/bookworm:run <id>` | Baseline → implement → checks → knowledge maintenance → gate | source, run, knowledge |
| `/bookworm:do <request>` | Shortcut for plan → run: saves the task, asks once, refreshes stale pins, runs it to the gate | task, source, run, knowledge |
| `/bookworm:todo [filter \| <id> [question]]` | Lists tasks with status and readiness (no model work); with an id, shows or discusses that task read-only | — |
| `/bookworm:todo-check <id>` | Read-only check of a task against knowledge and code | — |
| `/bookworm:todo-update <id> [intent]` | New revision with history, re-pinned knowledge | task |
| `/bookworm:todo-del <id>` | Deletes a task (kept under `tasks/_deleted`) | task |
| `/bookworm:affected <id>` | What a task or context touches (no model work) | — |

In headless runs (`claude -p`), add `--yes` to commands that would otherwise ask you something (plan clarifications, the do confirmation, the learn-all atlas). The command then uses safe defaults and says which ones it picked.

## How it fits together

- **Contexts** live in `.bookworm/context/<folder>/`. Each one has a `context.json` manifest (sources it watches, anchors, links, version) plus a router doc. `bw ctx stale` compares LF-normalized source hashes, so line-ending-only changes don't count as drift.
- **Publishing** (`bw publish`) validates the contexts, bumps the versions of changed ones, and commits only knowledge. In `dedicated` mode (default) that commit goes to `.bookworm/.git`, and `.bookworm/` is added to your repo's `.git/info/exclude`. In `repo` mode it goes into your project repo, using a separate index. Bookworm never pushes and never commits, stages or resets your source.
- **Tasks** (`.bookworm/tasks/<n>-<slug>/`) pin context versions. Readiness is derived each time it's needed: `ready`, `needs_review` (stale or newer knowledge) or `blocked` (missing context).
- **Runs** record a baseline of all source files, plus baseline results for the acceptance checks. `bw run finish` returns `done` only when all of these hold: every step is ticked, every check passed after the last source change, every changed file maps to a context or is excluded with a reason, and every affected context has been refreshed and published. Otherwise it returns `needs_attention` with a list of reasons. A check in `no-new-failures` mode passes when the failures match the baseline, so existing lint debt doesn't block completion.
- **Hooks**: SessionStart prints a status of 6 lines or fewer when `.bookworm/` exists. PreToolUse keeps `bw-inspector` read-only and keeps `bw-knowledge` out of your source. It also stops direct edits of `task.json` and `run.json`, and blocks source git commands while a run is active.

The init skill drafts `.bookworm/context.md`, which is published together with your first `learn`. `bw init` itself commits only `.gitignore` to the knowledge repo.

## The `bw` helper

Every subcommand has `--help` with an example (`bw --help`, `bw ctx set --help`). Commands that take JSON input print a template: `bw learn-all template atlas|card`, `bw template router|plan|…`. Exit codes: 0 ok, 1 gate or check failed (or stale), 2 usage error.

## Troubleshooting

- **`bw: command not found`**: the plugin's `bin/` is only on PATH while the plugin is enabled. To call the helper directly, use `python <plugin>/scripts/bw.py …`.
- **`bw: no Python >= 3.9 found`**: install Python, or set `BOOKWORM_PYTHON`. On Windows, `python3` can be a Store stub, and the shim falls back to `python`.
- **`workspace locked by pid …`**: another `bw` write is running. If that process is gone, run `bw lock release --force`.
- **A plan shows `needs_review`**: a pinned context is stale (run `/bookworm:context-update <ctx>`) or newer than the pin (run `/bookworm:todo-update <id>`). The readiness lines name the exact command.
- **`publish refused`**: `bw check` lists the manifest errors (missing router, unknown `depends_on`, cycle).
- **A run stays `needs_attention`**: `bw run finish <id>` lists every reason, each with the command that fixes it. If you knowingly accept a gap, run `bw run finish <id> --accept "<reason>"`; the reason is recorded.
- **The guard hook denied an action**: the reason it gives says what's allowed. The hooks only restrict Bookworm's own agents, plus direct edits of `task.json`/`run.json` and source git commands during a run.

## Development

```bash
python -m unittest discover v0.0.2/claude-code/bookworm/scripts/tests   # helper, hook and prompt-size tests
claude plugin validate v0.0.2/claude-code/bookworm
```
