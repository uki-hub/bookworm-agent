"""Contexts: validation, staleness, refresh, scaffolding, navigation, publish."""

from __future__ import annotations

import json
import re
import shutil

from . import gitk
from .snapshot import Snapshot, run_git, git_head
from .store import validate_id
from .util import BwError, SLUG, now, out, read_json, short, write_json

MANIFEST_KEYS = {"id", "title", "type", "parent", "version", "docs", "depends_on", "related", "sources",
                 "anchors", "upstream_seen", "updated_at"}
VOLATILE_KEYS = {"version", "updated_at", "upstream_seen"}
VOLATILE_SOURCE_KEYS = {"hashes", "git"}


# ---- validation ------------------------------------------------------------
def validate_manifest(ws, c, ids):
    """Return (errors, warnings) for one context."""
    errs, warns = [], []
    d = c.data
    where = c.display
    if c.error:
        return [f"{where}: context.json is not valid JSON ({c.error})"], []
    if not SLUG.match(str(d.get("id", ""))):
        errs.append(f"{where}: id must be a lowercase slug")
    for key in ("title", "type"):
        if not isinstance(d.get(key), str) or not d.get(key):
            errs.append(f"{where}: '{key}' must be a non-empty string")
    if not isinstance(d.get("version"), int) or d["version"] < 1:
        errs.append(f"{where}: version must be an integer ≥ 1")
    unknown = set(d) - MANIFEST_KEYS
    if unknown:
        warns.append(f"{where}: unknown keys {sorted(unknown)}")
    docs = d.get("docs")
    if not isinstance(docs, dict) or not docs.get("router"):
        errs.append(f"{where}: docs.router is required")
    else:
        for name, rel in docs.items():
            if not isinstance(rel, str) or "/" in rel or "\\" in rel or not (c.folder / rel).is_file():
                errs.append(f"{where}: docs.{name} '{rel}' is not a file in the context folder")
    parent = d.get("parent")
    if parent is not None and parent not in ids:
        errs.append(f"{where}: parent '{parent}' does not exist")
    for dep in d.get("depends_on") or []:
        if not isinstance(dep, dict) or not dep.get("id") or not dep.get("reason"):
            errs.append(f"{where}: depends_on entries need id and reason")
        elif dep["id"] not in ids:
            errs.append(f"{where}: depends_on '{dep['id']}' does not exist")
        elif dep["id"] == d.get("id"):
            errs.append(f"{where}: depends on itself")
    for rel in d.get("related") or []:
        if rel not in ids:
            errs.append(f"{where}: related '{rel}' does not exist")
    src = d.get("sources")
    if not isinstance(src, dict) or not isinstance(src.get("include"), list) or not src["include"]:
        errs.append(f"{where}: sources.include must list at least one 'repo:glob'")
    else:
        for inc in src["include"]:
            try:
                ws.repo_path(ws.split(inc)[0])
            except BwError as e:
                errs.append(f"{where}: include '{inc}': {e}")
        if not src.get("hashes"):
            warns.append(f"{where}: never refreshed (run: bw ctx refresh {d.get('id')})")
    for a in d.get("anchors") or []:
        if not isinstance(a, dict) or not a.get("path") or not a.get("when"):
            errs.append(f"{where}: anchors need path and when")
    for f in c.folder.iterdir():
        if f.is_file() and f.name != "context.json" and f.name not in (docs or {}).values() and f.suffix == ".md" \
                and not f.name.endswith("-verification.md"):
            warns.append(f"{where}: {f.name} is not listed in docs")
    return errs, warns


def cycles(ws):
    """Cycles over parent + depends_on edges."""
    graph = {}
    for cid, c in ws.contexts().items():
        if cid.startswith("!"):
            continue
        edges = [dep.get("id") for dep in c.data.get("depends_on") or [] if isinstance(dep, dict)]
        if c.data.get("parent"):
            edges.append(c.data["parent"])
        graph[cid] = [e for e in edges if e in ws.contexts()]
    found, state = [], {}

    def visit(n, stack):
        state[n] = 1
        for m in graph.get(n, []):
            if state.get(m) == 1:
                found.append(" → ".join(stack[stack.index(m):] + [m]) if m in stack else f"{n} → {m}")
            elif not state.get(m):
                visit(m, stack + [m])
        state[n] = 2

    for n in graph:
        if not state.get(n):
            visit(n, [n])
    return found


