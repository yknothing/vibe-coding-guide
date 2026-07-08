from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tools.change_probe import build_probe_report


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "change_probe.py"


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=True)


def write_file(repo: Path, relative_path: str, content: str) -> None:
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def commit(repo: Path, message: str) -> None:
    run(["git", "add", "."], repo)
    run(["git", "commit", "-m", message], repo)


def make_repo() -> tuple[tempfile.TemporaryDirectory[str], Path, str]:
    tmp = tempfile.TemporaryDirectory()
    repo = Path(tmp.name)
    run(["git", "init"], repo)
    run(["git", "config", "user.email", "probe@example.com"], repo)
    run(["git", "config", "user.name", "Probe Test"], repo)
    write_file(
        repo,
        "service/api.py",
        textwrap.dedent(
            """
            def get_user(user_id):
                return user_id
            """
        ).strip()
        + "\n",
    )
    write_file(repo, "storage/repo.py", "DEFAULT_TABLE = 'users'\n")
    commit(repo, "baseline")
    base = run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    return tmp, repo, base


class ChangeProbeTests(unittest.TestCase):
    def test_probe_report_scores_blast_radius_from_git_diff(self) -> None:
        tmp, repo, base = make_repo()
        with tmp:
            write_file(
                repo,
                "service/api.py",
                textwrap.dedent(
                    """
                    def get_user(user_id, include_deleted=False):
                        return user_id
                    """
                ).strip()
                + "\n",
            )
            write_file(repo, "storage/repo.py", "DEFAULT_TABLE = 'users_v2'\n")
            commit(repo, "probe: include deleted users")

            report = build_probe_report(repo=repo, base=base, head="HEAD", scenario_id="APOSD05-A")

        blast_radius = report["blast_radius"]
        self.assertEqual(report["schema_version"], "change-probe/v1")
        self.assertEqual(report["scenario_id"], "APOSD05-A")
        self.assertEqual(blast_radius["touched_file_count"], 2)
        self.assertEqual(blast_radius["touched_module_count"], 2)
        self.assertEqual(blast_radius["modules"], ["service", "storage"])
        self.assertEqual(blast_radius["interface_signature_change_count"], 1)
        self.assertEqual(blast_radius["interface_signature_changes"][0]["symbol"], "get_user")

    def test_cli_emits_json_probe_report(self) -> None:
        tmp, repo, base = make_repo()
        with tmp:
            write_file(
                repo,
                "service/api.py",
                textwrap.dedent(
                    """
                    def get_user(user_id, include_deleted=False):
                        return user_id
                    """
                ).strip()
                + "\n",
            )
            commit(repo, "probe: include deleted users")

            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--repo",
                    str(repo),
                    "--base",
                    base,
                    "--head",
                    "HEAD",
                    "--scenario-id",
                    "APOSD05-A",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], "change-probe/v1")
        self.assertEqual(payload["git_range"]["base"], base)


if __name__ == "__main__":
    unittest.main()
