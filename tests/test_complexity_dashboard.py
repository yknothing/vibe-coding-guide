from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.complexity_dashboard import build_dashboard, parse_context_log, parse_defect_log


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "complexity_dashboard.py"


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=True)


def commit(repo: Path, message: str) -> str:
    run(["git", "add", "."], repo)
    result = run(["git", "commit", "-m", message], repo)
    return result.stdout


def write_file(repo: Path, relative_path: str, content: str) -> None:
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def make_repo() -> tuple[tempfile.TemporaryDirectory[str], Path, str]:
    tmp = tempfile.TemporaryDirectory()
    repo = Path(tmp.name)
    run(["git", "init"], repo)
    run(["git", "config", "user.email", "dashboard@example.com"], repo)
    run(["git", "config", "user.name", "Dashboard Test"], repo)
    write_file(repo, "README.md", "baseline\n")
    commit(repo, "baseline")
    base = run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    return tmp, repo, base


class ComplexityDashboardTests(unittest.TestCase):
    def test_change_amplification_groups_commits_by_logical_change_id(self) -> None:
        tmp, repo, base = make_repo()
        with tmp:
            write_file(repo, "app/auth.py", "POLICY = 'strict'\n")
            write_file(repo, "app/user.py", "ROLE = 'admin'\n")
            commit(repo, "issue: AUTH-1 add auth policy")
            write_file(repo, "app/auth.py", "POLICY = 'stricter'\n")
            commit(repo, "issue: AUTH-1 tune auth policy")
            write_file(repo, "billing/invoice.py", "TOTAL_FIELD = 'total'\n")
            commit(repo, "spec=BILL-2 add invoice")

            report = build_dashboard(repo=repo, since=base)

        amplification = report["change_amplification"]
        self.assertEqual(amplification["logical_change_count"], 2)
        self.assertEqual(amplification["ungrouped_commit_count"], 0)
        self.assertEqual(amplification["average_files_per_logical_change"], 1.5)
        self.assertEqual(amplification["max_files_per_logical_change"], 2)
        self.assertEqual(amplification["average_modules_per_logical_change"], 1.0)
        self.assertEqual(
            amplification["logical_changes"]["AUTH-1"]["files"],
            ["app/auth.py", "app/user.py"],
        )
        self.assertEqual(amplification["top_changed_files"][0], ["app/auth.py", 2])
        self.assertIn(["app/auth.py", "app/user.py", 1], amplification["top_cochange_pairs"])

    def test_context_footprint_counts_reads_without_turning_them_into_quality_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "context.jsonl"
            log.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "path": "app/auth.py",
                                "bytes": 1200,
                                "tokens": 300,
                                "source": "read_file",
                            }
                        ),
                        json.dumps(
                            {
                                "path": "app/user.py",
                                "bytes": 800,
                                "tokens": 200,
                                "source": "rg",
                            }
                        ),
                        json.dumps(
                            {
                                "path": "app/auth.py",
                                "bytes": 100,
                                "tokens": 25,
                                "source": "read_file",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            footprint = parse_context_log(log)

        self.assertEqual(footprint["status"], "present")
        self.assertEqual(footprint["read_count"], 3)
        self.assertEqual(footprint["unique_file_count"], 2)
        self.assertEqual(footprint["total_bytes"], 2100)
        self.assertEqual(footprint["total_tokens"], 525)
        self.assertEqual(footprint["source_counts"], {"read_file": 2, "rg": 1})
        self.assertIn("not a standalone quality score", footprint["interpretation"])

    def test_defect_log_tracks_unknown_sources_and_recent_change_overlap(self) -> None:
        tmp, repo, base = make_repo()
        with tmp:
            write_file(repo, "app/auth.py", "POLICY = 'strict'\n")
            commit(repo, "issue: AUTH-1 add auth policy")
            defects = repo / "defects.jsonl"
            defects.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "id": "D-1",
                                "files": ["app/auth.py"],
                                "source": "production",
                            }
                        ),
                        json.dumps({"id": "D-2", "files": ["docs/guide.md"]}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            changed_files = set(build_dashboard(repo=repo, since=base)["change_amplification"]["changed_files"])

            correlation = parse_defect_log(defects, changed_files)

        self.assertEqual(correlation["status"], "present")
        self.assertEqual(correlation["defect_count"], 2)
        self.assertEqual(correlation["unknown_source_count"], 1)
        self.assertEqual(correlation["source_counts"], {"production": 1, "unknown": 1})
        self.assertEqual(correlation["overlap_recent_changed_file_count"], 1)
        self.assertEqual(correlation["defects_overlapping_recent_changes"], ["D-1"])

    def test_json_array_non_object_records_remain_visible_as_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            defects = Path(tmp) / "defects.json"
            defects.write_text(
                json.dumps(
                    [
                        {"id": "D-1", "files": ["app/auth.py"]},
                        "not-a-record",
                    ]
                ),
                encoding="utf-8",
            )

            correlation = parse_defect_log(defects, {"app/auth.py"})

        self.assertEqual(correlation["defect_count"], 1)
        self.assertEqual(correlation["malformed_record_count"], 1)

    def test_cli_emits_json_report_for_harness_consumption(self) -> None:
        tmp, repo, base = make_repo()
        with tmp:
            write_file(repo, "app/auth.py", "POLICY = 'strict'\n")
            commit(repo, "issue: AUTH-1 add auth policy")

            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--repo",
                    str(repo),
                    "--since",
                    base,
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema_version"], "complexity-dashboard/v1")
        self.assertEqual(report["git_range"]["since"], base)
        self.assertIn("change_amplification", report)
        self.assertIn("context_footprint", report)
        self.assertIn("escaped_defect_correlation", report)


if __name__ == "__main__":
    unittest.main()