def overview_missing_routes(ws):
    path = ws.bw / "context.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = []
    for cid, c in ws.contexts().items():
        if cid.startswith("!"):
            continue
        if f"context/{c.rel_folder}/" not in text and not re.search(rf"(?<![\w-]){re.escape(cid)}(?![\w-])", text):
            missing.append(cid)
    return missing


def validate_all(ws):
    errs, warns = [], []
    ids = {k for k in ws.contexts() if not k.startswith("!")}
    for cid, c in ws.contexts().items():
        if cid.startswith("!dup"):
            errs.append(f"{c.display}: duplicate id '{c.data.get('id')}'")
            continue
        e, w = validate_manifest(ws, c, ids)
        errs += e
        warns += w
    errs += [f"cycle: {cy}" for cy in cycles(ws)]
    for cid in overview_missing_routes(ws):
        warns.append(f"context.md has no reading route to '{cid}'")
    return errs, warns


# ---- staleness -------------------------------------------------------------
def stale_info(ws, c, snap):
    """{'changed','added','deleted','upstream','never'} for one context."""
    src = c.data.get("sources") or {}
    old = src.get("hashes") or {}
    cur = snap.hashes(snap.match(c.includes))
    info = {"changed": [], "added": [], "deleted": [], "upstream": [], "never": not old}
    if old:
        info["changed"] = sorted(k for k in cur if k in old and old[k] != cur[k])
        info["added"] = sorted(k for k in cur if k not in old)
        info["deleted"] = sorted(k for k in old if k not in cur)
    seen = c.data.get("upstream_seen") or {}
    for dep in c.data.get("depends_on") or []:
        up = ws.contexts().get(dep.get("id"))
        if up is None:
            info["upstream"].append(f"{dep.get('id')} missing")
        elif up.version > int(seen.get(up.id, 0)):
            info["upstream"].append(f"{up.id} v{up.version} > seen v{seen.get(up.id, 0)}")
    return info


def is_stale(info):
    return bool(own_stale(info) or info["upstream"])


def own_stale(info):
    """Drift in the context's own sources (blocks readiness); upstream-only drift is a review suggestion."""
    return bool(info["never"] or info["changed"] or info["added"] or info["deleted"])


def label(info):
    return "STALE" if own_stale(info) else "REVIEW" if info["upstream"] else "current"


def dep_order(ws, ids):
    """ids ordered so each context comes after the ones it depends on (stable by id)."""
    want, ctxs, res, seen = set(ids), ws.contexts(), [], set()

    def visit(cid):
        if cid in seen:
            return
        seen.add(cid)
        for dep in (ctxs[cid].data.get("depends_on") or []) if cid in ctxs else []:
            if dep.get("id") in want:
                visit(dep["id"])
        res.append(cid)

    for cid in sorted(want):
        visit(cid)
    return res


def stale_lines(ws, c, info, diff=False, max_diff=120):
    if not is_stale(info):
        return [f"{c.id} v{c.version}: current ({len((c.data.get('sources') or {}).get('hashes') or {})} files match; "
                f"docs in .bookworm/context/{c.rel_folder}/)"]
    why = "" if own_stale(info) else "; dependency changed, review suggested"
    lines = [f"{c.id} v{c.version}: {label(info)} (docs in .bookworm/context/{c.rel_folder}/{why})"]
    if info["never"]:
        lines.append("  never refreshed: no source hashes recorded")
    base = (c.data.get("sources") or {}).get("git") or {}
    for kind in ("changed", "added", "deleted"):
        for q in info[kind]:
            rid, rel = ws.split(q)
            stat = ""
            commit = base.get(rid)
            if commit and kind != "added":
                r = run_git(ws.repo_path(rid), "diff", "--numstat", commit, "--", rel)
                if r is not None and r.returncode == 0 and r.stdout.strip():
                    a, d, _ = r.stdout.split("\t", 2)
                    stat = f" (+{a} -{d} since {commit})"
            lines.append(f"  {kind:8} {q}{stat}")
            if diff and kind == "changed" and commit:
                r = run_git(ws.repo_path(rid), "diff", "-U2", commit, "--", rel)
                body = (r.stdout if r is not None else "").splitlines()[4:]
                lines += ["    " + ln for ln in body[:max_diff]]
                if len(body) > max_diff:
                    lines.append(f"    … {len(body) - max_diff} more diff lines")
    for u in info["upstream"]:
        lines.append(f"  upstream {u}")
    return lines


