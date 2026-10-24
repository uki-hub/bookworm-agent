#!/usr/bin/env bash
# Eval scaffold: copy the fixture app into the run workspace (cwd), commit it, and optionally
# prepare Bookworm state. Usage: setup.sh [init|learned|drifted|planned]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plugin="$(cd "$here/../.." && pwd)"
py=python3; "$py" -c '' 2>/dev/null || py=python
bw() { "$py" "$plugin/scripts/bw.py" "$@" >/dev/null; }
cp -r "$here/../fixture/app/." .
git init -q && git config user.email eval@local && git config user.name eval && git config core.autocrlf false
git add -A && git commit -qm "fixture"
stage="${1:-none}"
[ "$stage" = none ] && exit 0
bw init
[ "$stage" = init ] && exit 0
printf '# Taskboard: workspace overview\n\nTiny kanban board.\n\n## Reading routes\n\n| Changing | Open | Why |\n|---|---|---|\n| move rules, WIP limit | [board](context/features/board/board-context.md) | rules |\n' > .bookworm/context.md
bw ctx new features/board --id board --title "Board rules"
cat > .bookworm/context/features/board/board-context.md <<'DOC'
# Board rules

## Purpose and boundary
Owns the task list and the rules for moving tasks between `todo`, `doing` and `done` (`app:src/state/board.ts`).

## Rules and invariants
- Moving into `doing` is refused when `doing` already holds `WIP_LIMIT` (3) tasks (`moveTask`, `app:src/types.ts#WIP_LIMIT`).
- Moving back to `todo` is always allowed.
- Every change is saved to localStorage (`saveTasks`).
DOC
bw ctx set board --include app:src/state/board.ts --include app:src/types.ts --anchor "app:src/state/board.ts#moveTask=change move rules"
bw ctx refresh board
bw publish -m "learn board"
[ "$stage" = learned ] && exit 0
sed -i 's/WIP_LIMIT = 3/WIP_LIMIT = 1/' src/types.ts
[ "$stage" = drifted ] && exit 0
bw task new owner-reassign --goal "Allow reassigning a task owner"
printf '# 1-owner-reassign\n\n## Goal\nAllow reassigning a task owner.\n' > .bookworm/tasks/1-owner-reassign/plan.md
bw task set 1-owner-reassign --step "Add reassignOwner to board state" --check build pass "npm run build" --affects board
bw task pin 1-owner-reassign
