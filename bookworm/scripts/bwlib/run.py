"""Runs: baseline, acceptance checks, effects, maintenance and the completion gate."""

from __future__ import annotations

import re
import subprocess
from collections import Counter

from . import ctx as ctxmod
from . import gitk
from .snapshot import Snapshot, diff_hashes, fingerprint, git_head, run_git
from .task import readiness, repin_behind, repin_on_start
from .util import BwError, now, out, read_json, short, write_json

FAIL_LINE = re.compile(r"\berror\b|\bfail(ed|ure)?\b|✖|✗|\bFAIL\b", re.I)
SUMMARY_LINE = re.compile(r"\d+\s+(problems?|errors?|warnings?|failed|passed|tests?)\b.*\d", re.I)
LOCATION = re.compile(r"\b\d+:\d+\b|:\d+\b|\(\d+,\d+\)|\bline \d+\b", re.I)
PATHLIKE = re.compile(r"^(?:[A-Za-z]:)?[\\/]?[\w.@~ ()-]+(?:[\\/][\w.@~ ()-]+)+\.\w+\s*$")
CHECK_TIMEOUT = 1800


def failure_set(output):
    """Normalized failure lines: file header + message, without line:col, so edits elsewhere don't count."""
    keys, current = [], ""
    for raw in output.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if PATHLIKE.match(line.strip()) and not raw.startswith((" ", "\t")):
            current = "/".join(line.strip().replace("\\", "/").split("/")[-3:])
            continue
        if FAIL_LINE.search(line) and not SUMMARY_LINE.search(line):
            norm = " ".join(LOCATION.sub("#", line).split())
            keys.append(f"{current} | {norm}" if current else norm)
    return keys


def exec_check(ws, cmd):
    cwd = ws.repo_path(ws.default_repo)
    try:
        p = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=CHECK_TIMEOUT)
        output, code = (p.stdout or "") + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired:
        output, code = f"timed out after {CHECK_TIMEOUT}s", 124
    return code, output


def tail(text, n=25):
    lines = text.rstrip().splitlines()
    return lines[-n:]


def cmd_start(ws, tid, override=None, baseline_checks=True):
    d, t = ws.load_task(tid)
    if t.get("run"):
        rp = ws.run_path(t["run"])
        if rp.is_file():
            r = read_json(rp)
            if r["revision"] == t["revision"] and r.get("result") not in ("done", "superseded"):
                t["status"] = "running"
                ws.save_task(d, t)
                r["resumed_at"] = now()
                r["result"] = None
                write_json(rp, r)
                out(f"resumed run {r['id']} (revision {r['revision']}); baseline from {r['started_at']} is kept")
                return 0
    # one run at a time: baselines and the source-git block assume a single running task
    for other in ws.task_ids():
        if other != t["id"] and read_json(ws.tasks_dir / other / "task.json").get("status") == "running":
            raise BwError(f"{other} is running; not starting {t['id']}. Finish or resume it first: "
                          f"/bookworm:run {other} (or revise it: /bookworm:todo-update {other})", 1)
    repinned = repin_behind(ws, d, t) if repin_on_start(t) else []
    for r in repinned:
        out(f"re-pinned {r['id']} v{r['from']}→v{r['to']}; check the doc changes against the plan: {r['diff']}")
    level, reasons = readiness(ws, t)
    if level != "ready" and not override:
        out(f"{t['id']} is {level}; not starting:")
        for why in reasons:
            out(f"  - {why}")
        out("fix those, or if the user explicitly accepts the risk: bw run start "
            f"{t['id']} --override \"<user's reason>\"")
        return 1
    if t["status"] == "done":
        raise BwError(f"{t['id']} is already done; use /bookworm:todo-update {t['id']} to revise it", 1)
    n = 1 + sum(1 for p in ws.runs_dir.glob(f"{t['id']}-r{t['revision']}-*")) if ws.runs_dir.is_dir() else 1
    rid = f"{t['id']}-r{t['revision']}-{n}"
    snap = Snapshot(ws)
    base = snap.full()
    run = {"id": rid, "task": t["id"], "revision": t["revision"], "started_at": now(),
           "override": override, "readiness_at_start": level, "repinned": repinned,
           "git": {r: {"head": git_head(p), "dirty": bool((run_git(p, "status", "--porcelain").stdout or "").strip())}
                   for r, p in ws.repos},
           "baseline": base, "baseline_checks": {}, "checks": {}, "maintenance": {"contexts": {}, "files": {}},
           "effects": None, "result": None, "reasons": []}
    if baseline_checks:
        for c in t.get("acceptance", []):
            code, output = exec_check(ws, c["cmd"])
            run["baseline_checks"][c["name"]] = {"exit": code, "failures": failure_set(output), "tail": tail(output, 8)}
    write_json(ws.run_path(rid), run)
    t["run"] = rid
    t["status"] = "running"
    ws.save_task(d, t)
    out(f"started run {rid}: baseline of {len(base)} files" + (f" (override: {override})" if override else ""))
    for name, b in run["baseline_checks"].items():
        out(f"  baseline {name}: exit {b['exit']}" + (f", {len(b['failures'])} failure lines already present" if b["exit"] else ""))
    return 0


