"""SessionStart: ≤ 6 lines of Bookworm orientation when .bookworm/ exists; silent otherwise or on any error."""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
        start = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        os.chdir(start)
        from bwlib import core
        from bwlib.store import Workspace
        ws = Workspace.find(required=False)
        if ws is None:
            return 0
        buf = io.StringIO()
        with redirect_stdout(buf):
            core.cmd_status(ws, brief=True)
        text = "\n".join(buf.getvalue().strip().splitlines()[:6])
        if text:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
