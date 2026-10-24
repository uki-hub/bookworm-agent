"""Source listing and LF-normalized hashing across registered repos."""

from __future__ import annotations

import hashlib
import os
import subprocess

from .util import glob_match, has_magic

DEFAULT_EXCLUDES = [
    ".bookworm/**", ".git/**", ".claude/**", ".opencode/**", "node_modules/**", "vendor/**",
    "dist/**", "build/**", "out/**", "coverage/**", ".next/**", ".nuxt/**", ".venv/**", "venv/**",
    "__pycache__/**", "*.pyc", ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", ".DS_Store",
]
HASH_LEN = 16


def excluded(rel, patterns):
    for p in patterns:
        if glob_match(p, rel) or (not p.startswith("**/") and glob_match("**/" + p, rel)):
            return True
    return False


def run_git(cwd, *args, check=False, env=None, text=True):
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=text,
                           env=env, encoding="utf-8" if text else None, errors="replace" if text else None)
    except FileNotFoundError:
        return None
    if check and r.returncode != 0:
        from .util import BwError
        raise BwError(f"git {' '.join(args)} failed: {(r.stderr or '').strip()}")
    return r


def is_git_repo(path):
    r = run_git(path, "rev-parse", "--show-toplevel")
    if r is None or r.returncode != 0:
        return False
    return os.path.normcase(os.path.realpath(r.stdout.strip())) == os.path.normcase(os.path.realpath(path))


def git_head(path):
    r = run_git(path, "rev-parse", "--short", "HEAD")
    return r.stdout.strip() if r is not None and r.returncode == 0 else None


def file_hash(path):
    """sha256 of the file with CRLF→LF for text (no NUL in first 8 KB); first 16 hex."""
    with open(path, "rb") as f:
        data = f.read()
    if b"\0" not in data[:8192]:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()[:HASH_LEN]


class Snapshot:
    """Per-process cache of listings and hashes for a workspace."""

    def __init__(self, ws):
        self.ws = ws
        self._lists = {}
        self._hashes = {}
        cfg = ws.config if ws.exists else {}
        self.patterns = DEFAULT_EXCLUDES + list(cfg.get("excludes", []))

    def list_repo(self, rid):
        if rid in self._lists:
            return self._lists[rid]
        root = self.ws.repo_path(rid)
        files = []
        if is_git_repo(root):
            r = run_git(root, "-c", "core.quotepath=off", "ls-files", "-z", "-co", "--exclude-standard")
            seen = set()
            for rel in (r.stdout.split("\0") if r and r.returncode == 0 else []):
                if rel and rel not in seen and (root / rel).is_file():
                    seen.add(rel)
                    files.append(rel)
        else:
            for dirpath, dirnames, names in os.walk(root):
                reldir = os.path.relpath(dirpath, root).replace("\\", "/")
                reldir = "" if reldir == "." else reldir + "/"
                dirnames[:] = [d for d in dirnames if not excluded(reldir + d + "/x", self.patterns)]
                files.extend(reldir + n for n in names)
        files = sorted(f for f in files if not excluded(f, self.patterns))
        self._lists[rid] = files
        return files

    def all_files(self):
        return [f"{rid}:{rel}" for rid, _ in self.ws.repos for rel in self.list_repo(rid)]

    def hash(self, qpath):
        if qpath not in self._hashes:
            p = self.ws.abs(qpath)
            self._hashes[qpath] = file_hash(p) if p.is_file() else None
        return self._hashes[qpath]

    def hashes(self, qpaths):
        return {q: self.hash(q) for q in qpaths if self.hash(q) is not None}

    def full(self):
        return self.hashes(self.all_files())

    def match(self, includes):
        """Files matching any 'repo:glob' include. A plain directory means everything under it."""
        result = []
        for inc in includes:
            rid, _, pat = self.ws.qualify(inc).partition(":")
            pat = pat.rstrip("/")
            try:
                root = self.ws.repo_path(rid)
            except Exception:
                continue
            if not has_magic(pat) and (root / pat).is_dir():
                pat = pat + "/**"
            for rel in self.list_repo(rid):
                if glob_match(pat, rel):
                    result.append(f"{rid}:{rel}")
        return sorted(set(result))


def fingerprint(hashes):
    h = hashlib.sha256()
    for k in sorted(hashes):
        h.update(f"{k}\0{hashes[k]}\n".encode("utf-8"))
    return h.hexdigest()[:HASH_LEN]


def diff_hashes(before, after):
    added = sorted(k for k in after if k not in before)
    deleted = sorted(k for k in before if k not in after)
    modified = sorted(k for k in after if k in before and before[k] != after[k])
    return added, modified, deleted
