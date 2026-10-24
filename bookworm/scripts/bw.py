#!/usr/bin/env python3
"""bw — the Bookworm helper. Every subcommand has --help with an example.

Exit codes: 0 ok, 1 gate/check failed (or stale), 2 usage/error.
Paths: repo files are 'repo:path' (e.g. app:src/x.ts; a bare path means the first repo).
Context folders are relative to .bookworm/context/. Printed paths are workspace-relative.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bwlib import core, ctx, learn, run, task  # noqa: E402
from bwlib.store import Workspace, lock_info  # noqa: E402
from bwlib.util import BwError, out  # noqa: E402

for stream in (sys.stdout, sys.stderr, sys.stdin):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


SHELL_PATH = re.compile(r"[\\/](usr[\\/])?bin[\\/](ba|z|da)?sh(\.exe)?$", re.I)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write(f"bw: error: {message}\n(see: {self.prog} --help)\n")
        sys.exit(2)


def sub(parent, name, helptext, example, ro=False):
    p = parent.add_parser(name, help=helptext, description=helptext + (" Read-only." if ro else ""),
                          epilog=f"example:\n  {example}", formatter_class=argparse.RawDescriptionHelpFormatter)
    p.set_defaults(ro=ro)
    return p


def build():
    ap = Parser(prog="bw", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True, parser_class=Parser)

    p = sub(sp, "init", "Create .bookworm/ (config, overview stub, knowledge git, exclude entry). Idempotent.",
            "bw init --mode dedicated")
    p.add_argument("--mode", choices=["dedicated", "repo"], help="dedicated .bookworm/.git (default) or project repo")
    p.add_argument("--policy", choices=["auto", "manual"], help="auto commits knowledge; manual prints commands")
    p.add_argument("--repo", action="append", metavar="ID=PATH", help="register a repo (default app=.)")

    p = sub(sp, "status", "Contexts, stale ones, open tasks, unpublished knowledge, lock.", "bw status --brief", ro=True)
    p.add_argument("--brief", action="store_true")
    sub(sp, "check", "Structural validation of all records (manifests, routes, cycles, tasks).", "bw check", ro=True)

    # ctx
    c = sub(sp, "ctx", "Knowledge contexts.", "bw ctx tree").add_subparsers(dest="sub", required=True, parser_class=Parser)
    p = sub(c, "tree", "Context tree with version and freshness.", "bw ctx tree", ro=True)
    p.add_argument("id", nargs="?")
    p = sub(c, "show", "Manifest, links, dependents, tasks, freshness of one or more contexts (no id: the tree).",
            "bw ctx show detective-scan game-state", ro=True)
    p.add_argument("ids", nargs="*")
    p = sub(c, "new", "Create a context folder + manifest; optional fields as in 'ctx set'. You then write the router.",
            'bw ctx new features/detective-scan --id detective-scan --title "Detective scan" '
            '--include app:src/context/GameContext.tsx --anchor "app:src/context/GameContext.tsx#submitDetectiveScan=change validation"')
    p.add_argument("folder", help="folder under .bookworm/context/")
    p.add_argument("--id", required=True)
    p.add_argument("--title")
    p.add_argument("--type", default="feature", help="feature | component | concept | area (default feature)")
    p.add_argument("--parent")
    p.add_argument("--include", action="append", metavar="REPO:GLOB")
    p.add_argument("--anchor", action="append", metavar="PATH#SYMBOL=WHEN")
    p.add_argument("--depends", action="append", metavar='ID="REASON"')
    p.add_argument("--related", action="append", metavar="ID")
    p = sub(c, "set", "Set manifest fields (each given field is replaced; --add-include appends).",
            'bw ctx set detective-scan --include app:src/context/GameContext.tsx --include "app:src/components/shared/ActionScreens/Detective*.tsx" '
            '--anchor "app:src/context/GameContext.tsx#submitDetectiveScan=change scan validation" '
            '--depends game-state="uses phase transitions" --related peer-transport --doc contract=detective-scan-contract.md\n'
            '  bw ctx set board --add-include "app:src/export/**"')
    p.add_argument("id")
    p.add_argument("--title")
    p.add_argument("--type")
    p.add_argument("--parent", help="'' clears it")
    p.add_argument("--include", action="append", metavar="REPO:GLOB")
    p.add_argument("--add-include", action="append", metavar="REPO:GLOB",
                   help="append to sources.include (de-duplicated); not with --include")
    p.add_argument("--anchor", action="append", metavar="PATH#SYMBOL=WHEN")
    p.add_argument("--depends", action="append", metavar='ID="REASON"')
    p.add_argument("--related", action="append", metavar="ID")
    p.add_argument("--doc", action="append", metavar="NAME=FILE", help="register a scope doc in the folder")
    p.add_argument("--no-depends", dest="depends", action="store_const", const=[], help="clear depends_on")
    p = sub(c, "stale", "Changed/added/deleted watched files and upstream drift. Exit 1 if stale.",
            "bw ctx stale detective-scan --diff", ro=True)
    p.add_argument("id", nargs="?", default="--all")
    p.add_argument("--all", dest="id", action="store_const", const="--all")
    p.add_argument("--diff", action="store_true", help="include the git diff of changed files since refresh")
    p = sub(c, "refresh", "Record current source hashes and upstream versions after you reviewed the source.",
            "bw ctx refresh detective-scan")
    p.add_argument("id")
    p = sub(c, "del", "Delete a context folder and its overview route lines; report what breaks.",
            "bw ctx del detective-scan")
    p.add_argument("id")
    p.add_argument("--force", action="store_true")
    p = sub(c, "rename", "Rename a context id: folder, doc files, links, task pins. Commits without a version bump.",
            "bw ctx rename detective-scan detective")
    p.add_argument("old")
    p.add_argument("new")

    p = sub(sp, "publish", "Validate, bump versions of changed contexts, commit knowledge (per policy), clear their findings.",
            'bw publish -m "learn detective-scan" detective-scan')
    p.add_argument("-m", "--message", required=True)
    p.add_argument("ids", nargs="*", help="limit to these contexts (default: all knowledge)")
    p.add_argument("--learn-all", metavar="RUN", help="final publish of a learn-all run")

    # task
    t = sub(sp, "task", "Plans and todos.", "bw task list").add_subparsers(dest="sub", required=True, parser_class=Parser)
    p = sub(t, "new", "Create a task in one call: id, task.json, plan.md (from --plan file or stdin), steps, checks, "
                      "affects; pins the affected contexts and prints readiness.",
            "bw task new detective-scan-guards --goal \"Harden submitDetectiveScan\" --step \"Guard the updater\" "
            "--check build pass \"npm run build\" --affects detective-scan --plan - <<'EOF'\n# plan …\nEOF")
    p.add_argument("slug")
    p.add_argument("--kind", default="plan", choices=["plan", "todo"])
    p.add_argument("--goal", default="")
    p.add_argument("--step", action="append")
    p.add_argument("--check", action="append", nargs=3, metavar=("NAME", "MODE", "CMD"))
    p.add_argument("--affects", action="append", metavar="CTX")
    p.add_argument("--plan", metavar="FILE|-", help="plan.md content ('-' = stdin)")
    p = sub(t, "set", "Set task fields (--step/--check/--affects replace the list).",
            'bw task set 1-x --goal "…" --step "Guard the updater" --step "Run checks" '
            '--check build pass "npm run build" --check lint no-new-failures "npm run lint" --affects detective-scan')
    p.add_argument("id")
    p.add_argument("--goal")
    p.add_argument("--step", action="append")
    p.add_argument("--check", action="append", nargs=3, metavar=("NAME", "MODE", "CMD"),
                   help="MODE is pass or no-new-failures")
    p.add_argument("--affects", action="append", metavar="CTX")
    p.add_argument("--status", choices=list(task.STATUSES))
    p = sub(t, "pin", "Pin consumed contexts at their published version (default: current pins + affects).",
            "bw task pin 1-x detective-scan")
    p.add_argument("id")
    p.add_argument("ctx", nargs="*")
    p.add_argument("--reason")
    p = sub(t, "list", "Tasks with status and derived readiness. Filter: text, a status, or 'open'.",
            "bw task list open", ro=True)
    p.add_argument("filter", nargs="?")
    p = sub(t, "show", "One task: goal, checks, pins, steps, run, readiness with fixes.", "bw task show 1-x", ro=True)
    p.add_argument("id")
    p = sub(t, "step", "Mark a step done/undone ('all' for every step).", "bw task step 1-x S1 done")
    p.add_argument("id")
    p.add_argument("step")
    p.add_argument("state", choices=["done", "undone"])
    p = sub(t, "revise", "Snapshot to history/r<n>, bump revision, supersede an unfinished run, re-pin.",
            "bw task revise 1-x")
    p.add_argument("id")
    p.add_argument("--no-repin", action="store_true")
    p = sub(t, "todo", "Turn a plan into a todo and scaffold handoff.md.", "bw task todo 1-x")
    p.add_argument("id")
    p = sub(t, "del", "Delete a task (files move to tasks/_deleted/).", "bw task del 1-x")
    p.add_argument("id")
    p.add_argument("--force", action="store_true")

    p = sub(sp, "affected", "Task → its contexts, drift, run effects. Context → dependents and tasks.",
            "bw affected detective-scan", ro=True)
    p.add_argument("id")

    # run
    r = sub(sp, "run", "Execution runs and the completion gate.", "bw run start 1-x").add_subparsers(
        dest="sub", required=True, parser_class=Parser)
    p = sub(r, "start", "Baseline snapshot + baseline check results; resumes the same-revision run.",
            "bw run start 1-x")
    p.add_argument("task")
    p.add_argument("--override", metavar="REASON", help="start although readiness is not ready (user decided)")
    p.add_argument("--no-baseline", action="store_true", help="skip running checks at baseline")
    p = sub(r, "check", "Run acceptance checks (default all) and record results.", "bw run check 1-x lint")
    p.add_argument("run", help="run id or task id")
    p.add_argument("names", nargs="*")
    p = sub(r, "effects", "Source changes since the baseline, mapped to contexts.", "bw run effects 1-x", ro=True)
    p.add_argument("run")
    p = sub(r, "maintain", 'Record maintenance: <ctx> updated|no-change "<reason>", or --file <path> excluded "<reason>".',
            'bw run maintain 1-x detective-scan updated "documented new guards"')
    p.add_argument("run")
    p.add_argument("args", nargs=argparse.REMAINDER)
    p = sub(r, "finish", "Completion gate: done, or needs_attention with every reason.", "bw run finish 1-x")
    p.add_argument("run")
    p.add_argument("--accept", metavar="REASON", help="user explicitly accepts the listed gaps (recorded)")

    f = sub(sp, "findings", "Check→update handoff cache (.cache/findings).", "bw findings get detective-scan"
            ).add_subparsers(dest="sub", required=True, parser_class=Parser)
    p = sub(f, "put", "Save findings for a context from a file or stdin.",
            "bw findings put detective-scan <<'EOF'\n- stale: …\nEOF")
    p.add_argument("id")
    p.add_argument("file", nargs="?", default="-")
    p = sub(f, "get", "Print cached findings for a context.", "bw findings get detective-scan", ro=True)
    p.add_argument("id")

    p = sub(sp, "survey", "Inventory, entry points, docs, coarse import graph, existing contexts. No model needed.",
            "bw survey", ro=True)
    p.add_argument("--json", action="store_true")

    la = sub(sp, "learn-all", "learn-all run state: atlas, waves, cards, coverage.", "bw learn-all status"
             ).add_subparsers(dest="sub", required=True, parser_class=Parser)
    p = sub(la, "template", "Print an example atlas or card JSON.", "bw learn-all template atlas", ro=True)
    p.add_argument("kind", choices=["atlas", "card"])
    p = sub(sp, "template", "Print a document shape: overview, router, plan, handoff, verification, run-steps.",
            "bw template router", ro=True)
    p.add_argument("kind", choices=["overview", "router", "plan", "handoff", "verification", "run-steps"])
    p = sub(la, "start", "Start a run from a confirmed atlas file (deleted after import), or --resume one.",
            "bw learn-all start --atlas .bookworm/.cache/atlas.json")
    p.add_argument("--atlas")
    p.add_argument("--resume", nargs="?", const="", metavar="RUN")
    p.add_argument("--dry-run", action="store_true", help="validate the atlas and print the preview table; no run")
    p = sub(la, "next", "Mark and print the jobs to dispatch now (current wave, ≤ 4 in flight; BOOKWORM_MAX_PARALLEL lowers it).", "bw learn-all next")
    p.add_argument("--run")
    p.add_argument("--max", type=int)
    p = sub(la, "brief", "Worker brief: job, budget, steps, earlier-wave cards.", "bw learn-all brief game-state", ro=True)
    p.add_argument("job")
    p.add_argument("--run")
    p = sub(la, "done", "Validate the job's folder, manifest and card; mark done.", "bw learn-all done game-state")
    p.add_argument("job")
    p.add_argument("--run")
    p = sub(la, "fail", "Record a failed job (one retry, optionally narrower), then failed.",
            'bw learn-all fail game-state "worker returned nothing" --include app:src/context/GameContext.tsx')
    p.add_argument("job")
    p.add_argument("reason")
    p.add_argument("--include", action="append")
    p.add_argument("--run")
    p = sub(la, "status", "Jobs per wave with status.", "bw learn-all status", ro=True)
    p.add_argument("--run")
    p = sub(la, "cards", "All finished cards, compact (summary, routes, interactions, unknowns).", "bw learn-all cards", ro=True)
    p.add_argument("--run")
    p = sub(la, "connect", "Turn card interactions into depends_on/related edges (dry run unless --apply).",
            "bw learn-all connect --apply")
    p.add_argument("--run")
    p.add_argument("--apply", action="store_true")
    p = sub(la, "coverage", "Covered ÷ included code files, gaps with reasons; --write writes context/coverage.md.",
            "bw learn-all coverage --write")
    p.add_argument("--run")
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", action="store_true")
    p = sub(la, "abandon", "Stop tracking a run (its folders stay, unpublished).", "bw learn-all abandon la-1")
    p.add_argument("run", nargs="?")

    lk = sub(sp, "lock", "Inspect or release the write lock.", "bw lock status").add_subparsers(
        dest="sub", required=True, parser_class=Parser)
    sub(lk, "status", "Show the lock holder.", "bw lock status", ro=True)
    p = sub(lk, "release", "Remove a stale lock (--force removes a live one).", "bw lock release --force")
    p.add_argument("--force", action="store_true")
    return ap


def dispatch(a):
    if a.cmd == "template":
        return learn.cmd_template(a.kind)
    if a.cmd == "init":
        root = os.environ.get("BOOKWORM_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        existing = Workspace.find(required=False)
        return core.cmd_init(existing.root if existing else root, a.mode, a.policy, a.repo)
    ws = Workspace.find()
    if a.ro:
        return ro_dispatch(ws, a)
    with ws.lock(f"{a.cmd} {getattr(a, 'sub', '') or ''}".strip()):
        return rw_dispatch(ws, a)


def ro_dispatch(ws, a):
    key = (a.cmd, getattr(a, "sub", None))
    if key == ("status", None):
        return core.cmd_status(ws, a.brief)
    if key == ("check", None):
        return core.cmd_check(ws)
    if key == ("ctx", "tree"):
        return ctx.cmd_tree(ws, a.id)
    if key == ("ctx", "show"):
        return ctx.cmd_show_many(ws, a.ids) if a.ids else ctx.cmd_tree(ws)
    if key == ("ctx", "stale"):
        return ctx.cmd_stale(ws, a.id, a.diff)
    if key == ("task", "list"):
        return task.cmd_list(ws, a.filter)
    if key == ("task", "show"):
        return task.cmd_show(ws, a.id)
    if key == ("affected", None):
        return core.cmd_affected(ws, a.id)
    if key == ("run", "effects"):
        return run.cmd_effects(ws, a.run)
    if key == ("findings", "get"):
        return core.cmd_findings_get(ws, a.id)
    if key == ("survey", None):
        return learn.cmd_survey(ws, a.json)
    if key == ("template", None):
        return learn.cmd_template(a.kind)
    if key == ("learn-all", "template"):
        return learn.cmd_template(a.kind)
    if key == ("learn-all", "brief"):
        return learn.cmd_brief(ws, a.run, a.job)
    if key == ("learn-all", "status"):
        return learn.cmd_status(ws, a.run)
    if key == ("learn-all", "cards"):
        return learn.cmd_cards(ws, a.run)
    if key == ("lock", "status"):
        info = lock_info(ws.cache / "lock")
        out("unlocked" if not info else f"locked by pid {info.get('pid')} ({info.get('cmd')}), "
            f"{int(info['age'])}s old{' — stale' if info['stale'] else ''}")
        return 0
    raise BwError(f"unhandled command {key}")


def rw_dispatch(ws, a):
    key = (a.cmd, getattr(a, "sub", None))
    if key == ("ctx", "new"):
        ctx.cmd_new(ws, a.folder, a.id, a.title, a.type, a.parent)
        if a.include or a.anchor or a.depends or a.related:
            ws.contexts(refresh=True)
            a.doc, a.title, a.type, a.parent = None, None, None, None
            ctx.cmd_set(ws, a.id, a)
        return 0
    if key == ("ctx", "set"):
        return ctx.cmd_set(ws, a.id, a)
    if key == ("ctx", "refresh"):
        return ctx.cmd_refresh(ws, a.id)
    if key == ("ctx", "del"):
        return ctx.cmd_del(ws, a.id, a.force)
    if key == ("ctx", "rename"):
        return ctx.cmd_rename(ws, a.old, a.new)
    if key == ("publish", None):
        return ctx.cmd_publish(ws, a.message, a.ids, a.learn_all)
    if key == ("task", "new"):
        return task.cmd_new(ws, a.slug, a.kind, a.goal, a)
    if key == ("task", "set"):
        return task.cmd_set(ws, a.id, a)
    if key == ("task", "pin"):
        return task.cmd_pin(ws, a.id, a.ctx, a.reason)
    if key == ("task", "step"):
        return task.cmd_step(ws, a.id, a.step, a.state)
    if key == ("task", "revise"):
        return task.cmd_revise(ws, a.id, not a.no_repin)
    if key == ("task", "todo"):
        return task.cmd_todo(ws, a.id)
    if key == ("task", "del"):
        return task.cmd_del(ws, a.id, a.force)
    if key == ("run", "start"):
        return run.cmd_start(ws, a.task, a.override, not a.no_baseline)
    if key == ("run", "check"):
        return run.cmd_check(ws, a.run, a.names)
    if key == ("run", "maintain"):
        return run.cmd_maintain(ws, a.run, a.args)
    if key == ("run", "finish"):
        return run.cmd_finish(ws, a.run, a.accept)
    if key == ("findings", "put"):
        return core.cmd_findings_put(ws, a.id, a.file)
    if key == ("learn-all", "start"):
        return learn.cmd_start(ws, a.atlas, a.resume, a.dry_run)
    if key == ("learn-all", "next"):
        return learn.cmd_next(ws, a.run, a.max)
    if key == ("learn-all", "done"):
        return learn.cmd_done(ws, a.run, a.job)
    if key == ("learn-all", "fail"):
        return learn.cmd_fail(ws, a.run, a.job, a.reason, a.include)
    if key == ("learn-all", "connect"):
        return learn.cmd_connect(ws, a.run, a.apply)
    if key == ("learn-all", "coverage"):
        return learn.cmd_coverage(ws, a.run, a.json, a.write)
    if key == ("learn-all", "abandon"):
        return learn.cmd_abandon(ws, a.run)
    if key == ("lock", "release"):
        info = lock_info(ws.cache / "lock")
        raise BwError("lock release runs outside the lock; use: bw lock release --force" if info else "unlocked")
    raise BwError(f"unhandled command {key}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # skills pass --yes through (it only affects prompts); an unset $0 in a skill expands to the shell's path
    argv = [x for x in argv if x != "--yes" and not SHELL_PATH.search(x)]
    if argv[:2] == ["lock", "release"]:
        ws = Workspace.find()
        info = lock_info(ws.cache / "lock")
        if not info:
            out("unlocked")
            return 0
        if not info["stale"] and "--force" not in argv:
            out(f"lock held by live pid {info.get('pid')} ({info.get('cmd')}); pass --force to remove it anyway")
            return 1
        (ws.cache / "lock").unlink()
        out("lock released")
        return 0
    a = build().parse_args(argv)
    try:
        code = dispatch(a)
        return code if isinstance(code, int) else 0
    except BwError as e:
        sys.stderr.write(f"bw: {e}\n")
        return e.code
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # unexpected: short report, never a source dump
        sys.stderr.write(f"bw: internal error: {e.__class__.__name__}: {e}\n")
        if os.environ.get("BW_DEBUG"):
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