# ---- commands --------------------------------------------------------------
def cmd_new(ws, folder, cid, title=None, ctype="feature", parent=None):
    validate_id(cid)
    if cid in ws.contexts():
        raise BwError(f"context id '{cid}' already exists at {ws.contexts()[cid].display}")
    folder = folder.replace("\\", "/").strip("/")
    for pre in (".bookworm/context/", "context/"):
        if folder.startswith(pre):
            folder = folder[len(pre):]
    if not folder or ".." in folder.split("/"):
        raise BwError("folder must be a path under .bookworm/context/, e.g. features/" + cid)
    if parent and parent not in ws.contexts():
        raise BwError(f"parent '{parent}' does not exist")
    d = ws.ctx_dir / folder
    if (d / "context.json").exists():
        raise BwError(f"{ws.rel(d)} already holds a context")
    title = title or cid.replace("-", " ").capitalize()
    router = f"{cid}-context.md"
    manifest = {"id": cid, "title": title, "type": ctype, "parent": parent, "version": 1,
                "docs": {"router": router}, "depends_on": [], "related": [],
                "sources": {"include": [], "hashes": {}}, "anchors": [], "upstream_seen": {},
                "updated_at": now()}
    d.mkdir(parents=True, exist_ok=True)
    write_json(d / "context.json", manifest)
    out(f"created context {cid} (manifest {ws.rel(d / 'context.json')})")
    out(f"next: write the router {ws.rel(d / router)} (new file), then bw ctx set {cid} --include <repo:glob>… "
        f"and bw ctx refresh {cid}")


def parse_kv(item, what):
    key, sep, val = item.partition("=")
    if not sep or not key.strip() or not val.strip():
        raise BwError(f"{what} must look like id=\"reason\": got '{item}'")
    return key.strip(), val.strip()


def cmd_set(ws, cid, a):
    c = ws.ctx(cid)
    d = c.data
    changed = []
    if a.title:
        d["title"] = a.title
        changed.append("title")
    if a.type:
        d["type"] = a.type
        changed.append("type")
    if a.parent is not None:
        if a.parent and a.parent not in ws.contexts():
            raise BwError(f"parent '{a.parent}' does not exist")
        d["parent"] = a.parent or None
        changed.append("parent")
    add = getattr(a, "add_include", None)
    if a.include and add:
        raise BwError("use --include (replace the list) or --add-include (append), not both")
    if a.include:
        d.setdefault("sources", {})["include"] = [ws.qualify(p) for p in a.include]
        changed.append("include")
    if add:
        inc = d.setdefault("sources", {}).setdefault("include", [])
        inc.extend(g for g in dict.fromkeys(ws.qualify(p) for p in add) if g not in inc)
        changed.append("include")
    if a.depends is not None:
        deps = []
        for item in a.depends:
            k, v = parse_kv(item, "--depends")
            if k not in ws.contexts():
                raise BwError(f"depends_on '{k}' does not exist")
            deps.append({"id": k, "reason": v})
        d["depends_on"] = deps
        changed.append("depends_on")
    if a.related is not None:
        for r in a.related:
            if r not in ws.contexts():
                raise BwError(f"related '{r}' does not exist")
        d["related"] = sorted(set(a.related))
        changed.append("related")
    if a.anchor:
        anchors = []
        for item in a.anchor:
            loc, sep, when = item.partition("=")
            if not sep:
                raise BwError("--anchor must look like 'app:src/x.ts#symbol=when to look here'")
            path, _, symbol = loc.partition("#")
            entry = {"path": ws.qualify(path.strip()), "when": when.strip()}
            if symbol.strip():
                entry["symbol"] = symbol.strip()
            anchors.append(entry)
        d["anchors"] = anchors
        changed.append("anchors")
    if a.doc:
        docs = d.setdefault("docs", {})
        for item in a.doc:
            k, v = parse_kv(item, "--doc")
            if not (c.folder / v).is_file():
                raise BwError(f"--doc {k}: {v} is not a file in {c.display}")
            docs[k] = v
        changed.append("docs")
    if not changed:
        raise BwError("nothing to set; see bw ctx set --help")
    c.save()
    out(f"{cid}: set {', '.join(changed)}")


