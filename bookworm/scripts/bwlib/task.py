"""Tasks (plans and todos are one entity): create, set, pin, readiness, revise."""

from __future__ import annotations

import json
import shutil

from . import ctx as ctxmod
from . import gitk
from .snapshot import Snapshot
from .util import BwError, now, out, read_json, short, slugify, write_json

STATUSES = ("planned", "todo", "running", "needs_attention", "blocked", "done")
MODES = ("pass", "no-new-failures")


def next_number(ws):
    nums = [0]
    for base in (ws.tasks_dir, ws.tasks_dir / "_deleted"):
        if base.is_dir():
            for p in base.iterdir():
                head = p.name.split("-")[0]
                if head.isdigit():
                    nums.append(int(head))
    return max(nums) + 1


def cmd_new(ws, slug, kind="plan", goal="", a=None):
    if kind not in ("plan", "todo"):
        raise BwError("--kind must be plan or todo")
    tid = f"{next_number(ws)}-{slugify(slug)}"
    d = ws.tasks_dir / tid
    d.mkdir(parents=True)
    task = {"id": tid, "kind": kind, "status": "planned" if kind == "plan" else "todo", "revision": 1,
            "goal": goal, "acceptance": [], "consumes": [], "affects": [], "steps": [], "run": None,
            "created_at": now(), "updated_at": now()}
    write_json(d / "task.json", task)
    out(f"created task {tid} ({kind})")
    plan = getattr(a, "plan", None)
    if plan:
        import sys
        text = sys.stdin.read() if plan == "-" else open(plan, encoding="utf-8").read()
        if text.strip():
            (d / "plan.md").write_text(text.strip() + "\n", encoding="utf-8", newline="\n")
    if a is not None and (a.step or a.check or a.affects):
        a.goal, a.status = None, None
        cmd_set(ws, tid, a)
        if a.affects:
            cmd_pin(ws, tid, [])
    if (d / "plan.md").exists():
        cmd_show(ws, tid)
        return
    out(f"next: write {ws.rel(d / 'plan.md')} (new file)" + (f" and {ws.rel(d / 'handoff.md')}" if kind == "todo" else "")
        + f", then bw task set {tid} --step … --check NAME MODE CMD --affects CTX; bw task pin {tid}")


def cmd_set(ws, tid, a):
    d, t = ws.load_task(tid)
    changed = []
    if a.goal:
        t["goal"] = a.goal
        changed.append("goal")
    if a.step:
        old = {s["title"]: s.get("done", False) for s in t.get("steps", [])}
        t["steps"] = [{"id": f"S{i}", "title": s, "done": old.get(s, False)} for i, s in enumerate(a.step, 1)]
        changed.append("steps")
    if a.check:
        checks = []
        for name, mode, cmd in a.check:
            if mode not in MODES:
                raise BwError(f"check mode must be one of {MODES}, got '{mode}'")
            checks.append({"name": name, "cmd": cmd, "mode": mode})
        t["acceptance"] = checks
        changed.append("acceptance")
    if a.affects is not None:
        for cid in a.affects:
            ws.ctx(cid)
        t["affects"] = sorted(set(a.affects))
        changed.append("affects")
    if a.status:
        if a.status not in STATUSES:
            raise BwError(f"status must be one of {STATUSES}")
        t["status"] = a.status
        changed.append("status")
    if not changed:
        raise BwError("nothing to set; see bw task set --help")
    ws.save_task(d, t)
    out(f"{t['id']}: set {', '.join(changed)}")


def published_version(ws, c):
    text = gitk.show(ws, f"context/{c.rel_folder}/context.json")
    if text is None:
        return None
    return int(json.loads(text).get("version", 1))


def pin_entries(ws, ids, reasons):
    head = gitk.head(ws)
    pins = []
    for cid in ids:
        c = ws.ctx(cid)
        ver = published_version(ws, c)
        if ver is None:
            raise BwError(f"context {cid} was never published; run bw publish first")
        pins.append({"id": cid, "version": ver, "commit": head, "reason": reasons.get(cid, "plan relies on it")})
    return pins


def cmd_pin(ws, tid, ids, reason=None):
    d, t = ws.load_task(tid)
    old = {p["id"]: p for p in t.get("consumes", [])}
    ids = ids or list(dict.fromkeys([*old, *[a for a in t.get("affects", []) if a in ws.contexts()]]))
    if not ids:
        raise BwError("no contexts to pin: pass ids or set --affects first")
    reasons = {k: v.get("reason") for k, v in old.items()}
    if reason:
        reasons.update({i: reason for i in ids})
    pins = pin_entries(ws, ids, reasons)
    keep = [p for p in t.get("consumes", []) if p["id"] not in ids]
    t["consumes"] = keep + pins
    ws.save_task(d, t)
    for p in pins:
        was = old.get(p["id"])
        out(f"pinned {p['id']} v{p['version']}@{p['commit']}" + (f" (was v{was['version']})" if was else ""))


