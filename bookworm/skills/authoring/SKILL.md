---
name: authoring
description: How to write Bookworm knowledge (overview, context routers, scope docs, verification notes). Loaded by the bw-knowledge agent.
user-invocable: false
---
# Writing Bookworm knowledge

Code already says *what* it does. Knowledge says what the code can't: **why** it exists, **how** the pieces cooperate across files, **where** to start a change, and **what** breaks if you get it wrong.

## The four questions

| Question | Write | Don't write |
|---|---|---|
| Why? | Purpose, requirements, constraints, recorded decisions | Invented reasons; explanations of syntax |
| How does it fit? | Short cross-file flow: entry → boundary → result; state, timing, trust boundaries | A walkthrough of every function; copied code |
| Where do I change it? | `repo:path` + symbol + when to open it | File inventories; line numbers |
| What could break? | Non-obvious invariants, coupling, missing guards, consequences | Generic warnings |

## Label every claim

- **Observed**: you read it in the code. Name the symbol.
- **Documented intent**: a comment, README, ADR or issue says so. Say where.
- **Inferred**: your reasoning. Write "inferred:" before it. If one more read would verify it, read and state it as observed instead.
- **Unknown**: you couldn't find out. Say "unknown" instead of guessing.

When a comment and the code disagree, say both and which one wins at runtime (the code). That disagreement is often the most useful fact in the doc.

## Files in a context folder

- `<id>-context.md`: the router. Required. Keep it under ~150 lines.
- Scope or concept docs (`<id>-<topic>.md`) only when there is a real reading boundary, e.g. `detective-scan-contract.md` for the validation rules. Register each with `bw ctx set <id> --doc <name>=<file>`.
- `<id>-verification.md`: one rolling note (≤ 40 lines), overwritten on every learn/update: what you checked, against which source state, what you did not check.
- `context.json`: written by `bw` (`bw ctx new/set/refresh`). Don't hand-edit hashes or versions.
- No drafts, copies or scratch files. Nothing else goes in the folder.

Split a doc at ~300–400 lines. Each concept has one owner doc; other docs link to it instead of repeating it.

## Router shape

1. **Purpose and boundary**: 2–4 sentences. What it owns, what it delegates.
2. **How it works**: 3–7 numbered steps across files, naming symbols.
3. **Reading routes**: a table. "Changing X → open file/symbol → why".
4. **Rules and invariants**: bullets, each with its symbol.
5. **Risks and unknowns**: missing guards, trust gaps, comment/code mismatches, open questions.

Delete any section with nothing real to say. No empty headings, no "TBD".

## Code references

- Write `app:src/context/GameContext.tsx#submitDetectiveScan`. Use the repo id from `bw status`.
- Use symbols, not line numbers. If you need a position, say "near" plus the symbol or handler name.
- Anonymous handlers: enclosing symbol + what it handles, e.g. "`setupConnection` → `conn.on('data')`, case `DETECTIVE_SCAN`".
- Put the decisive entry points in the manifest as anchors: `bw ctx set <id> --anchor "app:path#symbol=when to open it"`.

## Sources to watch

`sources.include` decides what counts as drift. Include the files whose behavior the docs describe, plus tests you cite. Don't include the whole repo. Use globs only where every match is relevant.

## Connections

- `depends_on`: this context relies on the other's contract (calls its API, assumes its state machine). Give the reason: which assumption.
- `related`: useful for navigation only.
- A shared import is a clue, not proof of a dependency. Check what is actually assumed.

## Security and trust boundaries

Always note where untrusted input enters (network messages, peers, URLs, storage), what is validated, and what isn't. For each message/event handler on the feature's path, check every type it accepts and on which side; if a message from another client can change state without checks, say exactly which message and handler. For shared or synced state, say what is sent to which clients and whether anyone can see data they shouldn't (secrets, other players' private info).

## Overview (`.bookworm/context.md`)

App purpose and users, repo map with entry points, how to run and test, and one reading route per context. No feature detail: link to the context instead. Keep it short.

## When updating

1. Read `bw ctx stale <id> --diff` and cached findings first.
2. Fix every claim the drift made wrong. Add findings that are confirmed in the code; drop ones that aren't.
3. Keep labels honest: a fixed comment/code mismatch becomes "consistent" — say so.
4. Overwrite the verification note.
5. `bw ctx refresh <id>`, then `bw check`, then `bw publish -m "<what changed>" <id>`.

## Before you finish

- Every route points to a doc or symbol that covers that topic.
- Every symbol you name exists where you say.
- No duplicated explanations across files.
- Unknowns are stated, not hidden.