def cmd_refresh(ws, cid):
    c = ws.ctx(cid)
    snap = Snapshot(ws)
    files = snap.match(c.includes)
    if not files:
        raise BwError(f"{cid}: sources.include matches no files: {c.includes}")
    src = c.data.setdefault("sources", {})
    before = json.dumps([src.get("hashes"), src.get("git"), c.data.get("upstream_seen")], sort_keys=True)
    src["hashes"] = snap.hashes(files)
    src["git"] = {rid: h for rid, p in ws.repos if (h := git_head(p))}
    seen = {}
    for dep in c.data.get("depends_on") or []:
        up = ws.contexts().get(dep.get("id"))
        if up:
            seen[up.id] = up.version
    c.data["upstream_seen"] = seen
    if before == json.dumps([src["hashes"], src["git"], seen], sort_keys=True):
        out(f"{cid}: already current ({len(files)} files); nothing changed")
        return
    c.save()
    out(f"{cid}: refreshed {len(files)} source hashes" + (f", upstream {seen}" if seen else ""))


def cmd_stale(ws, target, diff=False):
    snap = Snapshot(ws)
    ids = dep_order(ws, [k for k in ws.contexts() if not k.startswith("!")]) if target in (None, "--all", "all") else [target]
    if not ids:
        out("no contexts yet")
        return 0
    any_stale = False
    for cid in ids:
        c = ws.ctx(cid)
        info = stale_info(ws, c, snap)
        any_stale |= is_stale(info)
        for ln in stale_lines(ws, c, info, diff=diff and len(ids) == 1):
            out(ln)
    return 1 if any_stale else 0


def dependents(ws, cid):
    res = []
    for oid, o in ws.contexts().items():
        if oid.startswith("!"):
            continue
        if o.data.get("parent") == cid:
            res.append((oid, "child"))
        for dep in o.data.get("depends_on") or []:
            if dep.get("id") == cid:
                res.append((oid, "depends_on: " + short(dep.get("reason", ""), 60)))
        if cid in (o.data.get("related") or []):
            res.append((oid, "related"))
    return res


def tasks_using(ws, cid):
    from .util import read_json
    res = []
    for tid in ws.task_ids():
        t = read_json(ws.tasks_dir / tid / "task.json")
        pins = [p for p in t.get("consumes", []) if p.get("id") == cid]
        if pins:
            res.append((tid, t.get("status"), f"consumes v{pins[0].get('version')}"))
        elif cid in t.get("affects", []):
            res.append((tid, t.get("status"), "affects"))
    return res


def cmd_tree(ws, root_id=None):
    ctxs = {k: v for k, v in ws.contexts().items() if not k.startswith("!")}
    bad = [k for k in ws.contexts() if k.startswith("!")]
    if not ctxs:
        out("no contexts yet. Create one: /bookworm:learn <feature>")
        return
    snap = Snapshot(ws)
    unpublished = set(gitk.changes(ws))
    kids = {}
    for cid, c in ctxs.items():
        kids.setdefault(c.data.get("parent") if c.data.get("parent") in ctxs else None, []).append(cid)

    def line(cid, depth):
        c = ctxs[cid]
        flag = label(stale_info(ws, c, snap)).lower()
        if any(p.startswith(f"context/{c.rel_folder}/") for p in unpublished):
            flag += ", unpublished"
        deps = [d.get("id") for d in c.data.get("depends_on") or []]
        extra = f"  → {', '.join(deps)}" if deps else ""
        out(f"{'  ' * depth}- {cid} v{c.version} [{flag}] {c.data.get('title', '')} "
            f"(.bookworm/context/{c.rel_folder}/{c.router()}){extra}")
        for k in sorted(kids.get(cid, [])):
            line(k, depth + 1)

    roots = [root_id] if root_id else sorted(kids.get(None, []))
    if root_id:
        ws.ctx(root_id)
    out(f"Contexts ({len(ctxs)}):" if not root_id else f"Context tree from {root_id}:")
    for r in roots:
        line(r, 0)
    for b in bad:
        out(f"! {b}")


