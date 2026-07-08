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


if __name__ == "__main__":
    unittest.main()
