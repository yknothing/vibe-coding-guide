from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "post_tool_use_quality_gate.py"
RULES_DIR = ROOT / "rules"


def make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def load_hook_module():
    spec = importlib.util.spec_from_file_location("post_tool_use_quality_gate", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PostToolUseQualityGateTests(unittest.TestCase):
    def run_hook(
        self,
        workspace: Path,
        payload: dict[str, object],
        *args: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(HOOK), "--hook", *args]
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        return subprocess.run(
            command,
            input=json.dumps(payload),
            cwd=workspace,
            env=full_env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_hook_payload_reports_magic_value_and_complexity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "bad.py"
            target.write_text(
                textwrap.dedent(
                    """
                    def route(status, retries, region):
                        if status == 2:
                            return "retry"
                        if retries > 3:
                            return "escalate"
                        if region == 4:
                            return "manual"
                        if status == 5:
                            return "fail"
                        return "ok"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "cwd": str(workspace),
                "tool_input": {"file_path": "bad.py"},
            }

            result = self.run_hook(workspace, payload, "--complexity-threshold", "4")

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("IMP_004", result.stderr)
            self.assertIn("IMP_007", result.stderr)
            self.assertIn("bad.py", result.stderr)

    def test_clean_constants_pass_without_external_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "clean.py"
            target.write_text(
                textwrap.dedent(
                    """
                    MAX_RETRIES = 3

                    def should_retry(retries):
                        return retries <= MAX_RETRIES
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Write",
                "cwd": str(workspace),
                "tool_input": {"file_path": "clean.py"},
            }

            result = self.run_hook(workspace, payload)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")

    def test_suppression_token_allows_intentional_magic_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "suppressed.py"
            target.write_text(
                textwrap.dedent(
                    """
                    def no_content_status():
                        # ALLOW_MAGIC_NUMBER: HTTP 204 protocol status, VCG-1
                        return 204
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "cwd": str(workspace),
                "tool_input": {"file_path": "suppressed.py"},
            }

            result = self.run_hook(workspace, payload)

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_hardcoded_url_literal_reports_configuration_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "endpoint.py"
            target.write_text(
                'def endpoint():\n    return "http://localhost:3000/v1"\n',
                encoding="utf-8",
            )
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Write",
                "cwd": str(workspace),
                "tool_input": {"file_path": "endpoint.py"},
            }

            result = self.run_hook(workspace, payload)

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("MNT_001", result.stderr)
            self.assertIn("endpoint.py", result.stderr)

    def test_constant_defined_hardcoded_url_still_reports_configuration_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "settings.py"
            target.write_text('API_URL = "http://localhost:3000/v1"\n', encoding="utf-8")
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Write",
                "cwd": str(workspace),
                "tool_input": {"file_path": "settings.py"},
            }

            result = self.run_hook(workspace, payload)

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("MNT_001", result.stderr)
            self.assertIn("settings.py", result.stderr)

    def test_allow_magic_number_does_not_suppress_hardcoded_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "settings.py"
            target.write_text(
                '# ALLOW_MAGIC_NUMBER: protocol status, VCG-1\nAPI_URL = "http://localhost:3000/v1"\n',
                encoding="utf-8",
            )
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Write",
                "cwd": str(workspace),
                "tool_input": {"file_path": "settings.py"},
            }

            result = self.run_hook(workspace, payload)

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("MNT_001", result.stderr)
            self.assertIn("settings.py", result.stderr)

    def test_multiedit_payload_can_report_multiple_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            first = workspace / "first.py"
            second = workspace / "second.js"
            first.write_text("def retry(value):\n    return value > 3\n", encoding="utf-8")
            second.write_text("setTimeout(run, 5000)\n", encoding="utf-8")
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "MultiEdit",
                "cwd": str(workspace),
                "tool_input": {
                    "edits": [
                        {"file_path": "first.py"},
                        {"file_path": "second.js"},
                    ]
                },
            }

            result = self.run_hook(workspace, payload)

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("first.py", result.stderr)
            self.assertIn("second.js", result.stderr)

    def test_json_output_uses_issue_schema_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "bad.py"
            target.write_text("def limit(value):\n    return value > 10\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(HOOK), "--format", "json", "--files", str(target)],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            payload = json.loads(result.stdout)
            for field in [
                "schema_version",
                "gate",
                "status",
                "rule_version",
                "timestamp",
                "root",
                "scanned_files",
                "skipped_files",
                "rules_loaded",
                "issues",
                "tool_errors",
                "summary",
            ]:
                self.assertIn(field, payload)
            self.assertEqual(payload["gate"], "post_tool_use_quality_gate")
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(payload["scanned_files"], ["bad.py"])
            self.assertEqual(set(payload["rules_loaded"]), {"IMP_004", "IMP_007", "MNT_001"})
            self.assertEqual(payload["summary"]["issue_count"], len(payload["issues"]))
            self.assertGreaterEqual(len(payload["issues"]), 1)
            issue = payload["issues"][0]
            for field in [
                "rule_id",
                "severity",
                "category",
                "file_path",
                "start_line",
                "end_line",
                "message",
                "detailed_explanation",
                "suggested_action",
                "rule_version",
                "scan_timestamp",
            ]:
                self.assertIn(field, issue)
            self.assertEqual(issue["severity"], "M")

    def test_json_max_issues_does_not_truncate_structured_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "many.py"
            target.write_text(
                "def values(a):\n"
                "    first = a > 2\n"
                "    second = a > 3\n"
                "    return first or second\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--format",
                    "json",
                    "--max-issues",
                    "1",
                    "--files",
                    str(target),
                ],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            payload = json.loads(result.stdout)
            self.assertGreater(len(payload["issues"]), 1)
            self.assertEqual(payload["summary"]["issue_count"], len(payload["issues"]))

    def test_hook_json_output_uses_rule_metadata_for_complexity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "complex.py"
            target.write_text(
                textwrap.dedent(
                    """
                    def route(status, retries, region):
                        if status == 2:
                            return "retry"
                        if retries > 3:
                            return "escalate"
                        if region == 4:
                            return "manual"
                        if status == 5:
                            return "fail"
                        return "ok"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "cwd": str(workspace),
                "tool_input": {"file_path": "complex.py"},
            }

            result = self.run_hook(
                workspace,
                payload,
                "--format",
                "json",
                "--complexity-threshold",
                "4",
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "fail")
            complexity_issue = next(issue for issue in report["issues"] if issue["rule_id"] == "IMP_007")
            self.assertEqual(complexity_issue["severity"], "H")
            self.assertEqual(complexity_issue["suggested_action"], "RCM")
            self.assertEqual(result.stderr, "")

    def test_hook_uses_rules_dir_metadata_instead_of_hardcoded_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            rules_dir = workspace / "rules"
            shutil.copytree(RULES_DIR, rules_dir)
            imp_007 = rules_dir / "IMP_007.yml"
            imp_007.write_text(
                imp_007.read_text(encoding="utf-8").replace('sev: "H"', 'sev: "B"'),
                encoding="utf-8",
            )
            target = workspace / "complex.py"
            target.write_text(
                textwrap.dedent(
                    """
                    def route(status, retries, region):
                        if status == 2:
                            return "retry"
                        if retries > 3:
                            return "escalate"
                        if region == 4:
                            return "manual"
                        if status == 5:
                            return "fail"
                        return "ok"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "cwd": str(workspace),
                "tool_input": {"file_path": "complex.py"},
            }

            result = self.run_hook(
                workspace,
                payload,
                "--format",
                "json",
                "--complexity-threshold",
                "4",
                "--rules-dir",
                str(rules_dir),
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads(result.stdout)
            complexity_issue = next(issue for issue in report["issues"] if issue["rule_id"] == "IMP_007")
            self.assertEqual(complexity_issue["severity"], "B")

    def test_require_tools_fails_closed_when_required_detector_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "bad.py"
            target.write_text("def limit(value):\n    return value > 10\n", encoding="utf-8")
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "cwd": str(workspace),
                "tool_input": {"file_path": "bad.py"},
            }

            result = self.run_hook(
                workspace,
                payload,
                "--require-tools",
                env={"PATH": "/nonexistent"},
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("Quality gate setup failed", result.stderr)
            self.assertIn("ruff", result.stderr)

    def test_require_tools_fails_closed_on_malformed_lizard_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.py"
            target.write_text("MAX_RETRIES = 3\n", encoding="utf-8")
            make_executable(
                bin_dir / "ruff",
                "#!/bin/sh\nprintf '%s\\n' '[]'\n",
            )
            make_executable(
                bin_dir / "eslint",
                "#!/bin/sh\nprintf '%s\\n' '[]'\n",
            )
            make_executable(
                bin_dir / "lizard",
                "#!/bin/sh\nprintf '%s\\n' 'not,a,lizard,csv'\n",
            )
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "cwd": str(workspace),
                "tool_input": {"file_path": "clean.py"},
            }

            result = self.run_hook(
                workspace,
                payload,
                "--format",
                "json",
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 2, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertEqual(report["tool_errors"][0]["tool"], "lizard")
            self.assertEqual(result.stderr, "")

    def test_unsupported_file_is_reported_as_skipped_in_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "README.md"
            target.write_text("port 3000\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(HOOK), "--format", "json", "--files", str(target)],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["skipped_files"][0]["path"], "README.md")
            self.assertEqual(report["skipped_files"][0]["reason"], "unsupported_extension")

    def test_external_tool_outputs_are_parsed_in_require_tools_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "bad.py"
            target.write_text("def limit(value):\n    return value > 10\n", encoding="utf-8")
            make_executable(
                bin_dir / "ruff",
                "#!/bin/sh\n"
                "printf '%s\\n' '[{\"code\":\"PLR2004\",\"filename\":\"bad.py\",\"location\":{\"row\":2},\"message\":\"ruff magic\"}]'\n"
                "exit 1\n",
            )
            make_executable(
                bin_dir / "eslint",
                "#!/bin/sh\nprintf '%s\\n' '[]'\n",
            )
            make_executable(
                bin_dir / "lizard",
                "#!/bin/sh\n"
                "printf '%s\\n' 'NLOC,CCN,token,PARAM,length,location,file,function'\n"
                "printf '%s\\n' '4,12,20,1,4,1:1,bad.py,limit'\n",
            )
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "cwd": str(workspace),
                "tool_input": {"file_path": "bad.py"},
            }

            result = self.run_hook(
                workspace,
                payload,
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn("Quality gate setup failed", result.stderr)
            self.assertIn("ruff magic", result.stderr)
            self.assertIn("IMP_007", result.stderr)

    def test_require_tools_fails_closed_on_detector_nonzero_even_with_parseable_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.py"
            target.write_text("MAX_RETRIES = 3\n", encoding="utf-8")
            make_executable(
                bin_dir / "ruff",
                "#!/bin/sh\nprintf '%s\\n' '[]'\nexit 2\n",
            )
            make_executable(
                bin_dir / "eslint",
                "#!/bin/sh\nprintf '%s\\n' '[]'\n",
            )
            make_executable(
                bin_dir / "lizard",
                "#!/bin/sh\nprintf '%s\\n' 'NLOC,CCN,token,PARAM,length,location,file,function'\n",
            )
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "cwd": str(workspace),
                "tool_input": {"file_path": "clean.py"},
            }

            result = self.run_hook(
                workspace,
                payload,
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("Quality gate setup failed", result.stderr)
            self.assertIn("ruff", result.stderr)

    def test_hook_input_without_file_path_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "cwd": str(workspace),
                "tool_input": {"content": "def f(): return 2"},
            }

            result = self.run_hook(workspace, payload)

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("did not include a file path", result.stderr)

    def test_python_complexity_does_not_count_nested_function_in_parent(self) -> None:
        module = load_hook_module()
        source = textwrap.dedent(
            """
            def outer(flag):
                def inner(value):
                    if value:
                        return 1
                    if flag:
                        return 2
                    return 3
                return inner(flag)
            """
        )
        tree = compile(source, "<test>", "exec", flags=module.ast.PyCF_ONLY_AST)
        outer = tree.body[0]

        self.assertEqual(module.python_cyclomatic_complexity(outer), 1)


if __name__ == "__main__":
    unittest.main()