def cmd_show(ws, cid):
    c = ws.ctx(cid)
    d = c.data
    snap = Snapshot(ws)
    info = stale_info(ws, c, snap)
    out(f"{cid} v{c.version} \"{d.get('title')}\" ({d.get('type')}) — {label(info)}")
    out(f"read first: .bookworm/context/{c.rel_folder}/{c.router()}")
    out("docs: " + ", ".join(f"{k}={v}" for k, v in (d.get("docs") or {}).items()))
    src = d.get("sources") or {}
    out(f"sources: {', '.join(src.get('include', [])) or '(none)'} — {len(src.get('hashes') or {})} files"
        + (f", refreshed at {', '.join(f'{k}@{v}' for k, v in (src.get('git') or {}).items())}" if src.get("git") else ""))
    for a in d.get("anchors") or []:
        out(f"anchor: {a.get('path')}{'#' + a['symbol'] if a.get('symbol') else ''} — {a.get('when')}")
    if d.get("parent"):
        out(f"parent: {d['parent']}")
    for dep in d.get("depends_on") or []:
        out(f"depends_on: {dep.get('id')} — {dep.get('reason')}")
    if d.get("related"):
        out(f"related: {', '.join(d['related'])}")
    for oid, why in dependents(ws, cid):
        out(f"used by: {oid} ({why})")
    for tid, status, why in tasks_using(ws, cid):
        out(f"task: {tid} [{status}] {why}")
    pub = gitk.last_commit(ws, f"context/{c.rel_folder}")
    dirty = [p for p in gitk.changes(ws) if p.startswith(f"context/{c.rel_folder}/")]
    out(f"published: {pub or 'never'}" + (f"; unpublished changes: {len(dirty)} file(s)" if dirty else ""))
    if is_stale(info):
        for ln in stale_lines(ws, c, info)[1:]:
            out(ln)


def cmd_show_many(ws, ids):
    """Several contexts in one call; an unknown id prints an error line and the rest still show."""
    rc = 0
    for i, cid in enumerate(dict.fromkeys(ids)):
        if i:
            out("")
        try:
            cmd_show(ws, cid)
        except BwError as e:
            out(f"error: {e}")
            rc = 1
    return rc


def cmd_del(ws, cid, force=False):
    c = ws.ctx(cid)
    users = tasks_using(ws, cid)
    running = [t for t in users if t[1] == "running"]
    kids = [o for o, why in dependents(ws, cid) if why == "child"]
    if (running or kids) and not force:
        raise BwError(f"refusing to delete {cid}: "
                      + "; ".join([f"running task {t[0]} uses it" for t in running] + [f"child context {k}" for k in kids])
                      + ". Use --force to delete anyway.", 1)
    shutil.rmtree(c.folder)
    marker = f"context/{c.rel_folder}/"
    ov = ws.bw / "context.md"
    removed = 0
    if ov.exists():
        lines = ov.read_text(encoding="utf-8").splitlines(keepends=True)
        keep = [ln for ln in lines if marker not in ln]
        removed = len(lines) - len(keep)
        if removed:
            ov.write_text("".join(keep), encoding="utf-8", newline="\n")
    out(f"deleted context {cid} ({c.display}); removed {removed} overview route line(s)")
    ws.contexts(refresh=True)
    for oid, why in dependents(ws, cid):
        out(f"  now broken: {oid} ({why}) — fix its manifest")
    for tid, status, why in users:
        out(f"  task {tid} [{status}] {why} → readiness now blocked")
    out(f"history stays in knowledge git (git -C {ws.rel(gitk.root(ws)) or '.'} log -- {gitk.prefix(ws)}{marker})")
    out("next: bw publish -m \"delete " + cid + "\"")


def word(s):
    return re.compile(rf"(?<![\w-]){re.escape(s)}(?![\w-])")


