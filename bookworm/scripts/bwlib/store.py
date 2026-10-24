"""Workspace discovery, config, record lookup and the write lock."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from .util import BwError, SLUG, now, pid_alive, read_json, write_json

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = PLUGIN_ROOT / "templates"
LOCK_STALE_SECONDS = 2 * 3600


def template(tpl, **values):
    text = (TEMPLATES / tpl).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.bw = self.root / ".bookworm"
        self.ctx_dir = self.bw / "context"
        self.tasks_dir = self.bw / "tasks"
        self.runs_dir = self.bw / "runs"
        self.cache = self.bw / ".cache"
        self._config = None
        self._contexts = None

    # ---- discovery -------------------------------------------------------
    @classmethod
    def find(cls, required=True):
        env = os.environ.get("BOOKWORM_ROOT")
        starts = [Path(env)] if env else []
        starts.append(Path.cwd())
        if os.environ.get("CLAUDE_PROJECT_DIR"):
            starts.append(Path(os.environ["CLAUDE_PROJECT_DIR"]))
        for start in starts:
            p = start.resolve()
            for cand in [p, *p.parents]:
                if (cand / ".bookworm" / "bookworm.json").is_file():
                    return cls(cand)
        if required:
            raise BwError("no .bookworm/ workspace here. Run /bookworm:init (or `bw init`) first.")
        return None

    @property
    def exists(self):
        return (self.bw / "bookworm.json").is_file()

    # ---- config ----------------------------------------------------------
    @property
    def config(self):
        if self._config is None:
            self._config = read_json(self.bw / "bookworm.json")
        return self._config

    def save_config(self):
        write_json(self.bw / "bookworm.json", self.config)

    @property
    def mode(self):
        return self.config.get("git", {}).get("mode", "dedicated")

    @property
    def policy(self):
        return self.config.get("git", {}).get("policy", "auto")

    @property
    def repos(self):
        return [(r["id"], (self.root / r["path"]).resolve()) for r in self.config.get("repos", [])]

    def repo_path(self, repo_id):
        for rid, path in self.repos:
            if rid == repo_id:
                return path
        raise BwError(f"unknown repo id '{repo_id}' (known: {', '.join(r for r, _ in self.repos)})")

    @property
    def default_repo(self):
        return self.repos[0][0]

    def qualify(self, path):
        """'src/x.ts' → 'app:src/x.ts'. Accepts already-qualified paths."""
        path = path.replace("\\", "/").strip()
        rid, sep, rest = path.partition(":")
        if sep and rid in {r for r, _ in self.repos}:
            return f"{rid}:{rest[2:] if rest.startswith('./') else rest}"
        if sep and len(rid) == 1:  # drive letter: absolute Windows path
            return self.qualify_abs(path)
        if os.path.isabs(path):
            return self.qualify_abs(path)
        return f"{self.default_repo}:{path[2:] if path.startswith('./') else path}"

    def qualify_abs(self, path):
        p = Path(path).resolve()
        for rid, root in self.repos:
            try:
                return f"{rid}:{p.relative_to(root).as_posix()}"
            except ValueError:
                continue
        raise BwError(f"path is outside every registered repo: {path}")

    def split(self, qpath):
        rid, _, rel = self.qualify(qpath).partition(":")
        return rid, rel

    def abs(self, qpath):
        rid, rel = self.split(qpath)
        return self.repo_path(rid) / rel

    def rel(self, path):
        """Workspace-relative display path."""
        try:
            return Path(path).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    # ---- contexts --------------------------------------------------------
    def contexts(self, refresh=False):
        """id → Context, found by scanning context/**/context.json."""
        if self._contexts is None or refresh:
            found = {}
            if self.ctx_dir.is_dir():
                for mf in sorted(self.ctx_dir.rglob("context.json")):
                    try:
                        data = json.loads(mf.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as e:
                        found[f"!invalid:{self.rel(mf)}"] = Context(self, mf.parent, None, str(e))
                        continue
                    cid = data.get("id") if isinstance(data, dict) else None
                    key = cid if isinstance(cid, str) and cid not in found else f"!dup:{self.rel(mf)}"
                    found[key] = Context(self, mf.parent, data)
            self._contexts = found
        return self._contexts

    def ctx(self, cid):
        c = self.contexts().get(cid)
        if not c:
            known = ", ".join(k for k in self.contexts() if not k.startswith("!")) or "none"
            raise BwError(f"unknown context '{cid}' (known: {known})")
        return c

    # ---- tasks / runs ----------------------------------------------------
    def task_ids(self):
        if not self.tasks_dir.is_dir():
            return []
        ids = [p.name for p in self.tasks_dir.iterdir() if (p / "task.json").is_file()]
        return sorted(ids, key=lambda s: (int(s.split("-")[0]) if s.split("-")[0].isdigit() else 0, s))

    def task_dir(self, tid):
        d = self.tasks_dir / tid
        if not (d / "task.json").is_file():
            matches = [t for t in self.task_ids() if t.split("-")[0] == tid or t.startswith(tid + "-")]
            if len(matches) == 1:
                return self.tasks_dir / matches[0]
            raise BwError(f"unknown task '{tid}' (open: {', '.join(self.task_ids()) or 'none'})")
        return d

    def load_task(self, tid):
        d = self.task_dir(tid)
        return d, read_json(d / "task.json")

    def save_task(self, d, data):
        data["updated_at"] = now()
        write_json(d / "task.json", data)

    def run_path(self, rid):
        return self.runs_dir / rid / "run.json"

    def load_run(self, ref):
        """Accept a run id or a task id (→ the task's current run)."""
        p = self.run_path(ref)
        if p.is_file():
            return p, read_json(p)
        try:
            _, task = self.load_task(ref)
        except BwError:
            raise BwError(f"unknown run or task '{ref}'")
        if not task.get("run"):
            raise BwError(f"task {task['id']} has no run. Start one: bw run start {task['id']}")
        p = self.run_path(task["run"])
        return p, read_json(p)

    # ---- lock ------------------------------------------------------------
    @contextmanager
    def lock(self, cmd):
        self.cache.mkdir(parents=True, exist_ok=True)
        path = self.cache / "lock"
        for _ in range(50):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    json.dump({"pid": os.getpid(), "time": time.time(), "cmd": cmd}, f)
                break
            except FileExistsError:
                info = lock_info(path)
                if info is None or info["stale"]:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    continue
                time.sleep(0.1)
        else:
            info = lock_info(path) or {}
            raise BwError(f"workspace locked by pid {info.get('pid')} ({info.get('cmd')}). "
                          "If that process is gone: bw lock release --force")
        try:
            yield
        finally:
            try:
                path.unlink()
            except OSError:
                pass


def lock_info(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"pid": None, "cmd": "?", "age": 0, "stale": True}
    age = time.time() - float(data.get("time", 0))
    stale = age > LOCK_STALE_SECONDS or not pid_alive(int(data.get("pid") or 0))
    return {**data, "age": age, "stale": stale}


class Context:
    def __init__(self, ws, folder, data, error=None):
        self.ws = ws
        self.folder = Path(folder)
        self.data = data or {}
        self.error = error

    @property
    def id(self):
        return self.data.get("id")

    @property
    def version(self):
        return int(self.data.get("version") or 0)

    @property
    def rel_folder(self):
        """Folder relative to .bookworm/context (e.g. features/detective-scan)."""
        return self.folder.relative_to(self.ws.ctx_dir).as_posix()

    @property
    def display(self):
        return self.ws.rel(self.folder)

    def save(self):
        self.data["updated_at"] = now()
        write_json(self.folder / "context.json", self.data)

    @property
    def includes(self):
        return [self.ws.qualify(p) for p in (self.data.get("sources") or {}).get("include", [])]

    def router(self):
        return (self.data.get("docs") or {}).get("router")


def validate_id(cid, what="id"):
    if not isinstance(cid, str) or not SLUG.match(cid):
        raise BwError(f"invalid {what} '{cid}': use lowercase letters, digits and dashes")
    return cid
