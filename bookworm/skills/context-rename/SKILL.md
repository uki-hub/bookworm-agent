---
description: Rename a Bookworm context id. Links, task pins and versions stay valid; history stays in knowledge git.
argument-hint: "<context-id> <new-id> [--yes]"
disable-model-invocation: true
allowed-tools: Bash(bw *)
---
## Request
$ARGUMENTS

## What uses it
!`bw affected $0 || true`

## Do
1. Show the user the dependents and tasks listed above and the new id `$1`. Unless the request contains `--yes`, ask for confirmation and stop.
2. `bw ctx rename $0 $1`. If it refuses, report its message and the fix it names; don't work around it.
3. If it prints `mention:` lines, show them: prose mentions of the old id it left alone. Wording changes go through `/bookworm:context-update $1`.

## Reply (≤ 6 lines)
Old → new id, what was rewritten (manifests, tasks, docs), the publish line, leftover mentions.