def cmd_rename(ws, old, new):
    """Rename a context id everywhere it is a link; commits without a version bump (pins stay valid)."""
    from . import learn
    c = ws.ctx(old)
    validate_id(new, "new id")
    if new == old:
        raise BwError(f"{old} already has that id")
    if new in ws.contexts():
        raise BwError(f"context id '{new}' already exists at {ws.contexts()[new].display}")
    running = [t for t, status, _ in tasks_using(ws, old) if status == "running"]
    if running:
        raise BwError(f"refusing to rename {old}: running task {running[0]} uses it. "
                      f"Finish the run first (bw run finish {running[0]}).", 1)
    if learn.active_run(ws):
        raise BwError(f"refusing to rename {old}: learn-all run {learn.active_run(ws)} is in progress. "
                      "Finish it first: /bookworm:learn-all --resume", 1)
    if gitk.changes(ws):
        raise BwError(f"refusing to rename {old}: knowledge has unpublished changes. "
                      "Publish them first: bw publish -m \"…\"", 1)
    dest = c.folder.with_name(new) if c.folder.name == old else c.folder
    if dest != c.folder and dest.exists():
        raise BwError(f"refusing to rename {old}: {ws.rel(dest)} already exists", 1)
    old_rel, new_rel = c.rel_folder, dest.relative_to(ws.ctx_dir).as_posix()

    # own manifest, doc files, folder
    docs = c.data.get("docs") or {}
    for f in sorted(c.folder.iterdir()):
        if f.is_file() and f.name.startswith(old + "-"):
            name = new + f.name[len(old):]
            f.rename(f.with_name(name))
            docs = {k: (name if v == f.name else v) for k, v in docs.items()}
    c.data["docs"] = docs
    c.data["id"] = new
    c.save()
    if dest != c.folder:
        c.folder.rename(dest)

    # links in other manifests
    links = 0
    for oid, o in ws.contexts().items():
        if oid.startswith("!") or oid == old:
            continue
        d = o.data
        before = json.dumps(d, sort_keys=True)
        if d.get("parent") == old:
            d["parent"] = new
        for dep in d.get("depends_on") or []:
            if isinstance(dep, dict) and dep.get("id") == old:
                dep["id"] = new
        if old in (d.get("related") or []):
            d["related"] = sorted(new if r == old else r for r in d["related"])
        if old in (d.get("upstream_seen") or {}):
            d["upstream_seen"] = {(new if k == old else k): v for k, v in d["upstream_seen"].items()}
        if json.dumps(d, sort_keys=True) != before:
            o.save()
            links += 1

    # task pins (history/ and _deleted/ are records of the past: left alone)
    tasks = []
    for tid in ws.task_ids():
        d, t = ws.load_task(tid)
        pins = t.get("consumes") or []
        if not any(p.get("id") == old for p in pins) and old not in (t.get("affects") or []):
            continue
        for p in pins:
            if p.get("id") == old:
                p["id"] = new
        t["affects"] = sorted(new if x == old else x for x in t.get("affects") or [])
        ws.save_task(d, t)
        tasks.append((d, t))

    # doc links: folder paths, router/verification filenames (and their relative ../<old>/ folder), `id` in
    # backticks; overview route lines also get the bare id
    path_re = re.compile(rf"(?<![\w-])context/{re.escape(old_rel)}/")
    file_res = [(word(f"{old}-{kind}.md"), f"{new}-{kind}.md") for kind in ("context", "verification")]
    if dest != c.folder:
        file_res.append((re.compile(rf"(?<![\w-]){re.escape(old)}/(?={re.escape(new)}-)"), f"{new}/"))
    file_res.append((re.compile(rf"`{re.escape(old)}`"), f"`{new}`"))
    file_res.append((re.compile(rf"\[{re.escape(old)}\](?=\([^)]*(?<![\w-]){re.escape(new)}-context\.md)"), f"[{new}]"))
    old_word = word(old)
    overview = ws.bw / "context.md"
    files = ([overview] if overview.exists() else []) + sorted(ws.ctx_dir.rglob("*.md"))
    edited, mentions = 0, []
    for path in files:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        for i, ln in enumerate(lines):
            if path == overview and path_re.search(ln):
                ln = old_word.sub(new, path_re.sub(f"context/{new_rel}/", ln))
            ln = path_re.sub(f"context/{new_rel}/", ln)
            for rx, repl in file_res:
                ln = rx.sub(repl, ln)
            lines[i] = ln
            if old_word.search(ln):
                mentions.append(f"{ws.rel(path)}:{i + 1}")
        if "".join(lines) != text:
            path.write_text("".join(lines), encoding="utf-8", newline="\n")
            edited += 1

    findings = ws.cache / "findings"
    if (findings / f"{old}.md").exists() and not (findings / f"{new}.md").exists():
        (findings / f"{old}.md").rename(findings / f"{new}.md")

    ws.contexts(refresh=True)
    out(f"renamed {old} → {new} (.bookworm/context/{new_rel}/); updated {links} manifest(s), "
        f"{len(tasks)} task(s), {edited} doc(s)")
    errs, _ = validate_all(ws)
    if errs:
        for e in errs:
            out(f"error: {e}")
        out("not committed: fix these (bw check), then bw publish -m \"rename " + old + " to " + new + "\"")
        return 1
    commit = commit_knowledge(ws, f"rename {old} to {new}")
    if commit:
        out(f"published {commit}: rename {old} to {new} (versions unchanged)")
        # current pins move to the rename commit, so later re-pin diffs of the new folder stay meaningful
        version = ws.ctx(new).version
        for d, t in tasks:
            for p in t.get("consumes") or []:
                if p.get("id") == new and int(p.get("version", 0)) == version:
                    p["commit"] = commit
            ws.save_task(d, t)
    for m in mentions[:10]:
        out(f"mention: {m}")
    if mentions:
        out(f"next: {len(mentions)} prose mention(s) of '{old}' left; review them (/bookworm:context-update {new})")
    return 0