def cmd_check(ws, ref, names):
    rp, run = ws.load_run(ref)
    _, t = ws.load_task(run["task"])
    checks = {c["name"]: c for c in t.get("acceptance", [])}
    if not checks:
        raise BwError(f"{t['id']} has no acceptance checks (bw task set {t['id']} --check NAME MODE CMD)")
    todo = list(checks) if not names or names == ["all"] else names
    worst = 0
    for name in todo:
        if name not in checks:
            raise BwError(f"no check '{name}' (have: {', '.join(checks)})")
        c = checks[name]
        snap = Snapshot(ws)
        fp = fingerprint(snap.full())
        code, output = exec_check(ws, c["cmd"])
        rec = {"cmd": c["cmd"], "mode": c["mode"], "exit": code, "at": now(), "fingerprint": fp,
               "tail": tail(output)}
        if c["mode"] == "pass":
            ok = code == 0
            why = "exit 0" if ok else f"exit {code}"
            base = run.get("baseline_checks", {}).get(name)
            if not ok and base and base["exit"] != 0:
                why += f"; it also failed at baseline (exit {base['exit']}) — pre-existing failures"
        else:
            base = run.get("baseline_checks", {}).get(name)
            failures = failure_set(output)
            rec["failures"] = failures
            if code == 0:
                ok, why = True, "exit 0"
            elif base is None:
                ok, why = False, "no baseline result recorded (run start captures it)"
            else:
                new = Counter(failures) - Counter(base["failures"])
                rec["new_failures"] = sorted(new.elements())
                ok = not new and not (base["exit"] == 0)
                why = (f"exit {code}, same {len(failures)} failure lines as baseline (no new failures)" if ok
                       else f"exit {code}, {sum(new.values())} new failure line(s)" if new
                       else f"exit {code} but baseline passed")
        rec["ok"] = ok
        rec["why"] = why
        run["checks"][name] = rec
        write_json(rp, run)
        out(f"check {name} ({c['mode']}): {'PASS' if ok else 'FAIL'} — {why}")
        if not ok:
            for ln in rec.get("new_failures", [])[:15] or rec["tail"][-12:]:
                out(f"    {ln}")
            worst = 1
    return worst


def compute_effects(ws, run, snap):
    added, modified, deleted = diff_hashes(run["baseline"], snap.full())
    ctxs = {k: c for k, c in ws.contexts().items() if not k.startswith("!")}
    owners = {}
    for cid, c in ctxs.items():
        for q in snap.match(c.includes):
            owners.setdefault(q, []).append(cid)
        for q in (c.data.get("sources") or {}).get("hashes", {}):
            if q in deleted:
                owners.setdefault(q, []).append(cid)
    rows = []
    for kind, paths in (("added", added), ("modified", modified), ("deleted", deleted)):
        for q in paths:
            rows.append({"path": q, "change": kind, "before": run["baseline"].get(q),
                         "after": snap.hash(q) if kind != "deleted" else None,
                         "contexts": sorted(set(owners.get(q, [])))})
    return rows


def cmd_effects(ws, ref):
    _, run = ws.load_run(ref)
    rows = compute_effects(ws, run, Snapshot(ws))
    if not rows:
        out(f"{run['id']}: no source changes since baseline")
        return
    out(f"{run['id']}: {len(rows)} changed file(s) since baseline")
    for r in rows:
        excl = run["maintenance"]["files"].get(r["path"])
        owner = ", ".join(r["contexts"]) or (f"excluded: {excl}" if excl else "UNMAPPED")
        out(f"  {r['change']:8} {r['path']} → {owner}")


