"""Helper tests: python -m unittest discover v0.0.2/claude-code/bookworm/scripts/tests

Each test builds a temp git repo from evals/fixture/app and drives bw in-process.
Numbers in test names refer to BLUEPRINT §14 acceptance criteria.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
PLUGIN = SCRIPTS.parent
FIXTURE = PLUGIN / "evals" / "fixture" / "app"
sys.path.insert(0, str(SCRIPTS))

import bw  # noqa: E402
from bwlib import learn  # noqa: E402

PY = sys.executable
LINT = f'"{PY}" lintcheck'


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bwtest-"))
        self.root = self.tmp / "app"
        shutil.copytree(FIXTURE, self.root)
        # deterministic python lint stand-in (no node needed): LINT-BAD lines are errors
        (self.root / "lintcheck").write_text(
            "import pathlib,sys\nbad=0\nfor p in sorted(pathlib.Path('src').rglob('*.ts*')):\n"
            "    hits=[i for i,l in enumerate(p.read_text().splitlines(),1) if 'LINT-BAD' in l]\n"
            "    if hits:\n        print(p.resolve())\n"
            "        for i in hits: print(f'  {i}:1  error  forbidden  no-bad'); bad+=1\n"
            "print(f'{bad} problems'); sys.exit(1 if bad else 0)\n", encoding="utf-8")
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@t")
        git(self.root, "config", "user.name", "t")
        git(self.root, "config", "core.autocrlf", "false")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "init")
        self.old = os.getcwd()
        os.chdir(self.root)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        os.environ.pop("BOOKWORM_ROOT", None)

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def bw(self, *args, code=0):
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            rc = bw.main([str(a) for a in args])
        text = o.getvalue() + e.getvalue()
        if code is not None:
            self.assertEqual(rc, code, f"bw {' '.join(map(str, args))} → {rc}\n{text}")
        return text

    def write(self, rel, text, mode="w"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, mode, encoding="utf-8", newline="") as f:
            f.write(text)

    def new_ctx(self, folder, cid):
        self.bw("ctx", "new", folder, "--id", cid)
        self.write(f".bookworm/context/{folder}/{cid}-context.md", f"# {cid}\n\nrouter\n")

    def learn_board(self):
        self.bw("init")
        self.new_ctx("features/board", "board")
        self.bw("ctx", "set", "board", "--include", "app:src/state/**", "--include", "src/types.ts",
                "--anchor", "app:src/state/board.ts#moveTask=change move rules")
        self.bw("ctx", "refresh", "board")
        with open(self.root / ".bookworm/context.md", "a", encoding="utf-8") as f:
            f.write("| board | [board](context/features/board/board-context.md) | rules |\n")
        self.bw("publish", "-m", "learn board")

    def plan(self, checks=(("lint", "no-new-failures", LINT),)):
        out = self.bw("task", "new", "wip-guard", "--goal", "Guard WIP")
        tid = out.split()[2]
        args = ["task", "set", tid, "--step", "Change", "--affects", "board"]
        for name, mode, cmd in checks:
            args += ["--check", name, mode, cmd]
        self.bw(*args)
        self.bw("task", "pin", tid)
        return tid


class TestInitAndStale(Base):
    def test_01_init_idempotent_and_hidden(self):
        first = self.bw("init")
        self.assertIn("initial knowledge commit", first)
        snapshot = sorted(str(p) for p in (self.root / ".bookworm").rglob("*") if ".git" not in p.parts)
        second = self.bw("init")
        self.assertIn("nothing changed", second)
        self.assertEqual(snapshot, sorted(str(p) for p in (self.root / ".bookworm").rglob("*") if ".git" not in p.parts))
        self.assertEqual(git(self.root, "status", "--porcelain"), "")

    def test_03_stale_modified_untracked_crlf(self):
        self.learn_board()
        self.bw("ctx", "stale", "board")  # current
        # CRLF-only rewrite → still current (K2)
        p = self.root / "src/state/board.ts"
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        self.assertIn("current", self.bw("ctx", "stale", "board"))
        # untracked new file in an included glob → added
        self.write("src/state/undo.ts", "export const undo = 1;\n")
        out = self.bw("ctx", "stale", "board", code=1)
        self.assertIn("added    app:src/state/undo.ts", out)
        os.remove(self.root / "src/state/undo.ts")
        # real edit → changed, with diff
        self.write("src/types.ts", (self.root / "src/types.ts").read_text().replace("WIP_LIMIT = 3", "WIP_LIMIT = 1"))
        out = self.bw("ctx", "stale", "board", "--diff", code=1)
        self.assertIn("changed  app:src/types.ts", out)
        self.assertIn("+export const WIP_LIMIT = 1", out)

    def test_upstream_drift(self):
        self.learn_board()
        self.new_ctx("pages/board-page", "board-page")
        self.bw("ctx", "set", "board-page", "--include", "app:src/pages/**", "--depends", "board=calls moveTask")
        self.bw("ctx", "refresh", "board-page")
        self.bw("ctx", "stale", "board-page")
        with open(self.root / ".bookworm/context/features/board/board-context.md", "a") as f:
            f.write("\nmore\n")
        self.bw("publish", "-m", "x")
        out = self.bw("ctx", "stale", "board-page", code=1)
        self.assertIn("upstream board v2 > seen v1", out)
        self.assertIn("board-page v1: REVIEW", out)  # upstream-only: review, not STALE
        self.assertIn("[review]", self.bw("ctx", "tree"))
        self.assertIn("1 to review", self.bw("status", "--brief"))

    def test_ctx_show_many(self):
        self.learn_board()
        out = self.bw("ctx", "show", "board", "nope", code=1)
        self.assertIn("read first: .bookworm/context/features/board/board-context.md", out)
        self.assertIn("error:", out)


class TestPublish(Base):
    def test_version_bump_and_findings_cleared(self):
        self.learn_board()
        sys_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("- gap: WIP limit off by one?\n")
            self.bw("findings", "put", "board")
        finally:
            sys.stdin = sys_stdin
        self.assertIn("WIP limit", self.bw("findings", "get", "board"))
        # manifest-only change (refresh after a source commit) does not bump the version
        self.assertIn("already current", self.bw("ctx", "refresh", "board"))
        self.write("README.md", "more\n", mode="a")
        git(self.root, "commit", "-qam", "readme")
        self.bw("ctx", "refresh", "board")
        self.bw("publish", "-m", "refresh only")
        self.assertIn("board v1", self.bw("ctx", "tree"))
        with open(self.root / ".bookworm/context/features/board/board-context.md", "a") as f:
            f.write("\n- WIP limit is 3\n")
        out = self.bw("publish", "-m", "update board")
        self.assertIn("version bumped: board v2", out)
        self.assertIn("no cached findings", self.bw("findings", "get", "board"))
        self.assertIn("nothing to publish", self.bw("publish", "-m", "again"))
        log = git(self.root / ".bookworm", "log", "--oneline")
        self.assertEqual(len(log.strip().splitlines()), 3 + 1)  # init, learn, refresh-only, update
        # a verification-note-only change is committed without a version bump
        self.write(".bookworm/context/features/board/board-verification.md", "checked again, no claim changes\n")
        out = self.bw("publish", "-m", "re-verified")
        self.assertNotIn("version bumped", out)
        self.assertIn("board v2", self.bw("ctx", "tree"))

    def test_publish_refuses_invalid_and_cycles(self):
        self.learn_board()
        self.new_ctx("features/other", "other")
        self.bw("ctx", "set", "other", "--include", "app:src/ui/**", "--depends", "board=uses")
        self.bw("ctx", "refresh", "other")
        self.bw("ctx", "set", "board", "--depends", "other=uses")
        out = self.bw("publish", "-m", "cycle", code=1)
        self.assertIn("cycle", out)

    def test_repo_mode_isolated_commit(self):
        self.bw("init", "--mode", "repo", "--policy", "auto")
        self.write("src/types.ts", "// user edit\n", mode="a")
        git(self.root, "add", "src/types.ts")  # user staged work must survive untouched
        self.new_ctx("features/board", "board")
        self.bw("ctx", "set", "board", "--include", "app:src/state/**")
        self.bw("ctx", "refresh", "board")
        self.bw("publish", "-m", "learn board")
        files = git(self.root, "show", "--name-only", "--format=", "HEAD").split()
        self.assertTrue(all(f.startswith(".bookworm/context") for f in files), files)
        self.assertIn("M  src/types.ts", git(self.root, "status", "--porcelain"))
        self.assertNotIn(".bookworm/.cache", git(self.root, "status", "--porcelain", "-uall"))


class TestTasksAndRuns(Base):
    def test_06_stale_plan_needs_review(self):
        self.learn_board()
        self.write("src/types.ts", "// drift\n", mode="a")
        tid = self.plan()
        out = self.bw("task", "show", tid)
        self.assertIn("readiness needs_review", out)
        self.assertIn("/bookworm:context-update board", out)

    def page_ctx(self):
        # "app-page" sorts before "board" but depends on it: order must come from depends_on, not ids
        self.new_ctx("pages/app-page", "app-page")
        self.bw("ctx", "set", "app-page", "--include", "app:src/pages/**", "--depends", "board=calls moveTask")
        self.bw("ctx", "refresh", "app-page")
        self.bw("publish", "-m", "learn app-page")

    def test_upstream_only_is_advice_and_repin_on_start(self):
        self.learn_board()
        self.page_ctx()
        tid = self.plan()
        self.bw("task", "pin", tid, "app-page")
        with open(self.root / ".bookworm/context/features/board/board-context.md", "a") as f:
            f.write("\nboard v2\n")
        self.bw("publish", "-m", "board v2")
        out = self.bw("task", "show", tid)
        self.assertIn("readiness ready", out)
        self.assertIn("context app-page: dependency changed", out)
        self.assertIn("bw run start re-pins it", out)
        out = self.bw("run", "start", tid)
        self.assertIn("re-pinned board v1→v2", out)
        t = json.loads((self.root / f".bookworm/tasks/{tid}/task.json").read_text())
        self.assertEqual({p["id"]: p["version"] for p in t["consumes"]}, {"board": 2, "app-page": 1})
        run = json.loads((self.root / f".bookworm/runs/{tid}-r1-1/run.json").read_text())
        self.assertEqual([r["id"] for r in run["repinned"]], ["board"])
        # once a run exists, a newer version needs todo-update again
        with open(self.root / ".bookworm/context/features/board/board-context.md", "a") as f:
            f.write("\nboard v3\n")
        self.bw("publish", "-m", "board v3")
        out = self.bw("task", "show", tid)
        self.assertIn("readiness needs_review", out)
        self.assertIn(f"/bookworm:todo-update {tid}", out)

    def test_fixes_listed_dependencies_first(self):
        self.learn_board()
        self.page_ctx()
        tid = self.plan()
        self.bw("task", "pin", tid, "app-page")
        self.write("src/state/board.ts", "// drift\n", mode="a")
        self.write("src/pages/Board.tsx", "// drift\n", mode="a")
        out = self.bw("task", "show", tid)
        self.assertLess(out.index("context-update board"), out.index("context-update app-page"))
        self.assertIn("/bookworm:context-update --all", out)
        out = self.bw("ctx", "stale", "--all", code=1)
        self.assertLess(out.index("board v1: STALE"), out.index("app-page v1: STALE"))

    def test_07_revise_history_supersede_repin(self):
        self.learn_board()
        tid = self.plan()
        self.bw("run", "start", tid)
        with open(self.root / ".bookworm/context/features/board/board-context.md", "a") as f:
            f.write("\nchange\n")
        self.bw("publish", "-m", "v2")
        out = self.bw("task", "revise", tid)
        self.assertIn("superseded", out)
        self.assertIn("board v1→v2", out)
        d = self.root / ".bookworm/tasks" / tid
        self.assertTrue((d / "history/r1/task.json").is_file())
        t = json.loads((d / "task.json").read_text())
        self.assertEqual((t["revision"], t["status"], t["run"]), (2, "planned", None))
        run = json.loads((self.root / f".bookworm/runs/{tid}-r1-1/run.json").read_text())
        self.assertEqual(run["result"], "superseded")

    def test_08_run_refuses_not_ready_and_gate_reasons(self):
        self.learn_board()
        tid = self.plan()
        self.write("src/types.ts", "// drift\n", mode="a")
        out = self.bw("run", "start", tid, code=1)
        self.assertIn("not starting", out)
        self.bw("run", "start", tid, "--override", "user accepted stale knowledge")
        self.write("src/ui/New.tsx", "export const N = 1;\n")  # unmapped file
        out = self.bw("run", "finish", tid, code=1)
        for needle in ("steps not done: S1", "check lint never ran", "maps to no context",
                       "context board has no maintenance record"):
            self.assertIn(needle, out)
        t = json.loads((self.root / f".bookworm/tasks/{tid}/task.json").read_text())
        self.assertEqual(t["status"], "needs_attention")

    def test_08_gate_passes_when_everything_holds(self):
        self.learn_board()
        tid = self.plan()
        self.bw("run", "start", tid)
        self.write("src/state/board.ts", "// guard\n", mode="a")
        self.bw("task", "step", tid, "all", "done")
        self.bw("run", "check", tid)
        out = self.bw("run", "finish", tid, code=1)
        self.assertIn("stale against the changed source", out)
        self.bw("ctx", "refresh", "board")
        self.bw("publish", "-m", "maintain board")
        self.bw("run", "maintain", tid, "board", "no-change", "docs still accurate")
        out = self.bw("run", "finish", tid)
        self.assertIn("DONE", out)
        # a source change after the check invalidates it
        self.bw("run", "start", tid, code=1)  # done tasks cannot restart

    def test_gate_passes_with_context_created_mid_run(self):
        self.learn_board()
        tid = self.plan()
        self.bw("run", "start", tid)
        self.write("src/export/csv.ts", "export const csv = 1;\n")  # brand-new area
        self.bw("task", "step", tid, "all", "done")
        self.bw("run", "check", tid)
        self.assertIn("maps to no context", self.bw("run", "finish", tid, code=1))
        self.bw("ctx", "new", "features/export", "--id", "csv", "--include", "app:src/export/**")
        self.write(".bookworm/context/features/export/csv-context.md", "# csv\n\nrouter\n")
        self.bw("ctx", "refresh", "csv")
        self.bw("publish", "-m", f"{tid}: new area csv", "csv")
        self.bw("run", "maintain", tid, "csv", "updated", "new area")
        self.bw("run", "maintain", tid, "board", "no-change", "not touched")
        self.assertIn("DONE", self.bw("run", "finish", tid))

    def test_09_no_new_failures(self):
        self.write("src/lib/storage.ts", "// LINT-BAD pre-existing\n", mode="a")
        git(self.root, "commit", "-qam", "lint debt")
        self.learn_board()
        tid = self.plan(checks=(("lint", "no-new-failures", LINT), ("strict", "pass", LINT)))
        self.bw("run", "start", tid)
        self.write("src/state/board.ts", "\n\n// moved lines\n" + (self.root / "src/state/board.ts").read_text())
        out = self.bw("run", "check", tid, code=1)
        self.assertIn("check lint (no-new-failures): PASS", out)
        self.assertIn("check strict (pass): FAIL", out)
        self.assertIn("pre-existing", out)
        self.write("src/state/board.ts", "// LINT-BAD new\n", mode="a")
        out = self.bw("run", "check", tid, "lint", code=1)
        self.assertIn("1 new failure", out)

    def test_12_ctx_del_blocks_todo(self):
        self.learn_board()
        tid = self.plan()
        self.bw("task", "todo", tid)
        out = self.bw("ctx", "del", "board")
        self.assertIn("readiness now blocked", out)
        self.assertNotIn("board", (self.root / ".bookworm/context.md").read_text().split("## Reading routes")[-1])
        self.bw("publish", "-m", "delete board")
        self.assertIn("readiness blocked", self.bw("task", "show", tid))
        log = git(self.root / ".bookworm", "log", "--oneline", "--", "context/features/board/")
        self.assertEqual(len(log.strip().splitlines()), 2)

    def test_12_ctx_del_refuses_running(self):
        self.learn_board()
        tid = self.plan()
        self.bw("run", "start", tid)
        self.assertIn("running task", self.bw("ctx", "del", "board", code=1))

    def test_ctx_rename_keeps_links_pins_and_versions(self):
        self.learn_board()
        self.new_ctx("features/pages", "pages")
        self.write(".bookworm/context/features/pages/pages-context.md",
                   "# pages\n\nSee context/features/board/board-context.md; board rules apply.\n"
                   "Moves: [rules](../board/board-context.md#rules), owner `board`, see [board](../board/board-context.md).\n")
        self.bw("ctx", "set", "pages", "--include", "app:src/pages/**", "--depends", "board=uses moveTask")
        self.bw("ctx", "refresh", "pages")
        with open(self.root / ".bookworm/context.md", "a", encoding="utf-8") as f:
            f.write("| pages | [pages](context/features/pages/pages-context.md) | screens |\n")
        self.bw("publish", "-m", "learn pages")
        tid = self.plan()
        self.assertIn("readiness ready", self.bw("task", "show", tid))
        out = self.bw("ctx", "rename", "board", "game-board")
        self.assertIn("updated 1 manifest(s), 1 task(s), 2 doc(s)", out)
        self.assertIn("versions unchanged", out)
        self.assertIn("mention: .bookworm/context/features/pages/pages-context.md:3", out)
        bw_dir = self.root / ".bookworm"
        new = bw_dir / "context/features/game-board"
        self.assertFalse((bw_dir / "context/features/board").exists())
        m = json.loads((new / "context.json").read_text(encoding="utf-8"))
        self.assertEqual((m["id"], m["version"], m["docs"]["router"]), ("game-board", 1, "game-board-context.md"))
        self.assertTrue((new / "game-board-context.md").is_file())
        p = json.loads((bw_dir / "context/features/pages/context.json").read_text(encoding="utf-8"))
        self.assertEqual(p["depends_on"][0]["id"], "game-board")
        self.assertEqual(p["upstream_seen"], {"game-board": 1})
        self.assertIn("| game-board | [game-board](context/features/game-board/game-board-context.md) |",
                      (bw_dir / "context.md").read_text(encoding="utf-8"))
        pages = (bw_dir / "context/features/pages/pages-context.md").read_text(encoding="utf-8")
        self.assertIn("context/features/game-board/game-board-context.md; board rules", pages)
        self.assertIn("[rules](../game-board/game-board-context.md#rules), owner `game-board`, "
                      "see [game-board](../game-board/game-board-context.md).", pages)
        self.assertNotIn("pages-context.md:4", out)
        t = json.loads(next(bw_dir.glob("tasks/*/task.json")).read_text(encoding="utf-8"))
        self.assertEqual((t["consumes"][0]["id"], t["affects"]), ("game-board", ["game-board"]))
        self.assertEqual(t["consumes"][0]["commit"], git(bw_dir, "rev-parse", "--short", "HEAD").strip())
        self.assertIn("readiness ready", self.bw("task", "show", tid))
        self.assertIn("nothing to publish", self.bw("publish", "-m", "again"))
        self.bw("check")
        self.assertIn("current", self.bw("ctx", "stale", "pages"))

    def test_ctx_rename_refuses(self):
        self.learn_board()
        self.new_ctx("features/pages", "pages")
        self.assertIn("unpublished changes", self.bw("ctx", "rename", "board", "game-board", code=1))
        self.bw("ctx", "set", "pages", "--include", "app:src/pages/**")
        self.bw("ctx", "refresh", "pages")
        self.bw("publish", "-m", "learn pages")
        self.assertIn("already exists", self.bw("ctx", "rename", "board", "pages", code=2))
        self.assertIn("invalid new id", self.bw("ctx", "rename", "board", "Game Board", code=2))
        tid = self.plan()
        self.bw("run", "start", tid)
        self.assertIn("running task", self.bw("ctx", "rename", "board", "game-board", code=1))
        self.assertTrue((self.root / ".bookworm/context/features/board/board-context.md").is_file())

    def test_one_running_task_at_a_time(self):
        self.learn_board()
        first, second = self.plan(), self.plan()
        self.bw("run", "start", first)
        out = self.bw("run", "start", second, code=1)
        self.assertIn(f"{first} is running", out)
        self.assertIn(f"/bookworm:run {first}", out)
        self.assertIn("resumed run", self.bw("run", "start", first))  # the running task itself still resumes
        t = json.loads((self.root / f".bookworm/tasks/{second}/task.json").read_text())
        self.assertEqual((t["status"], t["run"]), ("planned", None))

    def test_13_resume_same_run_original_baseline(self):
        self.learn_board()
        tid = self.plan()
        self.bw("run", "start", tid)
        self.write("src/ui/Button.tsx", "// edit 1\n", mode="a")
        out = self.bw("run", "start", tid)
        self.assertIn(f"resumed run {tid}-r1-1", out)
        self.write("src/ui/Card.tsx", "// edit 2\n", mode="a")
        out = self.bw("run", "effects", tid)
        self.assertIn("modified app:src/ui/Button.tsx", out)
        self.assertIn("modified app:src/ui/Card.tsx", out)

    def test_task_json_guarded_from_edits_but_steps_settable(self):
        self.learn_board()
        tid = self.plan()
        self.assertIn("S1 → done", self.bw("task", "step", tid, "S1", "done"))
        self.bw("task", "del", tid)
        self.assertTrue((self.root / ".bookworm/tasks/_deleted" / tid / "task.json").is_file())
        self.assertIn("no tasks", self.bw("task", "list"))


class TestOneCallCommands(Base):
    def test_task_new_one_call_and_ctx_new_fields(self):
        self.bw("init")
        self.bw("ctx", "new", "features/board", "--id", "board", "--include", "app:src/state/**",
                "--anchor", "app:src/state/board.ts#moveTask=move rules")
        self.write(".bookworm/context/features/board/board-context.md", "# board\n")
        self.bw("ctx", "refresh", "board")
        self.bw("publish", "-m", "learn")
        old = sys.stdin
        try:
            sys.stdin = io.StringIO("# plan\n\n## Goal\nGuard WIP\n")
            out = self.bw("task", "new", "wip", "--goal", "Guard WIP", "--step", "Change", "--check", "lint",
                          "no-new-failures", LINT, "--affects", "board", "--plan", "-")
        finally:
            sys.stdin = old
        self.assertIn("pinned board v1", out)
        self.assertIn("readiness ready", out)
        self.assertTrue((self.root / ".bookworm/tasks/1-wip/plan.md").read_text().startswith("# plan"))

    def test_ctx_set_add_include(self):
        self.learn_board()
        incs = lambda: json.loads((self.root / ".bookworm/context/features/board/context.json").read_text())["sources"]["include"]
        before = incs()
        self.bw("ctx", "set", "board", "--add-include", "app:src/export/**", "--add-include", "src/types.ts")
        self.assertEqual(incs(), before + ["app:src/export/**"])
        self.bw("ctx", "set", "board", "--add-include", "src/export/**")  # qualified, so a duplicate
        self.assertEqual(incs(), before + ["app:src/export/**"])
        out = self.bw("ctx", "set", "board", "--include", "app:src/**", "--add-include", "app:x/**", code=2)
        self.assertIn("not both", out)

    def test_unset_positional_shell_path_is_ignored(self):
        self.bw("init")
        self.assertIn("no tasks.", self.bw("task", "list", "C:/Program Files/Git/usr/bin/bash"))
        self.assertIn("no contexts yet", self.bw("ctx", "show", "/usr/bin/bash"))


class TestLock(Base):
    def test_lock_live_and_stale(self):
        self.bw("init")
        lock = self.root / ".bookworm/.cache/lock"
        lock.write_text(json.dumps({"pid": os.getpid(), "time": time.time(), "cmd": "other"}))
        from bwlib import store
        old = store.LOCK_STALE_SECONDS
        try:
            import bwlib.store as st
            orig_sleep = st.time.sleep
            st.time.sleep = lambda s: None
            out = self.bw("ctx", "new", "a/b", "--id", "b", code=2)
            self.assertIn("workspace locked", out)
            lock.write_text(json.dumps({"pid": 999999, "time": time.time(), "cmd": "dead"}))
            self.new_ctx("a/b", "b")
            self.assertFalse(lock.exists())
        finally:
            st.time.sleep = orig_sleep
            store.LOCK_STALE_SECONDS = old


class TestLearnAll(Base):
    ATLAS = {"jobs": [
        {"job": "types", "context_id": "domain-types", "folder": "core/domain-types", "include": ["app:src/types.ts", "app:src/lib/**"],
         "depth": "light", "wave": 1, "neighbors": [], "why": "shared types"},
        {"job": "board", "context_id": "board", "folder": "features/board", "include": ["app:src/state/**"],
         "depth": "deep", "wave": 2, "neighbors": ["domain-types"], "why": "rules"},
        {"job": "ui", "context_id": "ui", "folder": "ui/ui", "include": ["app:src/ui/**", "app:src/pages/**", "app:src/main.tsx"],
         "depth": "light", "wave": 3, "neighbors": ["board"], "why": "screens"},
        {"job": "scripts", "context_id": "tooling", "folder": "tooling", "include": ["app:scripts/**"],
         "depth": "skip", "wave": 1, "neighbors": [], "why": "build tooling stubs"}]}

    def worker(self, run, job, cid, folder, include, interactions=()):
        self.new_ctx(folder, cid)
        args = ["ctx", "set", cid]
        for inc in include:
            args += ["--include", inc]
        self.bw(*args)
        self.bw("ctx", "refresh", cid)
        card = {"job": job, "context_id": cid, "status": "ok", "summary": f"{cid} summary", "routes": [],
                "interactions": list(interactions), "unknowns": [], "not_covered": []}
        (self.root / f".bookworm/.cache/learn-all/{run}/cards/{job}.json").write_text(json.dumps(card))
        self.bw("learn-all", "done", job)

    def test_survey_waves(self):
        self.bw("init")
        data = learn.survey_data(bw.Workspace.find())
        dirs = data["repos"][0]["dirs"]
        self.assertLess(dirs["src/lib"]["wave_hint"], dirs["src/state"]["wave_hint"])
        self.assertLess(dirs["src/state"]["wave_hint"], dirs["src/pages"]["wave_hint"])
        self.assertEqual(dirs["src"]["wave_hint"], 1)  # types.ts is a foundation
        self.assertIn("src/state", dirs["src/lib"]["imported_by"])
        out = self.bw("survey")
        self.assertIn("w2 src/lib", out)

    def test_14_waves_resume_coverage_rerun(self):
        self.bw("init")
        atlas = self.root / ".bookworm/.cache/atlas.json"
        atlas.write_text(json.dumps(self.ATLAS))
        out = self.bw("learn-all", "start", "--atlas", atlas, "--dry-run")  # preview: no run, file kept
        self.assertIn("Atlas · 4 jobs (1 deep, 2 light, 1 skip)", out)
        self.assertIn("Depth  deep", out)
        self.assertTrue(all(len(ln) <= 80 for ln in out.splitlines()), out)
        self.assertTrue(atlas.exists())
        self.assertFalse((self.root / ".bookworm/.cache/learn-all").exists())
        out = self.bw("learn-all", "start", "--atlas", atlas)
        self.assertIn("started la-1", out)
        self.assertFalse(atlas.exists())
        out = self.bw("learn-all", "next")
        self.assertIn("wave 1: dispatch 1", out)  # skip job is not dispatched
        self.assertNotIn("board", out.split("dispatch")[1])
        self.assertIn("still running", self.bw("learn-all", "next"))
        self.worker("la-1", "types", "domain-types", "core/domain-types", ["app:src/types.ts", "app:src/lib/**"])
        self.bw("learn-all", "next")  # wave 2 → board running
        # simulated kill: board is running with no card → resume re-queues it; types stays done
        out = self.bw("learn-all", "start", "--resume")
        self.assertIn("re-queued board", out)
        self.assertIn("domain-types", self.bw("learn-all", "brief", "board"))  # earlier-wave card included
        self.bw("learn-all", "next")
        self.worker("la-1", "board", "board", "features/board", ["app:src/state/**"],
                    [{"to": "domain-types", "kind": "depends", "evidence": "board.ts imports types"}])
        self.bw("learn-all", "next")
        self.worker("la-1", "ui", "ui", "ui/ui", ["app:src/ui/**", "app:src/pages/**", "app:src/main.tsx"],
                    [{"to": "board", "kind": "depends", "evidence": "Board.tsx → moveTask"}])
        self.assertIn("all jobs finished", self.bw("learn-all", "next"))
        self.bw("learn-all", "connect", "--apply")
        m = json.loads((self.root / ".bookworm/context/ui/ui/context.json").read_text())
        self.assertEqual([d["id"] for d in m["depends_on"]], ["board"])
        self.assertIn("publish", self.bw("publish", "-m", "blocked", code=1))  # learn-all owns publishing
        cov = learn.coverage_data(bw.Workspace.find(), "la-1")
        self.assertEqual(cov["included"], 9)  # 7 src + 2 scripts (.mjs)
        self.assertEqual({u["reason"] for u in cov["uncovered"]}, {"skipped: build tooling stubs"})
        self.bw("learn-all", "coverage", "--write")
        self.assertIn("skipped: build tooling stubs", (self.root / ".bookworm/context/coverage.md").read_text())
        with open(self.root / ".bookworm/context.md", "a") as f:
            f.write("routes: domain-types board ui\n")
        self.bw("publish", "-m", "learn-all la-1", "--learn-all", "la-1")
        self.assertIsNone(learn.active_run(bw.Workspace.find()))
        self.assertIn("la-1 [complete]", self.bw("learn-all", "status", "--run", "la-1"))
        self.assertIn("uncovered code files by dir: scripts (2)", self.bw("survey"))
        # re-run on a published run: nothing to resume, no second publish, no-op edges and kept gap reasons
        self.assertIn("was published", self.bw("learn-all", "next"))
        self.assertIn("was published", self.bw("learn-all", "status"))
        self.assertIn("already published", self.bw("publish", "-m", "again", "--learn-all", "la-1", code=1))
        ctx_json = self.root / ".bookworm/context/ui/ui/context.json"
        before = ctx_json.read_text()
        self.bw("learn-all", "connect", "--run", "la-1", "--apply")
        self.assertEqual(ctx_json.read_text(), before)
        cov_md = self.root / ".bookworm/context/coverage.md"
        with open(cov_md, "a") as f:
            f.write("\n## Reasons for gaps\n\n- scripts: build stubs\n")
        self.bw("learn-all", "coverage", "--run", "la-1", "--write")
        text = cov_md.read_text()
        self.assertIn("- scripts: build stubs", text)
        self.assertEqual(text.count("## Contexts"), 1)

    def test_max_parallel_env(self):
        self.bw("init")
        atlas = self.root / "atlas.json"
        jobs = [{"job": f"j{i}", "context_id": f"c{i}", "folder": f"core/c{i}", "include": ["app:src/types.ts"],
                 "depth": "light", "wave": 1, "neighbors": [], "why": "x"} for i in range(4)]
        atlas.write_text(json.dumps({"jobs": jobs}))
        self.bw("learn-all", "start", "--atlas", atlas)
        os.environ["BOOKWORM_MAX_PARALLEL"] = "2"
        try:
            self.assertIn("wave 1: dispatch 2", self.bw("learn-all", "next"))
            self.assertIn("still running", self.bw("learn-all", "next"))
        finally:
            os.environ.pop("BOOKWORM_MAX_PARALLEL")
        self.assertIn("wave 1: dispatch 2", self.bw("learn-all", "next"))  # default cap 4: 2 more
        for v, n in (("bad", 4), ("0", 1), ("9", 4)):
            os.environ["BOOKWORM_MAX_PARALLEL"] = v
            try:
                self.assertEqual(learn.max_parallel(), n)
            finally:
                os.environ.pop("BOOKWORM_MAX_PARALLEL")

    def test_fail_retry_then_failed(self):
        self.bw("init")
        atlas = self.root / "atlas.json"
        atlas.write_text(json.dumps(self.ATLAS))
        self.bw("learn-all", "start", "--atlas", atlas)
        self.bw("learn-all", "next")
        self.assertIn("re-queued", self.bw("learn-all", "fail", "types", "empty", "--include", "app:src/types.ts"))
        self.assertIn("narrowed include", self.bw("learn-all", "brief", "types"))
        self.bw("learn-all", "next")
        self.assertIn("failed", self.bw("learn-all", "fail", "types", "empty again"))
        self.assertIn("job types not done", self.bw("learn-all", "done", "types", code=1))


class TestGuard(unittest.TestCase):
    def decide(self, agent, tool, inp, cwd=None):
        sys.path.insert(0, str(SCRIPTS / "hooks"))
        import guard
        return guard.decide({"agent_type": agent, "tool_name": tool, "tool_input": inp, "cwd": cwd or str(FIXTURE)})

    def test_10_inspector_and_knowledge(self):
        self.assertIsNotNone(self.decide("bookworm:bw-inspector", "Write", {"file_path": "x.md"}))
        self.assertIsNone(self.decide("bookworm:bw-inspector", "Bash", {"command": "bw ctx stale a --diff"}))
        self.assertIsNone(self.decide("bookworm:bw-inspector", "Bash", {"command": "git log -3 -- src | head"}))
        self.assertIsNone(self.decide("bookworm:bw-inspector", "Bash",
                                      {"command": "bw findings put a <<'EOF'\n- rm -rf x; git commit\nEOF"}))
        for cmd in ("bw publish -m x", "rm -rf .bookworm", "git commit -m x", "cat a > b", "echo $(rm x)",
                    "bw task show 1; rm x", "find . -delete", "sed -i s/a/b/ f", "bw learn-all coverage --write"):
            self.assertIsNotNone(self.decide("bookworm:bw-inspector", "Bash", {"command": cmd}), cmd)
        src = str(FIXTURE / "src" / "types.ts")
        self.assertIsNotNone(self.decide("bookworm:bw-knowledge", "Edit", {"file_path": src}))
        self.assertIsNotNone(self.decide("bookworm:bw-knowledge", "Bash", {"command": "git add -A"}))
        self.assertIsNotNone(self.decide("bookworm:bw-knowledge", "Bash", {"command": "echo x >> src/a.ts"}))
        self.assertIsNone(self.decide("bookworm:bw-knowledge", "Bash", {"command": "bw ctx refresh a && bw publish -m b"}))
        ok = ["cd .bookworm/context/x && cat > x-verification.md <<'E'\nhi\nE",
              "sed -i 's/a/b/' .bookworm/context/x/x.md", "echo hi > .bookworm/.cache/n.md"]
        for cmd in ok:
            self.assertIsNone(self.decide("bookworm:bw-knowledge", "Bash", {"command": cmd}), cmd)
        for cmd in ("cd src && echo x > a.ts", "sed -i 's/a/b/' src/a.ts", "cd .bookworm && cp context/x.md ../src/x"):
            self.assertIsNotNone(self.decide("bookworm:bw-knowledge", "Bash", {"command": cmd}), cmd)

    @unittest.skipUnless(os.name == "nt", "Git Bash drive paths")
    def test_knowledge_cd_git_bash_path(self):
        fx = str(FIXTURE).replace("\\", "/")
        gb = "/" + fx[0].lower() + fx[2:]  # D:/x → /d/x
        cmd = f"cd {gb}/.bookworm/context/x && cat > x-verification.md <<'E'\nhi\nE"
        self.assertIsNone(self.decide("bookworm:bw-knowledge", "Bash", {"command": cmd}))
        self.assertIsNotNone(self.decide("bookworm:bw-knowledge", "Bash", {"command": f"cd {gb}/src && cat > a.ts"}))

    def test_11_main_thread_chain_guard(self):
        self.assertIsNotNone(self.decide("", "Bash", {"command": "bw task show 1 SYSTEM; rm -rf .bookworm/tasks"}))
        self.assertIsNone(self.decide("", "Bash", {"command": "npm run build && npm run lint"}))
        self.assertIsNone(self.decide("", "Bash", {"command": "bw task new x; git diff src/a.ts | head -30"}))
        self.assertIsNotNone(self.decide("", "Bash", {"command": "bw task show 1 && git reset --hard"}))
        self.assertIsNotNone(self.decide("", "Bash", {"command": "bw task show 1; python -c 'x'"}))
        # backslash line continuations are one command, also with a heredoc plan
        cont = ('bw task new x --goal "g" \\\n  --step "a" \\\n  --check build pass "npm run build" \\\n'
                "  --affects m --plan - <<'EOF'\n# plan\nEOF")
        self.assertIsNone(self.decide("", "Bash", {"command": cont}))
        self.assertIsNotNone(self.decide("", "Bash", {"command": "bw task show 1 \\\n; rm -rf x"}))
        self.assertIsNotNone(self.decide("", "Bash", {"command": "bw task show 1 \\\n && rm -rf x"}))


if __name__ == "__main__":
    unittest.main()