def commit_knowledge(ws, message, folders=None):
    """Commit knowledge per policy. Returns the short hash; None if nothing changed or policy is manual."""
    if ws.policy == "manual":
        specs = " ".join(gitk.pathspecs(ws, folders))
        out("policy manual: knowledge is ready but not committed. Run:")
        out(f"  git -C \"{gitk.root(ws)}\" add -A -- {specs} && git -C \"{gitk.root(ws)}\" commit -m \"{message}\" -- {specs}")
        out("until then, run finish reports 'unpublished knowledge'.")
        return None
    return gitk.commit(ws, message, folders)


def semantic(manifest):
    m = {k: v for k, v in (manifest or {}).items() if k not in VOLATILE_KEYS}
    if "sources" in m:
        m["sources"] = {k: v for k, v in m["sources"].items() if k not in VOLATILE_SOURCE_KEYS}
    return json.dumps(m, sort_keys=True)


def cmd_publish(ws, message, ids=None, learn_all=None):
    from . import learn
    active = learn.active_run(ws)
    if active and active != learn_all:
        raise BwError(f"learn-all run {active} is in progress; it publishes everything at its end. "
                      f"Wait for it, or finish it with /bookworm:learn-all --resume.", 1)
    if learn_all:
        published = read_json(learn.la_dir(ws, learn_all) / "jobs.json", {}).get("published")
        if published:
            raise BwError(f"{learn_all} was already published ({published['commit']}); start a new run for gaps or stale contexts", 1)
    errs, warns = validate_all(ws)
    if errs:
        raise BwError("publish refused, fix these first:\n  " + "\n  ".join(errs), 1)
    for w in warns:
        out(f"warning: {w}")
    folders = None
    if ids:
        folders = [ws.ctx(i).rel_folder for i in ids]
    changed = gitk.changes(ws, folders)
    if not changed:
        out("nothing to publish: knowledge matches the last commit")
        return 0
    bumped, new, touched = [], [], []
    for cid, c in ws.contexts().items():
        if cid.startswith("!") or (folders is not None and c.rel_folder not in folders):
            continue
        pre = f"context/{c.rel_folder}/"
        files = [p for p in changed if p.startswith(pre)]
        if not files:
            continue
        touched.append(cid)
        head_text = gitk.show(ws, pre + "context.json")
        if head_text is None:
            new.append(cid)
            continue
        head_m = json.loads(head_text)
        # verification notes are provenance, not claims: committed, but no version bump (pins stay current)
        docs_changed = any(p != pre + "context.json" and not p.endswith("-verification.md") for p in files)
        if (docs_changed or semantic(head_m) != semantic(c.data)) and c.version <= int(head_m.get("version", 1)):
            c.data["version"] = int(head_m.get("version", 1)) + 1
            c.save()
            bumped.append(f"{cid} v{c.version}")
    commit = commit_knowledge(ws, message, folders)
    if ws.policy == "manual":
        return 0
    for cid in touched:
        f = ws.cache / "findings" / f"{cid}.md"
        if f.exists():
            f.unlink()
    out(f"published {commit}: {message}")
    if new:
        out(f"  new: {', '.join(new)}")
    if bumped:
        out(f"  version bumped: {', '.join(bumped)}")
    if learn_all:
        learn.after_publish(ws, learn_all, commit)
    return 0