def cmd_maintain(ws, ref, args):
    rp, run = ws.load_run(ref)
    if args[:1] == ["--file"]:
        if len(args) < 4 or args[2] != "excluded":
            raise BwError('usage: bw run maintain <run> --file <path> excluded "<reason>"')
        path = ws.qualify(args[1])
        run["maintenance"]["files"][path] = " ".join(args[3:])
        write_json(rp, run)
        out(f"{run['id']}: {path} excluded — {run['maintenance']['files'][path]}")
        return
    if len(args) < 2 or args[1] not in ("updated", "no-change"):
        raise BwError('usage: bw run maintain <run> <ctx> updated|no-change "<reason>"')
    cid, action, reason = args[0], args[1], " ".join(args[2:])
    c = ws.ctx(cid)
    if action == "no-change" and not reason:
        raise BwError("no-change needs a reason")
    dirty = [p for p in gitk.changes(ws) if p.startswith(f"context/{c.rel_folder}/")]
    if action == "updated" and dirty:
        raise BwError(f"{cid} has unpublished changes; run bw publish -m \"…\" {cid} first", 1)
    commit = gitk.last_commit(ws, f"context/{c.rel_folder}")
    run["maintenance"]["contexts"][cid] = {"action": action, "reason": reason, "version": c.version,
                                           "commit": commit, "at": now()}
    write_json(rp, run)
    out(f"{run['id']}: {cid} {action} (v{c.version}@{commit})" + (f" — {reason}" if reason else ""))


def gate(ws, run, t, snap):
    reasons = []
    if t.get("status") not in ("running", "needs_attention"):
        reasons.append(f"task status is {t.get('status')}, not running (bw run start {t['id']})")
    if run["revision"] != t["revision"] or run.get("result") == "superseded" or t.get("run") != run["id"]:
        reasons.append(f"run {run['id']} is not the task's current run (task revision {t['revision']})")
    left = [s["id"] for s in t.get("steps", []) if not s.get("done")]
    if left:
        reasons.append(f"steps not done: {', '.join(left)} (bw task step {t['id']} <S#> done)")
    fp = fingerprint(snap.full())
    for c in t.get("acceptance", []):
        rec = run["checks"].get(c["name"])
        if rec is None:
            reasons.append(f"check {c['name']} never ran (bw run check {run['id']} {c['name']})")
        elif rec["fingerprint"] != fp:
            reasons.append(f"check {c['name']} ran before the latest source change; re-run it")
        elif not rec["ok"]:
            reasons.append(f"check {c['name']} ({c['mode']}) failed: {rec['why']}")
    effects = compute_effects(ws, run, snap)
    mapped = set()
    for e in effects:
        if e["contexts"]:
            mapped.update(e["contexts"])
        elif e["path"] not in run["maintenance"]["files"]:
            reasons.append(f"changed file {e['path']} maps to no context: map it (add to a context's "
                           f"sources.include) or bw run maintain {run['id']} --file {e['path']} excluded \"<reason>\"")
    unpublished = gitk.changes(ws)
    for cid in sorted(mapped | set(t.get("affects", []))):
        c = ws.contexts().get(cid)
        m = run["maintenance"]["contexts"].get(cid)
        if c is None:
            reasons.append(f"affected context {cid} no longer exists")
            continue
        if m is None:
            reasons.append(f"context {cid} has no maintenance record "
                           f"(bw run maintain {run['id']} {cid} updated|no-change \"<reason>\")")
        elif m["action"] == "updated" and not gitk.commit_exists(ws, m.get("commit")):
            reasons.append(f"context {cid}: recorded commit {m.get('commit')} does not exist")
        if ctxmod.is_stale(ctxmod.stale_info(ws, c, snap)):
            reasons.append(f"context {cid} is stale against the changed source: update its docs if needed, "
                           f"bw ctx refresh {cid}, bw publish, then record maintenance again")
    if unpublished:
        reasons.append(f"unpublished knowledge changes ({len(unpublished)} file(s)): bw publish -m \"…\"")
    return reasons, effects


def cmd_finish(ws, ref, accept=None):
    rp, run = ws.load_run(ref)
    d, t = ws.load_task(run["task"])
    snap = Snapshot(ws)
    reasons, effects = gate(ws, run, t, snap)
    run["effects"] = effects
    run["finished_at"] = now()
    if reasons and accept:
        run["accepted"] = {"reason": accept, "waived": reasons, "at": now()}
    result = "done" if not reasons or accept else "needs_attention"
    run["result"] = result
    run["reasons"] = reasons
    write_json(rp, run)
    if t.get("run") == run["id"] and run["revision"] == t["revision"]:
        t["status"] = result
        ws.save_task(d, t)
    out(f"{run['id']}: {result.upper()}" + (f" (accepted by user: {accept})" if reasons and accept else ""))
    out(f"  effects: {len(effects)} file(s): " + ", ".join(f"{e['change'][0].upper()} {e['path']}" for e in effects[:12]))
    for name, rec in run["checks"].items():
        out(f"  check {name}: {'pass' if rec['ok'] else 'FAIL'} — {short(rec['why'], 120)}")
    for why in reasons:
        out(f"  - {why}")
    return 0 if result == "done" else 1
