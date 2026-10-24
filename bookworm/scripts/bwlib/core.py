"""init, status, check, findings, affected."""

from __future__ import annotations

from pathlib import Path

from . import ctx as ctxmod
from . import gitk, learn
from .snapshot import Snapshot, is_git_repo
from .store import Workspace, lock_info
from .task import readiness
from .util import BwError, now, out, read_json, short, write_json, write_text

KNOWN_TOP = {"bookworm.json", "context.md", "context", "tasks", "runs", ".cache", ".git", ".gitignore"}


def cmd_init(root, mode=None, policy=None, repos=None):
    if mode not in (None, "dedicated", "repo"):
        raise BwError("--mode must be dedicated or repo")
    if policy not in (None, "auto", "manual"):
        raise BwError("--policy must be auto or manual")
    ws = Workspace(root)
    changes = []
    if ws.exists:
        cfg = ws.config
        if mode and cfg["git"]["mode"] != mode:
            out(f"note: workspace already uses mode {cfg['git']['mode']}; leaving it")
    else:
        mode = mode or "dedicated"
        policy = policy or ("auto" if mode == "dedicated" else "manual")
        repo_list = []
        for spec in repos or []:
            rid, _, path = spec.partition("=")
            repo_list.append({"id": rid.strip(), "path": path.strip() or "."})
        if not repo_list:
            repo_list = [{"id": "app", "path": "."}]
        cfg = {"schema": 1, "repos": repo_list, "git": {"mode": mode, "policy": policy},
               "excludes": [], "created_at": now()}
        ws.bw.mkdir(parents=True, exist_ok=True)
        write_json(ws.bw / "bookworm.json", cfg)
        changes.append("config")
    ws._config = None
    for d in (ws.ctx_dir, ws.tasks_dir, ws.runs_dir, ws.cache):
        if not d.is_dir():
            d.mkdir(parents=True)
            changes.append(ws.rel(d) + "/")
    src_root = ws.root
    if ws.mode == "dedicated":
        if gitk.init_dedicated(ws):
            changes.append("knowledge git .bookworm/.git")
        if is_git_repo(src_root) and gitk.add_exclude(src_root, "/.bookworm/"):
            changes.append("'/.bookworm/' in .git/info/exclude")
    elif gitk.add_exclude(src_root, "/.bookworm/.cache/"):
        changes.append("'/.bookworm/.cache/' in .git/info/exclude")
    if ws.mode == "dedicated" and gitk.head(ws) is None:
        gitk.git(ws, "add", "-A", "--", ".gitignore")
        gitk.git(ws, *gitk.identity(ws.bw), "commit", "-q", "-m", "bookworm init")
        changes.append(f"initial knowledge commit {gitk.head(ws)}")
    if not changes:
        out(f"already initialized at {ws.bw} (mode {ws.mode}, policy {ws.policy}); nothing changed")
        out("overview: " + ("present (.bookworm/context.md)" if (ws.bw / "context.md").exists() else "MISSING (.bookworm/context.md)"))
        return
    out(f"initialized {ws.rel(ws.bw) or ws.bw} (mode {ws.mode}, policy {ws.policy}):")
    for c in changes:
        out(f"  + {c}")
    out("repos: " + ", ".join(f"{r['id']}={r['path']}" for r in ws.config["repos"]))
    if not (ws.bw / "context.md").exists():
        out("next: write .bookworm/context.md (purpose, repo map, run/test, reading routes); "
            "it is published with the first learn. Shape: bw template overview")


def summary(ws):
    snap = Snapshot(ws)
    ctxs = {k: c for k, c in ws.contexts().items() if not k.startswith("!")}
    labels = {k: ctxmod.label(ctxmod.stale_info(ws, c, snap)) for k, c in ctxs.items()}
    stale = [k for k, v in labels.items() if v == "STALE"]
    review = [k for k, v in labels.items() if v == "REVIEW"]
    open_tasks = []
    for tid in ws.task_ids():
        t = read_json(ws.tasks_dir / tid / "task.json")
        if t.get("status") != "done":
            open_tasks.append((t, readiness(ws, t, snap)[0]))
    return ctxs, stale, review, open_tasks


def cmd_status(ws, brief=False):
    ctxs, stale, review, open_tasks = summary(ws)
    unpublished = gitk.changes(ws)
    la = learn.active_run(ws)
    lock = lock_info(ws.cache / "lock")
    if brief:
        has_ov = (ws.bw / "context.md").is_file()
        out("Bookworm: read .bookworm/context.md before feature work." if has_ov
            else "Bookworm: no overview yet (.bookworm/context.md); /bookworm:init drafts one.")
        out(f"{len(ctxs)} contexts" + (f" ({len(stale)} stale: {', '.join(stale[:5])})" if stale else "")
            + (f" ({len(review)} to review, dependency changed: {', '.join(review[:5])})" if review else "")
            + (f"; {len(unpublished)} unpublished knowledge file(s)" if unpublished else "") + ".")
        if open_tasks:
            out("Open: " + "; ".join(f"{t['id']} ({t['status']}, {lvl})" for t, lvl in open_tasks[:5])
                + (" …" if len(open_tasks) > 5 else ""))
        if la:
            out(f"learn-all {la} in progress: /bookworm:learn-all --resume")
        return
    out(f"workspace {ws.root} (mode {ws.mode}, policy {ws.policy}; knowledge HEAD {gitk.head(ws)})")
    out(f"contexts: {len(ctxs)}" + (f"; stale: {', '.join(stale)}" if stale else "")
        + (f"; review (dependency changed): {', '.join(review)}" if review else ""))
    for t, lvl in open_tasks:
        out(f"task {t['id']}: {t['kind']} {t['status']} readiness {lvl} — {short(t.get('goal', ''), 70)}")
    if unpublished:
        out(f"unpublished: {', '.join(unpublished[:10])}")
    if la:
        out(f"learn-all active: {la}")
    if lock:
        out(f"lock: pid {lock.get('pid')} {lock.get('cmd')} {'(stale)' if lock['stale'] else ''}")


