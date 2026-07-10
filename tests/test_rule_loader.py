from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tools.rule_loader import RuleValidationError, load_rule, load_rules


ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / "rules"
VALIDATE = ROOT / "tools" / "validate_rules.py"


class RuleLoaderTests(unittest.TestCase):
    def test_loads_split_rules(self) -> None:
        rules = load_rules(RULES_DIR)

        self.assertEqual(set(rules), {"DSN_001", "IMP_004", "IMP_007", "MNT_001", "MNT_002"})
        self.assertEqual(rules["DSN_001"].cat, "DSN")
        self.assertEqual(rules["IMP_004"].act, "FIX")
        self.assertEqual(rules["IMP_007"].sev, "H")
        self.assertEqual(rules["MNT_001"].cat, "MNT")
        self.assertEqual(rules["MNT_002"].state, "T")
        for rule in rules.values():
            self.assertIn("type", rule.met)
            self.assertIn("expr", rule.met)

    def test_validate_rules_cli_requires_expected_rules(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(VALIDATE),
                str(RULES_DIR),
                "--require",
                "DSN_001",
                "--require",
                "IMP_004",
                "--require",
                "IMP_007",
                "--require",
                "MNT_001",
                "--require",
                "MNT_002",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("validated 5 rule(s)", result.stdout)

    def test_validate_rules_cli_runs_without_site_packages(self) -> None:
        result = subprocess.run(
            [sys.executable, "-S", str(VALIDATE), str(RULES_DIR)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("validated 5 rule(s)", result.stdout)

    def test_missing_met_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rule_path = Path(tmp) / "IMP_999.yml"
            rule_path.write_text(
                textwrap.dedent(
                    """
                    id: "IMP_999"
                    lvl: "M"
                    sev: "M"
                    cat: "IMP"
                    lang: ["*"]
                    state: "P"
                    det: [{"tool": "builtin", "rule": "example"}]
                    act: "FIX"
                    rat: "example -> impact ; #example"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuleValidationError, "met"):
                load_rule(rule_path)

    def test_unknown_detector_tool_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rule_path = Path(tmp) / "IMP_998.yml"
            rule_path.write_text(
                textwrap.dedent(
                    """
                    id: "IMP_998"
                    lvl: "M"
                    sev: "M"
                    cat: "IMP"
                    lang: ["*"]
                    state: "P"
                    met: {"type": "example", "expr": {"enabled": true}}
                    det: [{"tool": "unknown", "rule": "example"}]
                    act: "FIX"
                    gate: {"detector": "example", "enforcement": "block"}
                    rat: "example -> impact ; #example"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuleValidationError, "not registered"):
                load_rule(rule_path)

    def test_invalid_gate_enforcement_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rule_path = Path(tmp) / "IMP_998.yml"
            rule_path.write_text(
                textwrap.dedent(
                    """
                    id: "IMP_998"
                    lvl: "M"
                    sev: "M"
                    cat: "IMP"
                    lang: ["*"]
                    state: "P"
                    met: {"type": "example", "expr": {"enabled": true}}
                    det: [{"tool": "sa", "rule": "example"}]
                    act: "FIX"
                    gate: {"detector": "example", "enforcement": "silent"}
                    rat: "example -> impact ; #example"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuleValidationError, "gate.enforcement"):
                load_rule(rule_path)

    def test_invalid_complexity_threshold_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rule_path = Path(tmp) / "IMP_007.yml"
            source = (RULES_DIR / "IMP_007.yml").read_text(encoding="utf-8")
            rule_path.write_text(
                source.replace('"threshold": 10', '"threshold": 0'),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuleValidationError, "positive integer"):
                load_rule(rule_path)


if __name__ == "__main__":
    unittest.main()
