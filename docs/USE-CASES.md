# Bookworm use cases

These are concrete situations where Bookworm helps, with the commands to use for each. All of them assume `/bookworm:init` has been run once in the repo.

---

## 1. Onboard to an unfamiliar codebase

**Situation:** You (or a new teammate, or a fresh Claude session) need to understand a repo you didn't write.

```text
/bookworm:learn-all
```
Bookworm surveys the repo and proposes an atlas: one job per area that people change together, foundations first. Confirm or edit it; parallel workers then learn each area. You get an overview with reading routes ("changing X → open Y"), per-area contexts with rules and risks, and a coverage report that gives a reason for every gap.

**Why it beats re-reading:** every later session starts from `.bookworm/context.md` instead of rediscovering the code. On a ~100-file React app, learn-all used about 2M tokens once. After that, each read-only view costs about one turn.

---

## 2. Make a risky change safely

**Situation:** You must change logic that other code depends on, and you want to know what you might break.

```text
/bookworm:learn payment retries and idempotency keys
/bookworm:plan Retry failed charges with exponential backoff; reuse the idempotency key. Acceptance: npm test passes.
/bookworm:affected 1-retry-failed-charges
/bookworm:run 1-retry-failed-charges
```
The plan pins the knowledge it relied on. `affected` shows which contexts and dependents are in play. `run` records a baseline, implements the plan, re-runs the checks, refreshes the knowledge the change touched and reports `done` only if everything holds. Otherwise it lists exactly what's left.

---

## 3. Catch docs that silently went stale

**Situation:** Code changed under your docs (a merge, a teammate's PR, a hotfix), and nobody updated the explanation.

```text
/bookworm:context-check --all
/bookworm:context-update --all
```
`check` is read-only. It compares each context against current source and caches what's wrong (in the benchmark, it caught an allowance change from 99 to 1 and a host trust gap). `update` fixes the docs using those cached findings, so nothing the check found is lost, and publishes a new version.

**In CI:** `bw ctx stale` exits `1` when any watched file changed. Use it to remind PR authors to refresh knowledge.

---

## 4. Plan now, implement in another session

**Situation:** You've designed a change, but you'll implement it tomorrow, or someone else will.

```text
/bookworm:plan Split the settings page into tabs; acceptance: npm run build passes
/bookworm:plan-todo 2-settings-tabs
```
The todo gets a `handoff.md`. When anyone picks it up:
```text
/bookworm:todo-check 2-settings-tabs
/bookworm:run 2-settings-tabs
```
`todo-check` verifies the plan's assumptions still hold. If the code or knowledge moved since planning, readiness is `needs_review` and it names the fix (`context-update`, then `todo-update`). An outdated plan doesn't run blind.

---

## 5. Live with existing lint or test debt

**Situation:** The repo already fails lint (or some tests), and you don't want that to block every change, or hide new problems.

```text
/bookworm:plan Add input validation to the signup form. Acceptance: npm run build passes and no new lint errors.
```
"No new lint errors" becomes a `no-new-failures` check. The run records the baseline failures and passes only if the set of failures is unchanged. A new error fails the gate; the old debt doesn't.

If you write "lint must pass" instead, Bookworm keeps it strict. It reports `needs_attention` and names the pre-existing failures rather than pretending the work is `done`.

---

## 6. Audit trust boundaries and hidden risks

**Situation:** You want a source-backed list of what could go wrong in a feature: unchecked inputs, spoofable messages, state leaks.

```text
/bookworm:learn how clients and host exchange game state over PeerJS
/bookworm:context multiplayer-transport
```
The learn step follows data across boundaries: where inputs come from, who sends what, and what each receiver accepts without checks. The router's "Risks and unknowns" section lists each finding with its anchor and whether it was observed or inferred. In the benchmark this surfaced spoofable sender IDs, full-state broadcasts and a host that accepts state overwrites from peers.

---

## 7. Keep a team's shared understanding in the repo

**Situation:** The knowledge should be reviewed like code and shared across the team.

```text
/bookworm:init --mode repo
```
`.bookworm/` is then tracked in your project repo. Knowledge commits use a separate index (your staging area is never touched), and with the default `manual` policy, `publish` prints the git commands for you to run. The knowledge changes then go through your normal PR review.

---

## 8. Revise a plan without losing history

**Situation:** Requirements changed mid-task, or the knowledge was updated after planning.

```text
/bookworm:todo-update 1-retry-failed-charges also cap retries at 5
```
This creates revision 2. Revision 1 is kept under `history/r1`, any unfinished run is superseded, and the knowledge is re-pinned to current versions.

---

## 9. Make a small change in one command

**Situation:** The change is clear and you don't need to review a plan first (a bug fix, a guard, a small feature).

```text
/bookworm:do Round cart totals to cents before tax. Acceptance: npm test passes.
```
`do` is a shortcut for plan → run. It saves the task, shows one summary and asks "Run it?", refreshes any stale knowledge the task pins, then implements, checks, maintains knowledge and passes the same gate as `run`. Larger changes work too; use `/bookworm:plan` first when you want to review or edit the plan before any code changes.

---

## 10. Quick status between tasks

All of these are read-only, take one turn, use no tool calls and cost about the harness floor:

```text
/bookworm:todo                 open tasks with readiness
/bookworm:todo open            filter
/bookworm:context              the context tree
/bookworm:context checkout     one context: version, staleness, dependents
/bookworm:affected checkout    what depends on it, which tasks use it
```

---

## 11. Rename a context

**Situation:** A context's id no longer fits. For example, learn-all named it `multiplayer-sound`, but the team calls it `multiplayer`.

```text
/bookworm:context-rename multiplayer-sound multiplayer
```
It shows what uses the context and asks once. Then it renames the folder and doc files and rewrites the links in other contexts, the overview and the task pins, all in one knowledge commit. Versions don't change, so tasks stay `ready` and dependent contexts stay current. Prose that mentions the old name is listed for you to review; it isn't rewritten. Tasks don't need renaming: refer to them by number (`/bookworm:run 1`).

---

## When *not* to use Bookworm

- **One-off scripts or throwaway prototypes.** Nothing needs to survive the session.
- **Tiny edits in code you know well.** Plain Claude Code is about 1.2× cheaper for the same work, and Bookworm's value is persistence, drift detection and the gate.
- **When the code is the only spec you need.** For small, well-tested libraries with good docstrings, the extra layer may not pay off.
