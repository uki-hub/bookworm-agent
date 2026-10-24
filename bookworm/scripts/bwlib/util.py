"""Small shared helpers: errors, JSON files, time, slugs, globs, output."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path


class BwError(Exception):
    """Usage or state error. exit 2 unless a code is given."""

    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


class GateFailed(BwError):
    def __init__(self, message):
        super().__init__(message, 1)


SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48].strip("-") or "item"


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if default is not None:
            return default
        raise BwError(f"missing file: {path}")
    except json.JSONDecodeError as e:
        raise BwError(f"invalid JSON in {path}: {e}")


def write_json(path, data):
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def out(text=""):
    sys.stdout.write(text + "\n")


def dump(data):
    out(json.dumps(data, indent=2, ensure_ascii=False))


@lru_cache(maxsize=2048)
def glob_regex(pattern):
    """Glob → regex. `*` stays in one segment, `**` spans segments."""
    i, res = 0, ""
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if pattern[i:i + 2] == "**":
                i += 1
                if pattern[i + 1:i + 2] == "/":
                    res += "(?:[^/]+/)*"
                    i += 1
                else:
                    res += ".*"
            else:
                res += "[^/]*"
        elif c == "?":
            res += "[^/]"
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j == -1:
                res += r"\["
            else:
                body = pattern[i + 1:j].replace("\\", "\\\\")
                if body.startswith("!"):
                    body = "^" + body[1:]
                res += "[" + body + "]"
                i = j
        else:
            res += re.escape(c)
        i += 1
    return re.compile(res + r"\Z")


def has_magic(pattern):
    return any(ch in pattern for ch in "*?[")


def glob_match(pattern, path):
    return bool(glob_regex(pattern).match(path))


def short(text, n=100):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