def readiness(ws, t, snap=None):
    """('ready'|'needs_review'|'blocked', [reasons with fixes])."""
    snap = snap or Snapshot(ws)
    level, reasons, advice, stale = "ready", [], [], 0
    pins = {p["id"]: p for p in t.get("consumes", [])}
    for cid in ctxmod.dep_order(ws, pins):  # dependencies first, so updates don't re-stale each other
        pin, c = pins[cid], ws.contexts().get(cid)
        if c is None:
            level = "blocked"
            reasons.append(f"consumed context {cid} no longer exists → /bookworm:todo-update {t['id']} to re-plan")
            continue
        info = ctxmod.stale_info(ws, c, snap)
        if ctxmod.own_stale(info):
            what = ", ".join(f"{k} {len(info[k])}" for k in ("changed", "added", "deleted") if info[k]) or "never refreshed"
            reasons.append(f"context {c.id} is stale ({what}) → /bookworm:context-update {c.id}")
            level = "needs_review" if level == "ready" else level
            stale += 1
        elif info["upstream"]:
            advice.append(f"context {c.id}: dependency changed since it was learned ({'; '.join(info['upstream'])}); "
                          f"review suggested: /bookworm:context-update {c.id}")
        pv = published_version(ws, c) or c.version
        if pv > int(pin.get("version", 0)):
            if repin_on_start(t):
                advice.append(f"context {c.id} is v{pv}, task pinned v{pin['version']} → bw run start re-pins it")
            else:
                reasons.append(f"context {c.id} is v{pv}, task pinned v{pin['version']} → /bookworm:todo-update {t['id']} (re-pins)")
                level = "needs_review" if level == "ready" else level
    if stale > 1:
        reasons.append("or update all stale contexts at once, dependencies first: /bookworm:context-update --all")
    if not t.get("consumes"):
        reasons.append("no knowledge pinned (bw task pin)")
    return level, reasons + advice


def repin_on_start(t):
    """A task with no run for this revision re-pins at run start (no todo-update hop); start prints the doc diffs."""
    return not t.get("run") and t.get("status") in ("planned", "todo")


def repin_behind(ws, d, t):
    """Move pins behind their published version to it. Returns [{id, from, to, diff}] (diff = command to review)."""
    behind = []
    for p in t.get("consumes", []):
        c = ws.contexts().get(p["id"])
        pv = published_version(ws, c) if c else None
        if pv and pv > int(p.get("version", 0)):
            behind.append(p)
    if not behind:
        return []
    new = {p["id"]: p for p in pin_entries(ws, [p["id"] for p in behind],
                                           {p["id"]: p.get("reason") or "plan relies on it" for p in behind})}
    root, pre = ws.rel(gitk.root(ws)) or ".", gitk.prefix(ws)
    res = [{"id": p["id"], "from": p["version"], "to": new[p["id"]]["version"],
            "diff": f"git -C {root} diff {p['commit']}..{new[p['id']]['commit']} -- "
                    f"{pre}context/{ws.ctx(p['id']).rel_folder}"} for p in behind]
    t["consumes"] = [new.get(p["id"], p) for p in t["consumes"]]
    ws.save_task(d, t)
    return res


def task_row(ws, t, snap):
    level = "-" if t["status"] == "done" else readiness(ws, t, snap)[0]
    return f"{t['id']:<32} {t['kind']:<4} {t['status']:<15} {level:<12} r{t['revision']}  {short(t.get('goal', ''), 70)}"


def cmd_list(ws, filt=None):
    snap = Snapshot(ws)
    rows = []
    for tid in ws.task_ids():
        t = read_json(ws.tasks_dir / tid / "task.json")
        hay = f"{tid} {t['kind']} {t['status']} {t.get('goal', '')}".lower()
        if filt and filt.lower() not in hay and not (filt == "open" and t["status"] != "done"):
            continue
        rows.append(task_row(ws, t, snap))
    if not rows:
        out("no tasks" + (f" matching '{filt}'" if filt else "") + ". Create one: /bookworm:plan <request>")
        return
    out(f"{'id':<32} {'kind':<4} {'status':<15} {'readiness':<12} rev  goal")
    for r in rows:
        out(r)


