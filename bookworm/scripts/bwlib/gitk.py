"""Knowledge git: dedicated .bookworm/.git or knowledge-only commits in the project repo."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .snapshot import run_git
from .util import BwError

DEDICATED_GITIGNORE = "# Bookworm knowledge repo: only the overview and contexts are versioned.\n/*\n!/.gitignore\n!/context.md\n!/context/\n"


def root(ws):
    if ws.mode == "dedicated":
        return ws.bw
    r = run_git(ws.root, "rev-parse", "--show-toplevel")
    if r is None or r.returncode != 0:
        raise BwError("repo mode needs the workspace inside a git repository")
    return Path(r.stdout.strip())


def prefix(ws):
    """Path of .bookworm inside the knowledge repo ('' for dedicated)."""
    if ws.mode == "dedicated":
        return ""
    return ws.bw.resolve().relative_to(root(ws).resolve()).as_posix() + "/"


def pathspecs(ws, folders=None):
    p = prefix(ws)
    specs = [p + "context.md"]
    specs += [p + "context/" + f for f in folders] if folders is not None else [p + "context"]
    return specs


def identity(cwd):
    r = run_git(cwd, "config", "user.email")
    if r is not None and r.returncode == 0 and r.stdout.strip():
        return []
    return ["-c", "user.name=Bookworm", "-c", "user.email=bookworm@localhost"]


def git(ws, *args, check=True, env=None):
    return run_git(root(ws), *args, check=check, env=env)


def init_dedicated(ws):
    created = False
    if not (ws.bw / ".git").exists():
        run_git(ws.bw, "init", "-q", check=True)
        created = True
    run_git(ws.bw, "config", "core.autocrlf", "false", check=True)
    gi = ws.bw / ".gitignore"
    if not gi.exists():
        gi.write_text(DEDICATED_GITIGNORE, encoding="utf-8", newline="\n")
    return created


def head(ws):
    r = git(ws, "rev-parse", "--short", "HEAD", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def changes(ws, folders=None):
    """Uncommitted knowledge changes: list of paths relative to .bookworm."""
    r = git(ws, "-c", "core.quotepath=off", "status", "--porcelain", "-uall", "--", *pathspecs(ws, folders),
            check=False)
    p = prefix(ws)
    paths = []
    for line in r.stdout.splitlines():
        path = line[3:].split(" -> ")[-1].strip('"')
        paths.append(path[len(p):] if p and path.startswith(p) else path)
    return paths


def show(ws, rel):
    """File content at knowledge HEAD (rel to .bookworm) or None."""
    r = git(ws, "show", f"HEAD:{prefix(ws)}{rel}", check=False)
    return r.stdout if r.returncode == 0 else None


def commit_exists(ws, commit):
    if not commit:
        return False
    r = git(ws, "cat-file", "-e", f"{commit}^{{commit}}", check=False)
    return r.returncode == 0


def last_commit(ws, rel):
    r = git(ws, "log", "-1", "--format=%h", "--", prefix(ws) + rel, check=False)
    return r.stdout.strip() or None


def commit(ws, message, folders=None):
    """Commit knowledge paths only. Returns the short hash, or None if nothing changed."""
    specs = [s for s in pathspecs(ws, folders)
             if (root(ws) / s).exists() or git(ws, "ls-files", "--error-unmatch", "--", s, check=False).returncode == 0]
    if not specs:
        return None
    ident = identity(root(ws))
    if ws.mode == "dedicated":
        git(ws, "add", "-A", "--", *specs)
        if git(ws, "diff", "--cached", "--quiet", check=False).returncode == 0:
            return None
        git(ws, *ident, "commit", "-q", "-m", message)
        return head(ws)
    # repo mode: build the commit from an isolated index so user staging is untouched
    with tempfile.TemporaryDirectory(prefix="bw-index-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
        parent = git(ws, "rev-parse", "HEAD", check=False).stdout.strip()
        if parent:
            git(ws, "read-tree", "HEAD", env=env)
        git(ws, "add", "-A", "--", *specs, env=env)
        tree = git(ws, "write-tree", env=env).stdout.strip()
        if parent and git(ws, "rev-parse", "HEAD^{tree}").stdout.strip() == tree:
            return None
        args = ["commit-tree", tree, "-m", message] + (["-p", parent] if parent else [])
        new = git(ws, *ident, *args).stdout.strip()
        git(ws, "update-ref", "-m", "bookworm publish", "HEAD", new, *([parent] if parent else []))
    git(ws, "reset", "-q", "HEAD", "--", *specs, check=False)  # sync real index for knowledge paths only
    return head(ws)


def add_exclude(repo_root, entry):
    """Add an entry to <repo>/.git/info/exclude (local, never committed)."""
    r = run_git(repo_root, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")
    if r is None or r.returncode != 0:
        return False
    path = Path(r.stdout.strip())
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if entry in text.splitlines():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if text.endswith("\n") or not text else "\n") + entry + "\n")
    return True
