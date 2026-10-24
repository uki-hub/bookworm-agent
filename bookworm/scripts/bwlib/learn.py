"""bw survey (deterministic inventory) and bw learn-all (atlas, waves, cards, coverage)."""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath

from . import ctx as ctxmod
from .snapshot import Snapshot
from .util import BwError, SLUG, dump, now, out, read_json, short, write_json, write_text

CODE_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".py", ".cs", ".go", ".java",
            ".kt", ".rb", ".php", ".rs", ".swift", ".c", ".h", ".cc", ".cpp", ".hpp", ".m", ".scala", ".sql",
            ".sh", ".ps1", ".css", ".scss", ".less", ".html", ".razor", ".cshtml", ".dart", ".ex", ".exs"}
SCRIPT_EXT = CODE_EXT - {".css", ".scss", ".less", ".html", ".sql"}
ENTRY_NAMES = re.compile(r"(^|/)(main|index|app|App|server|program|Program|__main__|manage|router|routes)\.[\w]+$")
DOC_NAMES = re.compile(r"(^|/)(README|CONTRIBUTING|ARCHITECTURE|DEPLOYMENT|CHANGELOG|DESIGN)[^/]*\.(md|rst|txt)$|(^|/)(adr|docs/decisions)/", re.I)
GENERATED = re.compile(r"(\.min\.\w+$|\.generated\.|\.g\.cs$|\.pb\.go$|(^|/)(generated|__generated__|gen)/|-lock\.json$|\.lock$|\.lockb$)")
JS_IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*|^\s*import\s+)['"]([^'"]+)['"]""", re.M)
PY_IMPORT = re.compile(r"^\s*(?:from\s+(\.*[\w.]*)\s+import|import\s+([\w.]+))", re.M)
GO_IMPORT = re.compile(r'^\s*(?:import\s+)?(?:\w+\s+)?"([\w./-]+)"\s*$', re.M)
CS_USING = re.compile(r"^\s*using\s+(?:static\s+)?([\w.]+)\s*;", re.M)
CS_NS = re.compile(r"^\s*namespace\s+([\w.]+)", re.M)
JS_EXT = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", "/index.ts", "/index.tsx", "/index.js", "/index.jsx"]
DEPTH_COST = {"deep": 350_000, "light": 100_000, "skip": 0}
CARD_KEYS = ("job", "context_id", "status", "summary", "routes", "interactions", "unknowns", "not_covered")
MAX_PARALLEL = 4


def max_parallel():
    """Worker cap: BOOKWORM_MAX_PARALLEL (1..MAX_PARALLEL) for low-memory machines, else MAX_PARALLEL."""
    try:
        n = int(os.environ.get("BOOKWORM_MAX_PARALLEL", ""))
    except ValueError:
        return MAX_PARALLEL
    return max(1, min(n, MAX_PARALLEL))


# ---- survey ----------------------------------------------------------------
def strip_jsonc(text):
    res, i, n, in_str = [], 0, len(text), False
    while i < n:
        ch = text[i]
        if in_str:
            res.append(ch)
            if ch == "\\" and i + 1 < n:
                res.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
            res.append(ch)
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        else:
            res.append(ch)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(res))


def ts_aliases(root):
    aliases = []
    for name in ("tsconfig.json", "tsconfig.app.json", "jsconfig.json", "tsconfig.base.json"):
        p = root / name
        if not p.is_file():
            continue
        try:
            co = json.loads(strip_jsonc(p.read_text(encoding="utf-8"))).get("compilerOptions") or {}
        except (ValueError, OSError):
            continue
        base = (co.get("baseUrl") or ".").strip("./")
        for key, targets in (co.get("paths") or {}).items():
            if targets:
                tgt = str(PurePosixPath(base, targets[0].lstrip("./"))) if base else targets[0].lstrip("./")
                aliases.append((key.rstrip("*"), tgt.rstrip("*")))
    return sorted(set(aliases), key=lambda a: -len(a[0]))


def resolve_js(spec, src_dir, files, aliases):
    if spec.startswith("."):
        base = os.path.normpath(os.path.join(src_dir, spec)).replace("\\", "/")
    else:
        base = None
        for prefix, target in aliases:
            if prefix and spec.startswith(prefix):
                base = os.path.normpath(target + spec[len(prefix):]).replace("\\", "/")
                break
        if base is None:
            return None
    for ext in JS_EXT:
        if base + ext in files:
            return base + ext
    return None


def survey_data(ws):
    snap = Snapshot(ws)
    data = {"repos": [], "generated_at": now()}
    for rid, root in ws.repos:
        files = snap.list_repo(rid)
        fileset = set(files)
        aliases = ts_aliases(root)
        dirs = defaultdict(lambda: {"files": 0, "lines": 0, "code_files": 0, "ext": Counter()})
        langs = Counter()
        lines_of = {}
        edges = Counter()
        file_edges = defaultdict(set)
        externals = Counter()
        cs_ns = {}
        large, generated, entries, docs = [], [], [], []
        for rel in files:
            p = root / rel
            d = str(PurePosixPath(rel).parent)
            d = "." if d in ("", ".") else d
            ext = PurePosixPath(rel).suffix.lower()
            try:
                raw = p.read_bytes()
            except OSError:
                continue
            binary = b"\0" in raw[:8192]
            n = 0 if binary else raw.count(b"\n") + (0 if raw.endswith(b"\n") or not raw else 1)
            lines_of[rel] = n
            info = dirs[d]
            info["files"] += 1
            info["lines"] += n
            info["ext"][ext or PurePosixPath(rel).name] += 1
            if ext in CODE_EXT:
                info["code_files"] += 1
                langs[ext] += n
            if GENERATED.search(rel):
                generated.append(rel)
            elif ext in CODE_EXT and n > 800:
                large.append(f"{rel} ({n} lines)")
            if ENTRY_NAMES.search(rel) and ext in SCRIPT_EXT and rel.count("/") <= 2:
                entries.append(rel)
            if DOC_NAMES.search(rel):
                docs.append(rel)
            if binary or ext not in CODE_EXT:
                continue
            text = raw.decode("utf-8", "replace")
            if ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte"):
                for m in JS_IMPORT.finditer(text):
                    spec = m.group(1)
                    tgt = resolve_js(spec, str(PurePosixPath(rel).parent), fileset, aliases)
                    if tgt:
                        file_edges[rel].add(tgt)
                        td = str(PurePosixPath(tgt).parent)
                        if td != d:
                            edges[(d, "." if td in ("", ".") else td)] += 1
                    elif not spec.startswith("."):
                        pkg = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
                        externals[pkg] += 1
            elif ext == ".py":
                for m in PY_IMPORT.finditer(text):
                    mod = m.group(1) or m.group(2)
                    if mod.startswith("."):
                        dots = len(mod) - len(mod.lstrip("."))
                        base = PurePosixPath(rel).parents[dots - 1] if dots - 1 < len(PurePosixPath(rel).parents) else PurePosixPath(".")
                        cand = str(base / mod.lstrip(".").replace(".", "/"))
                    else:
                        cand = mod.replace(".", "/")
                    for c in (cand + ".py", cand + "/__init__.py", "src/" + cand + ".py", "src/" + cand + "/__init__.py"):
                        if c in fileset:
                            file_edges[rel].add(c)
                            td = str(PurePosixPath(c).parent)
                            if td != d:
                                edges[(d, td)] += 1
                            break
                    else:
                        if not mod.startswith("."):
                            externals[mod.split(".")[0]] += 1
            elif ext == ".cs":
                for m in CS_NS.finditer(text):
                    cs_ns.setdefault(m.group(1), set()).add(d)
            elif ext == ".go":
                for m in GO_IMPORT.finditer(text):
                    externals[m.group(1)] += 1
        for rel in files:
            if rel.endswith(".cs"):
                d = str(PurePosixPath(rel).parent)
                try:
                    text = (root / rel).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for m in CS_USING.finditer(text):
                    for td in cs_ns.get(m.group(1), ()):
                        if td != d:
                            edges[(d, td)] += 1
        pkg = root / "package.json"
        scripts = {}
        if pkg.is_file():
            try:
                pj = json.loads(pkg.read_text(encoding="utf-8"))
                scripts = pj.get("scripts") or {}
                if pj.get("main"):
                    entries.append(f"package.json main: {pj['main']}")
            except ValueError:
                pass
        if "index.html" in fileset and "index.html" not in entries:
            entries.insert(0, "index.html")
        out_edges = defaultdict(dict)
        for (a, b), cnt in edges.items():
            out_edges[a][b] = cnt
        fwave = layer(list(lines_of), file_edges)
        waves = {}
        for f, w in fwave.items():
            d = str(PurePosixPath(f).parent)
            d = "." if d in ("", ".") else d
            waves[d] = min(waves.get(d, w), w)
        data["repos"].append({
            "id": rid, "files": len(files), "lines": sum(lines_of.values()),
            "languages": {k: v for k, v in langs.most_common()},
            "dirs": {d: {"files": i["files"], "code_files": i["code_files"], "lines": i["lines"],
                         "ext": dict(i["ext"].most_common(3)), "wave_hint": waves.get(d, 1),
                         "imports": out_edges.get(d, {}),
                         "imported_by": sorted({a for (a, b) in edges if b == d})}
                     for d, i in sorted(dirs.items())},
            "entry_points": entries, "scripts": scripts, "docs": docs,
            "generated": generated, "large_files": large,
            "externals": dict(externals.most_common(15)), "aliases": aliases, "readme": readme_excerpt(root)})
    snap_ctx = existing_contexts(ws, snap)
    data["contexts"] = snap_ctx
    data["uncovered"] = uncovered_dirs(ws, snap)
    return data


def readme_excerpt(root, max_lines=20, max_chars=1500):
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = root / name
        if p.is_file():
            lines, total = [], 0
            text = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8", errors="replace"), flags=re.S)
            for ln in text.splitlines():
                ln = re.sub(r"<[^>]*>", "", ln).rstrip()
                if (not ln.strip() or ln.lstrip().startswith(("![", "[![")) or "<" in ln or ">" in ln
                        or re.match(r'^\s*[\w-]+="[^"]*"', ln)):
                    continue
                total += len(ln)
                if len(lines) >= max_lines or total > max_chars:
                    lines.append("…")
                    break
                lines.append(ln)
            return lines
    return []


def layer(dirs, out_edges):
    """Wave hint per node: 1 + longest chain of things it imports (cycles cut). Foundations get 1."""
    memo, active = {}, set()

    def depth(d):
        if d in memo:
            return memo[d]
        if d in active:
            return 0
        active.add(d)
        deps = [t for t in out_edges.get(d, {}) if t in out_edges or t in dirs]
        v = 1 + max((depth(t) for t in deps), default=0)
        active.discard(d)
        memo[d] = v
        return v

    return {d: depth(d) for d in dirs}


def existing_contexts(ws, snap):
    res = {}
    for cid, c in ws.contexts().items():
        if cid.startswith("!"):
            continue
        info = ctxmod.stale_info(ws, c, snap)
        res[cid] = {"folder": c.rel_folder, "version": c.version, "stale": ctxmod.is_stale(info),
                    "files": len(snap.match(c.includes))}
    return res


def coverage_files(ws, snap):
    return [q for q in snap.all_files() if PurePosixPath(q.split(":", 1)[1]).suffix.lower() in CODE_EXT]


def covered_set(ws, snap):
    cov = set()
    for cid, c in ws.contexts().items():
        if not cid.startswith("!"):
            cov.update(snap.match(c.includes))
    return cov


def uncovered_dirs(ws, snap):
    cov = covered_set(ws, snap)
    if not cov:
        return {}
    res = Counter()
    multi = len(ws.repos) > 1
    for q in coverage_files(ws, snap):
        if q not in cov:
            rid, rel = q.split(":", 1)
            d = str(PurePosixPath(rel).parent)
            res[(f"{rid}:" if multi else "") + d] += 1
    return dict(sorted(res.items()))


def cmd_survey(ws, as_json=False):
    data = survey_data(ws)
    if as_json:
        dump(data)
        return
    for r in data["repos"]:
        langs = ", ".join(f"{k} {v}" for k, v in list(r["languages"].items())[:6])
        out(f"repo {r['id']}: {r['files']} files, {r['lines']} lines ({langs} lines by ext). Import graph is regex-based, best effort.")
        if r["scripts"]:
            out("scripts: " + "; ".join(f"{k}: {short(v, 40)}" for k, v in r["scripts"].items()))
        out("entry points: " + (", ".join(r["entry_points"]) or "none found"))
        out("docs: " + (", ".join(r["docs"]) or "none"))
        if r.get("readme"):
            out("README excerpt:")
            for ln in r["readme"]:
                out(f"  | {ln}")
        if r["externals"]:
            out("top external imports: " + ", ".join(f"{k}({v})" for k, v in r["externals"].items()))
        if r["generated"]:
            out("generated/lock: " + ", ".join(r["generated"]))
        if r["large_files"]:
            out("large code files: " + ", ".join(r["large_files"]))
        out("dirs (wave hint | files code/all | lines | → imports):")
        for d, i in r["dirs"].items():
            imps = ", ".join(f"{t}({n})" for t, n in sorted(i["imports"].items(), key=lambda x: -x[1]))
            exts = ",".join(i["ext"])
            out(f"  w{i['wave_hint']} {d}: {i['code_files']}/{i['files']} files, {i['lines']} lines [{exts}]"
                + (f" → {imps}" if imps else ""))
    if data["contexts"]:
        out("existing contexts: " + ", ".join(f"{k} v{v['version']}{' STALE' if v['stale'] else ''} ({v['files']} files)"
                                             for k, v in data["contexts"].items()))
        out("uncovered code files by dir: " + (", ".join(f"{d} ({n})" for d, n in data["uncovered"].items()) or "none"))


# ---- learn-all state -------------------------------------------------------
def la_dir(ws, run=None):
    base = ws.cache / "learn-all"
    return base / run if run else base


def active_run(ws):
    p = la_dir(ws) / "active"
    return p.read_text(encoding="utf-8").strip() if p.is_file() else None


def set_active(ws, run):
    p = la_dir(ws) / "active"
    if run:
        write_text(p, run)
    elif p.exists():
        p.unlink()


def resolve_run(ws, run=None):
    run = run or active_run(ws)
    if not run:
        runs = sorted(p.name for p in la_dir(ws).glob("la-*")) if la_dir(ws).is_dir() else []
        if not runs:
            raise BwError("no learn-all run. Start one: /bookworm:learn-all")
        run = runs[-1]
    if not (la_dir(ws, run) / "jobs.json").is_file():
        raise BwError(f"unknown learn-all run '{run}'")
    return run


def load_jobs(ws, run):
    return read_json(la_dir(ws, run) / "jobs.json")


def save_jobs(ws, run, jobs):
    jobs["updated_at"] = now()
    write_json(la_dir(ws, run) / "jobs.json", jobs)


ATLAS_TEMPLATE = {"jobs": [
    {"job": "game-state", "context_id": "game-state", "folder": "features/game-state",
     "include": ["app:src/context/GameContext.tsx", "app:src/lib/gameEngine.ts", "app:src/types/game.ts"],
     "depth": "deep", "wave": 1, "neighbors": ["peer-transport"], "why": "core state machine every screen uses"},
    {"job": "ui-kit", "context_id": "ui-kit", "folder": "components/ui-kit", "include": ["app:src/components/ui/**"],
     "depth": "light", "wave": 1, "neighbors": [], "why": "shadcn primitives; conventions only"},
    {"job": "word-data", "context_id": "word-data", "folder": "data/word-data",
     "include": ["app:src/i18n/locales/*/wordPairs.ts"], "depth": "skip", "wave": 1, "neighbors": [],
     "why": "word list data"}]}
CARD_TEMPLATE = {"job": "detective-scan", "context_id": "detective-scan", "status": "ok",
                 "summary": "One or two sentences: what this context covers.",
                 "routes": ["Changing scan rules → detective-scan-context.md#rules"],
                 "interactions": [{"to": "game-state", "kind": "depends",
                                   "evidence": "app:src/components/shared/ActionScreens/DetectiveActionScreen.tsx → submitDetectiveScan"}],
                 "unknowns": ["no decision record for the scan limit"],
                 "not_covered": []}


def validate_atlas(ws, atlas):
    jobs = atlas.get("jobs") if isinstance(atlas, dict) else atlas
    if not isinstance(jobs, list) or not jobs:
        raise BwError("atlas must be {\"jobs\": [...]} with at least one job (bw learn-all template atlas)")
    errs, seen, ctx_ids = [], set(), set()
    for j in jobs:
        name = j.get("job")
        if not isinstance(name, str) or not SLUG.match(name) or name in seen:
            errs.append(f"job '{name}': needs a unique slug 'job'")
        seen.add(name)
        if j.get("depth") not in DEPTH_COST:
            errs.append(f"job {name}: depth must be deep, light or skip")
        if not isinstance(j.get("wave"), int) or j["wave"] < 1:
            errs.append(f"job {name}: wave must be an integer ≥ 1")
        if not isinstance(j.get("include"), list) or not j["include"]:
            errs.append(f"job {name}: include must list repo:globs")
        if j.get("depth") != "skip":
            cid = j.get("context_id")
            if not isinstance(cid, str) or not SLUG.match(cid) or cid in ctx_ids:
                errs.append(f"job {name}: needs a unique slug context_id")
            ctx_ids.add(cid)
            if not j.get("folder"):
                errs.append(f"job {name}: needs folder (under .bookworm/context/)")
            existing = ws.contexts().get(cid)
            if existing and existing.rel_folder != str(j.get("folder", "")).strip("/").removeprefix("context/"):
                errs.append(f"job {name}: context {cid} already exists at {existing.rel_folder}; use that folder")
    if errs:
        raise BwError("atlas invalid:\n  " + "\n  ".join(errs))
    return jobs


ATLAS_LEGEND = [
    "Depth  deep  = full docs + rules, ≤40 tool calls, ~350K tokens",
    "       light = conventions only, ≤12 tool calls, ~100K tokens",
    "       skip  = not learned; the reason goes to coverage.md",
    f"Wave   1 runs first; later waves read earlier waves' cards. ≤{MAX_PARALLEL} workers at once.",
]
ATLAS_FIELDS = ("Fields: job (slug), context_id (slug; reuse an existing id to update it), folder (<group>/<slug>), "
                "include (repo:glob list; a dir = dir/**), depth (deep|light|skip), wave (int ≥ 1), "
                "neighbors (job names), why (one line).")


def kilo(n):
    return f"{n / 1000:.1f}K" if n >= 1000 else str(n)


def atlas_preview(ws, jobs):
    """Fixed-width (≤ 80 cols) atlas table + legend, so every run shows the same thing."""
    snap, pre = Snapshot(ws), f"{ws.default_repo}:"
    rows, total = [], 0
    for j in sorted(jobs, key=lambda x: (x["depth"] == "skip", x["wave"], x["job"])):
        files = snap.match(j["include"])
        lines = 0
        for q in files:
            try:
                raw = ws.abs(q).read_bytes()
            except OSError:
                continue
            if b"\0" not in raw[:8192]:
                lines += raw.count(b"\n") + (0 if raw.endswith(b"\n") or not raw else 1)
        total += lines if j["depth"] != "skip" else 0
        wave = "" if j["depth"] == "skip" else j["wave"]
        rows.append(f"{wave:>2}  {j['depth']:<5}  {short(j['job'], 20):<20} {len(files):>5} {kilo(lines):>6}  "
                    f"{short(j.get('why', ''), 30)}")
        inc = ", ".join(p[len(pre):] if p.startswith(pre) else p for p in j["include"])
        rows.append(f"{'':11}{short(inc, 69)}")
    n = Counter(j["depth"] for j in jobs)
    cost = sum(DEPTH_COST[j["depth"]] for j in jobs)
    out(f"Atlas · {len(jobs)} jobs ({n['deep']} deep, {n['light']} light, {n['skip']} skip) · "
        f"{kilo(total)} lines to learn · est ~{cost / 1e6:.1f}M tokens")
    out(f" W  {'DEPTH':<5}  {'JOB':<20} {'FILES':>5} {'LINES':>6}  WHY")
    for r in rows:
        out(r)
    out("")
    for ln in ATLAS_LEGEND:
        out(ln)
    out('Edit   "skip X" · "make X light" · "merge A+B" · "X to wave 2" · or confirm')


def cmd_template(kind):
    if kind in ("atlas", "card"):
        dump(ATLAS_TEMPLATE if kind == "atlas" else CARD_TEMPLATE)
        if kind == "atlas":
            out(ATLAS_FIELDS)
            for ln in ATLAS_LEGEND:
                out(ln)
    else:
        from .store import TEMPLATES
        out((TEMPLATES / f"{kind}.md").read_text(encoding="utf-8").rstrip())


def cmd_start(ws, atlas_path=None, resume=None, dry_run=False):
    if dry_run:
        if not atlas_path:
            raise BwError("--dry-run needs --atlas <file>")
        atlas_preview(ws, validate_atlas(ws, read_json(atlas_path)))
        return
    act = active_run(ws)
    if resume is not None:
        run = resolve_run(ws, resume or None)
        if act and act != run:
            raise BwError(f"learn-all run {act} is active; resume that one", 1)
        jobs = load_jobs(ws, run)
        requeued, finished = [], []
        for j in jobs["jobs"]:
            if j["status"] == "running":
                if card_ok(ws, run, j) and not job_problems(ws, run, j):
                    j["status"] = "done"
                    finished.append(j["job"])
                else:
                    j["status"] = "queued"
                    requeued.append(j["job"])
        jobs["state"] = "active"
        save_jobs(ws, run, jobs)
        set_active(ws, run)
        out(f"resumed {run}: re-queued {', '.join(requeued) or 'nothing'}; found finished {', '.join(finished) or 'none'}")
        print_status(ws, run, jobs)
        return
    if act:
        raise BwError(f"learn-all run {act} is still active. Resume it (/bookworm:learn-all --resume) "
                      f"or abandon it: bw learn-all abandon {act}", 1)
    if not atlas_path:
        raise BwError("pass --atlas <file> (see bw learn-all template atlas)")
    atlas = read_json(atlas_path)
    jobs = validate_atlas(ws, atlas)
    n = 1 + max([int(p.name[3:]) for p in la_dir(ws).glob("la-*") if p.name[3:].isdigit()] or [0]) \
        if la_dir(ws).is_dir() else 1
    run = f"la-{n}"
    d = la_dir(ws, run)
    (d / "cards").mkdir(parents=True)
    write_json(d / "atlas.json", {"jobs": jobs, "confirmed_at": now()})
    state = {"run": run, "state": "active", "created_at": now(), "jobs": [
        {"job": j["job"], "wave": j["wave"], "depth": j["depth"], "context_id": j.get("context_id"),
         "status": "skipped" if j["depth"] == "skip" else "queued", "retries": 0, "reason": None,
         "mode": "update" if j.get("context_id") in ws.contexts() else "new"} for j in jobs]}
    save_jobs(ws, run, state)
    set_active(ws, run)
    try:
        os.unlink(atlas_path)
    except OSError:
        pass
    cost = sum(DEPTH_COST[j["depth"]] for j in jobs)
    out(f"started {run}: {len(jobs)} jobs, estimated {cost / 1e6:.2f}M input tokens for workers")
    print_status(ws, run, state)


def print_status(ws, run, jobs):
    counts = Counter(j["status"] for j in jobs["jobs"])
    out(f"{run} [{jobs.get('state')}]: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    for j in sorted(jobs["jobs"], key=lambda x: (x["wave"], x["job"])):
        extra = f" — {j['reason']}" if j.get("reason") else ""
        out(f"  w{j['wave']} {j['job']:<24} {j['depth']:<5} {j['mode']:<6} {j['status']}{extra}")
    if jobs.get("published") and run != active_run(ws):
        out(published_note(run, jobs))


def published_note(run, jobs):
    return (f"{run} was published ({jobs['published']['commit']}); nothing to resume or re-publish. A re-run starts a new run "
            "whose atlas holds only uncovered areas without a reason in coverage.md and stale contexts; if there are none, "
            "reply that the workspace is already learned and stop.")


def cmd_cards(ws, run=None):
    run = resolve_run(ws, run)
    for j in sorted(load_jobs(ws, run)["jobs"], key=lambda x: (x["wave"], x["job"])):
        if j["status"] != "done":
            continue
        c = read_json(la_dir(ws, run) / "cards" / f"{j['job']}.json", {})
        ctx = ws.contexts().get(j["context_id"])
        where = f"context/{ctx.rel_folder}/{ctx.router()}" if ctx else "?"
        out(f"[{j['context_id']}] {where}: {short(c.get('summary', ''), 240)}")
        for r in (c.get("routes") or [])[:5]:
            out(f"  route: {short(r, 140)}")
        for it in (c.get("interactions") or [])[:6]:
            out(f"  {it.get('kind')} → {it.get('to')}: {short(it.get('evidence', ''), 100)}")
        for u in (c.get("unknowns") or [])[:3]:
            out(f"  unknown: {short(u, 140)}")


def cmd_status(ws, run=None):
    run = resolve_run(ws, run)
    print_status(ws, run, load_jobs(ws, run))


def current_wave(jobs):
    open_waves = [j["wave"] for j in jobs["jobs"] if j["status"] in ("queued", "running")]
    return min(open_waves) if open_waves else None


def cmd_next(ws, run=None, max_n=None):
    run = resolve_run(ws, run)
    jobs = load_jobs(ws, run)
    if jobs.get("published") and run != active_run(ws):
        out(published_note(run, jobs))
        return
    wave = current_wave(jobs)
    if wave is None:
        out(f"{run}: all jobs finished. Next: connect (bw learn-all connect), overview, coverage, publish.")
        return
    running = [j for j in jobs["jobs"] if j["status"] == "running"]
    free = max(0, min(max_n or MAX_PARALLEL, max_parallel()) - len(running))
    picked = [j for j in jobs["jobs"] if j["status"] == "queued" and j["wave"] == wave][:free]
    for j in picked:
        j["status"] = "running"
        j["started_at"] = now()
    save_jobs(ws, run, jobs)
    if not picked:
        out(f"{run} wave {wave}: {len(running)} job(s) still running ({', '.join(j['job'] for j in running)}); wait for them")
        return
    out(f"{run} wave {wave}: dispatch {len(picked)} worker(s) now, in parallel, one bookworm:bw-knowledge agent each:")
    for j in picked:
        out(f"  {j['job']} ({j['depth']}) → prompt: \"learn-all job {j['job']} (run {run}): start with bw learn-all brief {j['job']}\"")


def cmd_brief(ws, run, job):
    run = resolve_run(ws, run)
    atlas = read_json(la_dir(ws, run) / "atlas.json")
    spec = next((j for j in atlas["jobs"] if j["job"] == job), None)
    if not spec:
        raise BwError(f"no job {job} in {run}")
    jobs = load_jobs(ws, run)
    state = next(j for j in jobs["jobs"] if j["job"] == job)
    exists = spec["context_id"] in ws.contexts()
    out(f"job {job} ({spec['depth']}, {'update existing' if exists else 'new'} context {spec['context_id']}), run {run}")
    out(f"why: {spec.get('why', '')}")
    out(f"include: {', '.join(spec['include'])}")
    if state.get("include_override"):
        out(f"narrowed include (retry): {', '.join(state['include_override'])}")
    out(f"folder: .bookworm/context/{spec['folder'].strip('/').removeprefix('context/')}/")
    out(f"neighbors: {', '.join(spec.get('neighbors') or []) or 'none'}")
    budget = "≤ 40 tool calls; router + scope files only where useful" if spec["depth"] == "deep" \
        else "≤ 12 tool calls; router only: what's there, conventions, where to change, what to avoid"
    out(f"budget: {budget}")
    steps = [] if exists else [f"bw ctx new {spec['folder']} --id {spec['context_id']} --title \"…\""]
    steps += [f"write docs; bw ctx set {spec['context_id']} --include … --anchor …",
              f"bw ctx refresh {spec['context_id']}",
              f"write card .bookworm/.cache/learn-all/{run}/cards/{job}.json (bw learn-all template card)",
              f"bw learn-all done {job}",
              "do NOT publish, edit .bookworm/context.md, or touch other context folders"]
    out("steps: " + " → ".join(steps))
    earlier = [j for j in jobs["jobs"] if j["wave"] < spec["wave"] and j["status"] == "done"]
    if earlier:
        out("cards from earlier waves (link to these instead of re-explaining):")
        for j in earlier:
            card = read_json(la_dir(ws, run) / "cards" / f"{j['job']}.json", {})
            out(f"  [{j['context_id']}] {short(card.get('summary', ''), 200)}")
            for r in (card.get("routes") or [])[:4]:
                out(f"     route: {short(r, 120)}")


def card_ok(ws, run, j):
    p = la_dir(ws, run) / "cards" / f"{j['job']}.json"
    if not p.is_file():
        return False
    try:
        card = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return False
    return all(k in card for k in CARD_KEYS)


def job_problems(ws, run, j):
    ws.contexts(refresh=True)
    c = ws.contexts().get(j["context_id"])
    if c is None:
        return [f"context {j['context_id']} not found (bw ctx new …)"]
    ids = {k for k in ws.contexts() if not k.startswith("!")}
    errs, _ = ctxmod.validate_manifest(ws, c, ids)
    if not (c.data.get("sources") or {}).get("hashes"):
        errs.append(f"run bw ctx refresh {c.id}")
    if not card_ok(ws, run, j):
        errs.append(f"card missing or lacks keys {CARD_KEYS}: .bookworm/.cache/learn-all/{run}/cards/{j['job']}.json")
    return errs


def cmd_done(ws, run, job):
    run = resolve_run(ws, run)
    jobs = load_jobs(ws, run)
    j = next((x for x in jobs["jobs"] if x["job"] == job), None)
    if not j:
        raise BwError(f"no job {job} in {run}")
    errs = job_problems(ws, run, j)
    if errs:
        raise BwError(f"job {job} not done:\n  " + "\n  ".join(errs), 1)
    jobs = load_jobs(ws, run)
    j = next(x for x in jobs["jobs"] if x["job"] == job)
    j["status"] = "done"
    j["finished_at"] = now()
    save_jobs(ws, run, jobs)
    out(f"{run}: job {job} done")


def cmd_fail(ws, run, job, reason, include=None):
    run = resolve_run(ws, run)
    jobs = load_jobs(ws, run)
    j = next((x for x in jobs["jobs"] if x["job"] == job), None)
    if not j:
        raise BwError(f"no job {job} in {run}")
    if j["retries"] < 1:
        j["retries"] += 1
        j["status"] = "queued"
        j["reason"] = f"retry: {reason}"
        if include:
            j["include_override"] = include
        out(f"{run}: job {job} re-queued for one retry" + (" with narrower include" if include else ""))
    else:
        j["status"] = "failed"
        j["reason"] = reason
        out(f"{run}: job {job} failed — {reason} (reported in coverage)")
    save_jobs(ws, run, jobs)


def cmd_abandon(ws, run):
    run = resolve_run(ws, run)
    jobs = load_jobs(ws, run)
    jobs["state"] = "abandoned"
    save_jobs(ws, run, jobs)
    if active_run(ws) == run:
        set_active(ws, None)
    out(f"{run} abandoned; its finished context folders stay (unpublished)")


def edges_from_cards(ws, run):
    jobs = load_jobs(ws, run)
    proposals = []
    for j in jobs["jobs"]:
        if j["status"] != "done":
            continue
        card = read_json(la_dir(ws, run) / "cards" / f"{j['job']}.json", {})
        for it in card.get("interactions") or []:
            to = it.get("to")
            if to and to != j["context_id"] and to in ws.contexts():
                proposals.append((j["context_id"], to, it.get("kind", "related"), it.get("evidence", "")))
    return proposals


def cmd_connect(ws, run=None, apply=False):
    run = resolve_run(ws, run)
    props = edges_from_cards(ws, run)
    if not props:
        out("no interactions in cards point at existing contexts")
        return
    by_src = defaultdict(list)
    for src, to, kind, ev in props:
        by_src[src].append((to, kind, ev))
    skipped = []
    for src, items in sorted(by_src.items()):
        c = ws.ctx(src)
        deps = {d["id"]: d for d in c.data.get("depends_on") or []}
        related = set(c.data.get("related") or [])
        for to, kind, ev in items:
            if kind == "depends" and to not in deps:
                deps[to] = {"id": to, "reason": short(ev or "relies on its contract", 160)}
                if apply:
                    c.data["depends_on"] = list(deps.values())
                    if ctxmod.cycles(ws):
                        del deps[to]
                        c.data["depends_on"] = list(deps.values())
                        skipped.append(f"{src} → {to} (would form a cycle; kept as related)")
                        related.add(to)
            elif kind != "depends" and to not in deps:
                related.add(to)
        out(f"{src}: depends_on {', '.join(deps) or '-'}; related {', '.join(sorted(related)) or '-'}")
        if apply:
            before = (c.data.get("depends_on"), c.data.get("related"), c.data.get("upstream_seen"))
            c.data["depends_on"] = list(deps.values())
            c.data["related"] = sorted(related - set(deps))
            c.data["upstream_seen"] = {d: ws.contexts()[d].version for d in deps if d in ws.contexts()}
            if (c.data["depends_on"], c.data["related"], c.data["upstream_seen"]) != before:
                c.save()
    for s in skipped:
        out(f"  skipped: {s}")
    out("applied" if apply else "dry run; add --apply to write these edges")


def coverage_data(ws, run=None):
    snap = Snapshot(ws)
    files = coverage_files(ws, snap)
    cov = covered_set(ws, snap)
    reasons = {}
    if run:
        atlas = read_json(la_dir(ws, run) / "atlas.json", {"jobs": []})
        jobs = {j["job"]: j for j in load_jobs(ws, run)["jobs"]}
        for spec in atlas["jobs"]:
            st = jobs.get(spec["job"], {})
            if st.get("status") in ("skipped", "failed", "queued", "running"):
                why = {"skipped": f"skipped: {spec.get('why', '')}", "failed": f"failed: {st.get('reason')}",
                       "queued": "not learned yet (run unfinished)", "running": "not learned yet (run unfinished)"}[st["status"]]
                for q in snap.match(spec["include"]):
                    reasons.setdefault(q, why)
            card = read_json(la_dir(ws, run) / "cards" / f"{spec['job']}.json", {})
            for pat in card.get("not_covered") or []:
                for q in snap.match([pat.split(" ")[0]]):
                    if q not in cov:
                        reasons.setdefault(q, f"left out by {spec['job']}")
    uncovered = [q for q in files if q not in cov]
    pct = 100.0 * (len(files) - len(uncovered)) / len(files) if files else 100.0
    return {"included": len(files), "covered": len(files) - len(uncovered), "percent": round(pct, 1),
            "uncovered": [{"path": q, "reason": reasons.get(q)} for q in uncovered]}


def coverage_markdown(ws, data, run=None):
    lines = ["# Knowledge coverage", "",
             f"Generated by `bw learn-all coverage`{f' for {run}' if run else ''} at {now()}. Navigation aid, not a context.", "",
             f"**{data['covered']} of {data['included']} code files covered ({data['percent']}%).**", ""]
    groups = defaultdict(list)
    for u in data["uncovered"]:
        groups[u["reason"] or "no reason recorded"].append(u["path"])
    if groups:
        lines += ["| Not covered | Files | Reason |", "|---|---|---|"]
        for reason, paths in sorted(groups.items()):
            dirs = Counter(str(PurePosixPath(p).parent) for p in paths)
            where = ", ".join(f"`{d}/` ({n})" for d, n in dirs.most_common(6))
            lines.append(f"| {where} | {len(paths)} | {reason} |")
    else:
        lines.append("Every code file is covered by a context.")
    contexts = [(cid, c) for cid, c in ws.contexts().items() if not cid.startswith("!")]
    lines += ["", "## Contexts", ""]
    snap = Snapshot(ws)
    for cid, c in sorted(contexts):
        lines.append(f"- `{cid}` — {len(snap.match(c.includes))} files — `context/{c.rel_folder}/{c.router()}`")
    return "\n".join(lines) + "\n"


def cmd_coverage(ws, run=None, as_json=False, write=False):
    try:  # latest run's skip/fail reasons apply after it is published too
        run = resolve_run(ws, run)
    except BwError:
        if run:
            raise
        run = None
    data = coverage_data(ws, run)
    if as_json:
        dump(data)
    else:
        out(f"coverage: {data['covered']}/{data['included']} code files ({data['percent']}%)")
        no_reason = [u["path"] for u in data["uncovered"] if not u["reason"]]
        with_reason = [u for u in data["uncovered"] if u["reason"]]
        if with_reason:
            out(f"  {len(with_reason)} uncovered with a reason")
        if no_reason:
            out(f"  {len(no_reason)} uncovered WITHOUT a reason: " + ", ".join(no_reason[:20])
                + (" …" if len(no_reason) > 20 else ""))
    if write:
        path = ws.ctx_dir / "coverage.md"
        text = coverage_markdown(ws, data, run)
        if path.is_file():  # keep sections written by hand, e.g. "## Reasons for gaps"
            old = path.read_text(encoding="utf-8")
            kept = [sec for sec in re.split(r"\n(?=## )", old)[1:] if not sec.startswith("## Contexts")]
            if kept:
                text = text.rstrip("\n") + "\n\n" + "\n".join(k.rstrip("\n") + "\n" for k in kept)
        write_text(path, text)
        out(f"wrote {ws.rel(path)}")


def after_publish(ws, run, commit):
    jobs = load_jobs(ws, run)
    done = all(j["status"] in ("done", "failed", "skipped") for j in jobs["jobs"])
    jobs["state"] = "complete" if done else "partial"
    jobs["published"] = {"commit": commit, "at": now()}
    save_jobs(ws, run, jobs)
    set_active(ws, None)
    out(f"{run}: {jobs['state']}" + ("" if done else " — resume later with /bookworm:learn-all --resume"))