def cmd_check(ws):
    errs, warns = ctxmod.validate_all(ws)
    try:
        cfg = ws.config
        for rid, p in ws.repos:
            if not p.is_dir():
                errs.append(f"repo {rid}: {p} is not a directory")
        if cfg.get("git", {}).get("mode") not in ("dedicated", "repo"):
            errs.append("bookworm.json: git.mode must be dedicated or repo")
    except BwError as e:
        errs.append(str(e))
    for tid in ws.task_ids():
        t = read_json(ws.tasks_dir / tid / "task.json")
        for key in ("id", "kind", "status", "revision", "goal"):
            if key not in t:
                errs.append(f"task {tid}: missing '{key}'")
        if t.get("id") != tid:
            errs.append(f"task {tid}: id field '{t.get('id')}' does not match folder")
        for p in t.get("consumes", []):
            if p.get("id") not in ws.contexts():
                warns.append(f"task {tid}: consumes missing context {p.get('id')} (readiness blocked)")
        if t.get("run") and not ws.run_path(t["run"]).is_file():
            errs.append(f"task {tid}: run {t['run']} has no run.json")
    for p in ws.bw.iterdir() if ws.bw.is_dir() else []:
        if p.name not in KNOWN_TOP:
            warns.append(f"unexpected file in .bookworm/: {p.name}")
    for e in errs:
        out(f"error: {e}")
    for w in warns:
        out(f"warning: {w}")
    out(f"check: {len(errs)} error(s), {len(warns)} warning(s)")
    return 1 if errs else 0


def cmd_findings_put(ws, cid, source):
    import sys
    c = ws.ctx(cid)
    text = sys.stdin.read() if source in (None, "-") else Path(source).read_text(encoding="utf-8")
    if not text.strip():
        raise BwError("no findings text given (pipe it on stdin or pass a file)")
    path = ws.cache / "findings" / f"{cid}.md"
    write_text(path, f"<!-- findings for {cid} v{c.version}, {now()} -->\n{text.strip()}\n")
    out(f"saved findings for {cid} ({len(text.splitlines())} lines) → {ws.rel(path)}; "
        f"/bookworm:context-update {cid} will use them")


def cmd_findings_get(ws, cid):
    path = ws.cache / "findings" / f"{cid}.md"
    if not path.is_file():
        out(f"no cached findings for {cid}")
        return
    out(path.read_text(encoding="utf-8").rstrip())


def cmd_affected(ws, ref):
    if ref in ws.contexts():
        c = ws.ctx(ref)
        snap = Snapshot(ws)
        info = ctxmod.stale_info(ws, c, snap)
        out(f"context {ref} v{c.version}: {ctxmod.label(info)}")
        deps = ctxmod.dependents(ws, ref)
        out("reverse dependents: " + (", ".join(f"{o} ({w})" for o, w in deps) or "none"))
        users = ctxmod.tasks_using(ws, ref)
        out("tasks: " + (", ".join(f"{t} [{s}] {w}" for t, s, w in users) or "none"))
        for ln in ctxmod.stale_lines(ws, c, info)[1:]:
            out(ln)
        return
    d, t = ws.load_task(ref)
    snap = Snapshot(ws)
    level, reasons = readiness(ws, t, snap)
    out(f"task {t['id']} ({t['status']}, readiness {level})")
    ids = list(dict.fromkeys([p["id"] for p in t.get("consumes", [])] + t.get("affects", [])))
    for cid in ids:
        c = ws.contexts().get(cid)
        role = ", ".join(r for r, ok in (("consumes", cid in [p["id"] for p in t.get("consumes", [])]),
                                         ("affects", cid in t.get("affects", []))) if ok)
        if c is None:
            out(f"  {cid} ({role}): MISSING")
            continue
        info = ctxmod.stale_info(ws, c, snap)
        drift = ", ".join(f"{k} {len(v)}" for k, v in info.items() if isinstance(v, list) and v)
        lbl = ctxmod.label(info)
        out(f"  {cid} v{c.version} ({role}): {lbl.lower() + ' — ' + drift if lbl != 'current' else 'current'}")
        for o, w in ctxmod.dependents(ws, cid):
            out(f"    downstream: {o} ({w})")
    if t.get("run") and ws.run_path(t["run"]).is_file():
        from .run import compute_effects
        run = read_json(ws.run_path(t["run"]))
        rows = compute_effects(ws, run, snap)
        out(f"run {run['id']} effects: {len(rows)} file(s)")
        for r in rows[:20]:
            out(f"  {r['change']:8} {r['path']} → {', '.join(r['contexts']) or 'unmapped'}")
    for why in reasons:
        out(f"readiness: {why}")
