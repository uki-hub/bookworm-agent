"""PreToolUse guard for Bookworm agents. Prints a deny decision or nothing.

- bookworm:bw-inspector: no Write/Edit; Bash only for read-only commands.
- bookworm:bw-knowledge: Write/Edit only inside .bookworm/context.md, context/**, .cache/**; no git/file mutations in Bash.
- main thread: no direct edits of task.json/run.json (bw owns them); bw calls can't be chained with other
  commands; no source git mutations while a Bookworm run is active.
Any internal error → exit 0 silently (never break the session).
"""

from __future__ import annotations

import json
import os
import re
import sys

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
GIT_RO = {"status", "log", "show", "diff", "rev-parse", "ls-files", "blame", "grep", "cat-file", "shortlog", "describe"}
GIT_MUTATE = {"commit", "add", "reset", "checkout", "stash", "push", "restore", "clean", "rebase", "merge",
              "cherry-pick", "revert", "rm", "mv", "switch", "tag", "am", "apply", "pull", "fetch", "branch", "worktree"}
SHELL_RO = {"ls", "cat", "head", "tail", "wc", "grep", "rg", "pwd", "echo", "sort", "uniq", "cut", "file", "stat",
            "diff", "tree", "basename", "dirname", "realpath", "which", "true", "printf", "nl", "tr", "jq", "sed", "find"}
BW_RO = {("status",), ("check",), ("ctx", "tree"), ("ctx", "show"), ("ctx", "stale"), ("task", "list"),
         ("task", "show"), ("affected",), ("run", "effects"), ("findings", "get"), ("findings", "put"), ("survey",),
         ("learn-all", "status"), ("learn-all", "brief"), ("learn-all", "template"), ("lock", "status")}
FILE_MUTATORS = {"rm", "mv", "cp", "touch", "mkdir", "rmdir", "chmod", "ln", "truncate", "dd", "tee", "install", "unlink"}
HARMLESS_WITH_BW = {"cd", "echo", "true", "printf"}


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": f"Bookworm guard: {reason}"}}))
    return 0


def norm(p):
    return os.path.normcase(os.path.realpath(p))


def under(path, base):
    path, base = norm(path), norm(base)
    return path == base or path.startswith(base.rstrip("\\/") + os.sep)


