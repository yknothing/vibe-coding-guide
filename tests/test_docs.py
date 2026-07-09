from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_readme_links_ide_neutral_adapter_matrix(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("docs/ADAPTERS.md", readme)
        self.assertIn("IDE-neutral", readme)
        self.assertIn("Generic CLI fallback", readme)
        self.assertIn("native adapter 仍是 planned", readme)

    def test_adapter_matrix_names_target_status_levels(self) -> None:
        adapters = (ROOT / "docs" / "ADAPTERS.md").read_text(encoding="utf-8")

        for target in ["Generic CLI", "Claude Code", "Codex", "Cursor", "Qoder", "Trae", "Droid"]:
            self.assertIn(target, adapters)
        for status in ["planned", "unsupported", "documented", "smoke-tested", "dogfooded"]:
            self.assertIn(status, adapters)
        for field in ["cwd", "files", "event_source", "baseline_path", "strict"]:
            self.assertIn(field, adapters)

    def test_install_docs_explain_detector_tools_and_safe_commands(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        hook_readme = (ROOT / "hooks" / "README.md").read_text(encoding="utf-8")
        adapters = (ROOT / "docs" / "ADAPTERS.md").read_text(encoding="utf-8")
        combined = "\n".join([readme, hook_readme, adapters])

        for detector in ["ruff", "eslint", "lizard"]:
            self.assertIn(detector, combined)
        self.assertIn("Fast Python linter", combined)
        self.assertIn("JavaScript and TypeScript linter", combined)
        self.assertIn("Cyclomatic complexity analyzer", combined)
        self.assertIn("python3 -m pip install --upgrade ruff lizard", combined)
        self.assertIn("npm install -g eslint", combined)
        self.assertIn("Do not use `curl | sh`", combined)
        self.assertIn("不得静默执行", combined)
        self.assertIn("--doctor --require-tools", combined)

    def test_adapter_docs_keep_doctor_install_fields_out_of_scan_report_contract(self) -> None:
        adapters = (ROOT / "docs" / "ADAPTERS.md").read_text(encoding="utf-8")

        self.assertIn("Doctor 输出契约", adapters)
        self.assertIn("doctor-only", adapters)
        scan_contract = adapters.split("## Core 输出契约", maxsplit=1)[1].split(
            "## 能力矩阵",
            maxsplit=1,
        )[0]
        self.assertNotIn("`tool_catalog`", scan_contract)
        self.assertNotIn("`install_plan`", scan_contract)
        self.assertNotIn("`quick_install_commands`", scan_contract)

    def test_docs_explain_profile_scoped_detector_truth(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        hook_readme = (ROOT / "hooks" / "README.md").read_text(encoding="utf-8")
        adapters = (ROOT / "docs" / "ADAPTERS.md").read_text(encoding="utf-8")
        combined = "\n".join([readme, hook_readme, adapters])

        self.assertIn("detectors.<name>.run", combined)
        self.assertIn("not_applicable", combined)
        self.assertIn("profile-scoped", combined)
        self.assertIn("TypeScript ignored", combined)
        self.assertIn("uncovered_files", combined)


if __name__ == "__main__":
    unittest.main()