def cmd_show(ws, tid):
    d, t = ws.load_task(tid)
    level, reasons = readiness(ws, t)
    out(f"{t['id']}  kind {t['kind']}  status {t['status']}  revision {t['revision']}  readiness {level}")
    out(f"goal: {t.get('goal') or '(unset)'}")
    for c in t.get("acceptance", []):
        out(f"check {c['name']} ({c['mode']}): {c['cmd']}")
    for p in t.get("consumes", []):
        out(f"consumes {p['id']} v{p['version']}@{p.get('commit')} — {p.get('reason', '')}")
    if t.get("affects"):
        out(f"affects: {', '.join(t['affects'])}")
    for s in t.get("steps", []):
        out(f"step [{'x' if s.get('done') else ' '}] {s['id']} {s['title']}")
    if t.get("run"):
        rp = ws.run_path(t["run"])
        if rp.is_file():
            r = read_json(rp)
            out(f"run {r['id']}: {r.get('result') or 'running'} (revision {r['revision']})")
            for why in r.get("reasons", []):
                out(f"  - {why}")
    files = [f.name for f in d.iterdir() if f.is_file() and f.suffix == ".md"]
    out(f"files: {', '.join(ws.rel(d / f) for f in sorted(files))}")
    if (d / "history").is_dir():
        out(f"history: {', '.join(sorted(p.name for p in (d / 'history').iterdir()))}")
    for why in reasons:
        out(f"readiness: {why}")


def cmd_step(ws, tid, step, state):
    d, t = ws.load_task(tid)
    hit = [s for s in t.get("steps", []) if s["id"].lower() == step.lower() or step == "all"]
    if not hit:
        raise BwError(f"no step {step} in {t['id']} (steps: {', '.join(s['id'] for s in t.get('steps', []))})")
    for s in hit:
        s["done"] = state == "done"
    ws.save_task(d, t)
    left = [s["id"] for s in t["steps"] if not s.get("done")]
    out(f"{t['id']}: {', '.join(s['id'] for s in hit)} → {state}; remaining: {', '.join(left) or 'none'}")


def cmd_revise(ws, tid, repin=True):
    d, t = ws.load_task(tid)
    rev = t["revision"]
    hist = d / "history" / f"r{rev}"
    hist.mkdir(parents=True, exist_ok=True)
    for f in d.iterdir():
        if f.is_file():
            shutil.copy2(f, hist / f.name)
    superseded = None
    if t.get("run"):
        rp = ws.run_path(t["run"])
        if rp.is_file():
            r = read_json(rp)
            if r.get("result") != "done":
                r["result"] = "superseded"
                r["superseded_at"] = now()
                write_json(rp, r)
                superseded = r["id"]
        t["run"] = None
    t["revision"] = rev + 1
    t["status"] = "planned" if t["kind"] == "plan" else "todo"
    changes = []
    if repin and t.get("consumes"):
        old = {p["id"]: p for p in t["consumes"]}
        live = [i for i in old if i in ws.contexts()]
        t["consumes"] = pin_entries(ws, live, {k: v.get("reason") for k, v in old.items()})
        for p in t["consumes"]:
            if p["version"] != old[p["id"]]["version"]:
                changes.append(f"{p['id']} v{old[p['id']]['version']}→v{p['version']}")
        dropped = [i for i in old if i not in ws.contexts()]
        changes += [f"{i} dropped (deleted)" for i in dropped]
    ws.save_task(d, t)
    out(f"{t['id']}: revision {rev} → {rev + 1}; snapshot at {ws.rel(hist)}")
    if superseded:
        out(f"  run {superseded} marked superseded")
    out(f"  re-pinned: {', '.join(changes) or 'no version changes'}")


def cmd_todo(ws, tid):
    d, t = ws.load_task(tid)
    t["kind"] = "todo"
    if t["status"] in ("planned", "running"):
        t["status"] = "todo"
    hp = d / "handoff.md"
    ws.save_task(d, t)
    out(f"{t['id']}: now a todo; write the handoff at {ws.rel(hp)}" + (" (exists: update it)" if hp.exists() else " (new file)"))


def cmd_del(ws, tid, force=False):
    d, t = ws.load_task(tid)
    if t["status"] == "running" and not force:
        raise BwError(f"{t['id']} is running; finish it or pass --force", 1)
    dest = ws.tasks_dir / "_deleted" / t["id"]
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d), str(dest))
    out(f"deleted task {t['id']}; files kept at {ws.rel(dest)}")