def find_workspace(start):
    p = os.path.realpath(start)
    while True:
        if os.path.isfile(os.path.join(p, ".bookworm", "bookworm.json")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def split_heredoc(cmd):
    """Return (command without heredoc bodies, ok). ok=False if text follows a heredoc terminator."""
    lines = cmd.split("\n")
    result, i = [], 0
    while i < len(lines):
        line = lines[i]
        result.append(line)
        m = re.search(r"<<-?\s*(['\"]?)(\w+)\1", line)
        i += 1
        if m:
            term = m.group(2)
            while i < len(lines) and lines[i].strip() != term:
                i += 1
            if i >= len(lines):
                return " ".join(result), False
            i += 1
    return "\n".join(result), True


def segments(cmd):
    """Split on ; && || | & and newlines outside quotes. Flags substitution and redirections."""
    segs, cur, q, i = [], "", None, 0
    flags = {"subst": False, "redirects": []}
    while i < len(cmd):
        ch = cmd[i]
        if ch == "\\" and q != "'" and cmd.startswith("\n", i + 1):  # line continuation: one command
            i += 2
            continue
        if q:
            if ch == q:
                q = None
            elif q == '"' and (cmd.startswith("$(", i) or ch == "`"):
                flags["subst"] = True
            cur += ch
        elif ch in "'\"":
            q = ch
            cur += ch
        elif cmd.startswith("$(", i) or ch == "`" or cmd.startswith("<(", i) or cmd.startswith(">(", i):
            flags["subst"] = True
            cur += ch
        elif ch in ";\n" or (ch == "&" and not cur.endswith(">")) or ch == "|":
            if cmd.startswith("&&", i) or cmd.startswith("||", i):
                i += 1
            if cur.strip():
                segs.append(cur.strip())
            cur = ""
        elif ch == ">":
            m = re.match(r">>?\s*(&\d|[^\s;&|]+)", cmd[i:])
            target = m.group(1) if m else ""
            flags["redirects"].append(target)
            cur += ch
        else:
            cur += ch
        i += 1
    if cur.strip():
        segs.append(cur.strip())
    return segs, flags


def words(seg):
    import shlex
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return seg.split()


def strip_redirects(ws):
    out, skip = [], False
    for w in ws:
        if skip:
            skip = False
            continue
        if re.match(r"^\d*>>?&?\d*$", w) or w in ("<", "<<"):
            skip = not re.match(r"^\d*>&\d+$", w)
            continue
        if re.match(r"^\d*>>?\S+$", w) or w.startswith("<<"):
            continue
        out.append(w)
    return out


def bw_ro(ws):
    args = [w for w in ws[1:] if not w.startswith("-")]
    if "--help" in ws or "-h" in ws:
        return True
    if args[:2] == ["learn-all", "coverage"]:
        return "--write" not in ws
    return any(tuple(args[:len(k)]) == k for k in BW_RO)


def git_sub(ws):
    i = 1
    while i < len(ws) and ws[i].startswith("-"):
        i += 2 if ws[i] in ("-C", "-c") else 1
    return ws[i] if i < len(ws) else ""


def gitbash_path(p):
    """Git Bash /d/x → d:/x (Windows only)."""
    p = p.strip("'\"")
    if os.name == "nt" and re.match(r"^/([a-zA-Z])/", p):
        p = p[1] + ":" + p[2:]
    return p


def harmless_redirect(t):
    return t in ("/dev/null", "&1", "&2") or t.startswith("&")


def inspector_bash(cmd):
    body, ok = split_heredoc(cmd)
    if not ok:
        return "unterminated heredoc"
    segs, flags = segments(body)
    if flags["subst"]:
        return "command substitution is not allowed for the read-only inspector"
    bad = [t for t in flags["redirects"] if not harmless_redirect(t)]
    if bad:
        return f"output redirection to {bad[0]} is not allowed (read-only)"
    for seg in segs:
        ws = strip_redirects(words(seg))
        if not ws:
            continue
        head = os.path.basename(ws[0])
        if head == "bw":
            if not bw_ro(ws):
                return f"'{' '.join(ws[:3])}' writes; the inspector may only run read-only bw commands (and bw findings put)"
        elif head == "git":
            if git_sub(ws) not in GIT_RO:
                return f"git {git_sub(ws)} is not read-only"
        elif head in SHELL_RO:
            if head == "sed" and any(w.startswith("-i") or w == "--in-place" for w in ws):
                return "sed -i writes files"
            if head == "find" and any(w in ("-exec", "-execdir", "-delete", "-ok", "-fprint", "-fprintf", "-fls") for w in ws):
                return "find with -exec/-delete is not allowed"
        else:
            return f"'{head}' is not on the read-only allowlist (bw RO commands, git status/log/show/diff, ls, cat, grep, …)"
    return None


def knowledge_bash(cmd, bw_dir, cwd):
    body, _ = split_heredoc(cmd)
    segs, flags = segments(body)
    here = cwd
    for seg in segs:  # a cd changes where relative paths land
        ws = strip_redirects(words(seg))
        if len(ws) >= 2 and ws[0] == "cd":
            here = os.path.join(here, os.path.expanduser(gitbash_path(ws[1])))

    def inside(t):
        return under(os.path.join(here, gitbash_path(t)), bw_dir)

    for t in flags["redirects"]:
        if not harmless_redirect(t) and not inside(t):
            return f"redirecting output to {t} would write outside .bookworm/; knowledge agents may only write knowledge"
    for seg in segs:
        ws = strip_redirects(words(seg))
        if not ws:
            continue
        head = os.path.basename(ws[0])
        if head == "git":
            sub = git_sub(ws)
            if sub in GIT_MUTATE:
                return f"git {sub} is not allowed; bw publish commits knowledge, and source git is the user's"
        elif head in FILE_MUTATORS:
            targets = [w for w in ws[1:] if not w.startswith("-")]
            if not targets or not all(inside(w) for w in targets):
                return f"'{head}' outside .bookworm/ is not allowed for knowledge agents"
        elif head in ("sed", "perl") and any(w.startswith("-i") for w in ws):
            nonopt = [w for w in ws[1:] if not w.startswith("-")]
            files = nonopt[1:] if "-e" not in ws and len(nonopt) > 1 else nonopt
            if not files or not all(inside(w) for w in files):
                return f"{head} -i outside .bookworm/ is not allowed"
        elif head in ("npm", "yarn", "pnpm", "pip", "bun") and len(ws) > 1 and ws[1] in ("install", "i", "ci", "add", "remove", "uninstall", "update"):
            return f"{head} {ws[1]} changes the project; knowledge agents only read source"
    return None


def main_bash(cmd, root):
    body, _ = split_heredoc(cmd)
    segs, flags = segments(body)
    heads = [os.path.basename(w[0]) for w in (strip_redirects(words(s)) for s in segs) if w]
    if "bw" in heads:
        others = [h for h in heads if h not in ("bw", "git", *HARMLESS_WITH_BW, *SHELL_RO)]
        for s in segs:
            ws_ = strip_redirects(words(s))
            if ws_ and os.path.basename(ws_[0]) == "git" and git_sub(ws_) not in GIT_RO:
                others.append(f"git {git_sub(ws_)}")
        if others or flags["subst"]:
            return (f"bw calls may only be chained with other bw calls (found: {', '.join(others) or 'substitution'}). "
                    "Run other commands separately.")
    if root and run_active(root):
        for s in segs:
            ws = strip_redirects(words(s))
            if ws and os.path.basename(ws[0]) == "git" and git_sub(ws) in GIT_MUTATE:
                gdir = ws[ws.index("-C") + 1] if "-C" in ws else ""
                if ".bookworm" in gdir.replace("\\", "/"):
                    continue
                return (f"git {git_sub(ws)} during a Bookworm run: Bookworm never commits, stages, resets or pushes "
                        "source. Leave version control to the user.")
    return None


def run_active(root):
    tdir = os.path.join(root, ".bookworm", "tasks")
    try:
        for name in os.listdir(tdir):
            p = os.path.join(tdir, name, "task.json")
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    if json.load(f).get("status") == "running":
                        return True
    except OSError:
        return False
    return False


def decide(data):
    agent = (data.get("agent_type") or "").split(":")[-1]
    tool = data.get("tool_name") or ""
    inp = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    project = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    root = find_workspace(project) or find_workspace(cwd)
    bw_dir = os.path.join(root or project, ".bookworm")

    if tool in WRITE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if path and not os.path.isabs(path):
            path = os.path.join(cwd, path)
        if agent == "bw-inspector":
            return "the inspector is read-only. Put findings in your reply, or save them with: bw findings put <id> <<'EOF' … EOF"
        if agent == "bw-knowledge":
            allowed = [os.path.join(bw_dir, "context.md"), os.path.join(bw_dir, "context"), os.path.join(bw_dir, ".cache")]
            if not path or not any(under(path, a) for a in allowed):
                return (f"knowledge agents may only write .bookworm/context.md, .bookworm/context/** and .bookworm/.cache/**; "
                        f"{path or 'this path'} is outside. Report needed source changes instead.")
            return None
        if path and root:
            if under(path, os.path.join(bw_dir, "runs")) or (
                    under(path, os.path.join(bw_dir, "tasks")) and os.path.basename(path) == "task.json"):
                return "task.json and run.json are owned by bw. Use bw task set/step/pin, bw run …"
        return None
    if tool == "Bash":
        cmd = inp.get("command") or ""
        if agent == "bw-inspector":
            return inspector_bash(cmd)
        if agent == "bw-knowledge":
            return knowledge_bash(cmd, bw_dir, cwd) or main_bash(cmd, None)
        return main_bash(cmd, root)
    return None


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
        reason = decide(data)
    except Exception:
        return 0
    if reason:
        deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
