"""Prompt-size budget (BLUEPRINT §12, acceptance 15): command skill ≤ 60 lines, agent ≤ 40, authoring ≤ 150."""

import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
COMMANDS = {"init", "learn", "learn-all", "context", "context-check", "context-update", "context-del", "context-rename", "plan",
            "plan-todo", "run", "do", "todo", "todo-check", "todo-update", "todo-del", "affected"}


def lines(p):
    return len(p.read_text(encoding="utf-8").splitlines())


class TestPromptSize(unittest.TestCase):
    def test_skills(self):
        found = {p.parent.name for p in (PLUGIN / "skills").glob("*/SKILL.md")}
        self.assertEqual(found - {"authoring"}, COMMANDS)
        for name in COMMANDS:
            n = lines(PLUGIN / "skills" / name / "SKILL.md")
            self.assertLessEqual(n, 60, f"skill {name}: {n} lines")
        self.assertLessEqual(lines(PLUGIN / "skills/authoring/SKILL.md"), 150)

    def test_agents(self):
        agents = list((PLUGIN / "agents").glob("*.md"))
        self.assertEqual({p.stem for p in agents}, {"bw-knowledge", "bw-inspector"})
        for p in agents:
            self.assertLessEqual(lines(p), 40, p.name)

    def test_command_skills_are_user_only_and_preapprove_bw(self):
        for name in COMMANDS:
            head = (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
            self.assertIn("disable-model-invocation: true", head, name)
            self.assertIn("allowed-tools: Bash(bw *)", head, name)

    def test_no_free_text_in_shell_injection(self):
        """Only $0 (an id) may reach a `!` command, except init's flags; free text never reaches a shell."""
        for name in COMMANDS:
            text = (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            for line in text.splitlines():
                if line.startswith("!`") and "$ARGUMENTS" in line:
                    # only init takes flags; every other skill injects $0 (unexpanded when empty)
                    self.assertIn(name, ("init",), f"{name}: $ARGUMENTS in a shell injection")

    def test_run_steps_shared(self):
        """run and do inject the same run steps (templates/run-steps.md); neither keeps its own copy."""
        steps = (PLUGIN / "templates/run-steps.md").read_text(encoding="utf-8")
        self.assertTrue(steps.startswith("2. `bw run start <task>`"))
        for name in ("run", "do"):
            text = (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("!`bw template run-steps || true`", text.splitlines(), name)
            self.assertNotIn("bw run finish <task>", text, name)


if __name__ == "__main__":
    unittest.main()
