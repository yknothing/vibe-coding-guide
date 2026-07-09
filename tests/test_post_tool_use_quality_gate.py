from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "post_tool_use_quality_gate.py"
RULES_DIR = ROOT / "rules"


def make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def lizard_script(files: list[Path], csv_output: str = "") -> str:
    file_items = "".join(f'<item name="{path}" />' for path in files)
    xml_output = (
        '<cppncss><measure type="Function" />'
        f'<measure type="File">{file_items}</measure></cppncss>'
    )
    csv_command = (
        f"printf '%s\\n' {shlex.quote(csv_output)}\n" if csv_output else ":\n"
    )
    return (
        "#!/bin/sh\n"
        'if [ "$1" = "--xml" ]; then\n'
        f"  printf '%s\\n' {shlex.quote(xml_output)}\n"
        "else\n"
        f"  {csv_command}"
        "fi\n"
    )


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
        payload: object,
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

    def test_hook_and_files_conflict_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "clean.py"
            target.write_text('APP_NAME = "demo"\n', encoding="utf-8")
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
                "--files",
                str(target),
                env={"PATH": "/nonexistent"},
            )

            self.assertEqual(result.returncode, 2, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("hook-input", {error["tool"] for error in report["tool_errors"]})
            self.assertEqual(report["source"]["mode"], "invalid")

    def test_non_object_hook_json_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)

            result = self.run_hook(
                workspace,
                [],
                "--format",
                "json",
                env={"PATH": "/nonexistent"},
            )

            self.assertEqual(result.returncode, 2, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("hook-input", {error["tool"] for error in report["tool_errors"]})

    def test_invalid_hook_cwd_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "cwd": [],
                "tool_input": {"file_path": "clean.py"},
            }

            result = self.run_hook(
                workspace,
                payload,
                "--format",
                "json",
                env={"PATH": "/nonexistent"},
            )

            self.assertEqual(result.returncode, 2, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("hook-input", {error["tool"] for error in report["tool_errors"]})

    def test_invalid_hook_tool_name_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": [],
                "cwd": str(workspace),
                "tool_input": {},
            }

            result = self.run_hook(
                workspace,
                payload,
                "--format",
                "json",
                env={"PATH": "/nonexistent"},
            )

            self.assertEqual(result.returncode, 2, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("hook-input", {error["tool"] for error in report["tool_errors"]})

    def test_request_root_precedence_is_explicit_env_event_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve()
            explicit_root = workspace / "explicit"
            env_root = workspace / "env"
            event_root = workspace / "event"
            process_root = workspace / "process"
            module = load_hook_module()
            event = {"cwd": str(event_root)}

            explicit_args = module.parse_args(
                ["--hook", "--root", str(explicit_root)]
            )
            env_args = module.parse_args(["--hook"])
            with mock.patch.dict(
                os.environ, {"CLAUDE_PROJECT_DIR": str(env_root)}, clear=False
            ):
                explicit_request, _ = module.build_quality_gate_request(
                    explicit_args, event, process_root
                )
                env_request, _ = module.build_quality_gate_request(
                    env_args, event, process_root
                )
            with mock.patch.dict(os.environ, {}, clear=True):
                event_request, _ = module.build_quality_gate_request(
                    env_args, event, process_root
                )
                process_request, _ = module.build_quality_gate_request(
                    env_args, {}, process_root
                )

            self.assertEqual(explicit_request.root, explicit_root)
            self.assertEqual(env_request.root, env_root)
            self.assertEqual(event_request.root, event_root)
            self.assertEqual(process_request.root, process_root)

    def test_relative_baseline_resolves_from_explicit_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            launch_dir = workspace / "launch"
            launch_dir.mkdir()
            target = workspace / "clean.py"
            target.write_text('APP_NAME = "demo"\n', encoding="utf-8")
            baseline = workspace / "baseline.json"
            baseline.write_text(
                json.dumps(
                    {
                        "metrics": {
                            "files": {
                                "clean.py": {
                                    "magic_literal_count": 0,
                                    "hardcoded_endpoint_count": 0,
                                    "python_max_cyclomatic_complexity": 0,
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = self.run_files(
                workspace,
                [target],
                "--root",
                str(workspace),
                "--ratchet-baseline",
                "baseline.json",
                env={"PATH": "/nonexistent"},
                process_cwd=launch_dir,
            )

            self.assertEqual(result.returncode, 0, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["ratchet"]["status"], "pass")
            self.assertEqual(report["ratchet"]["baseline"], str(baseline.resolve()))

    def test_cli_and_claude_project_to_equivalent_execution_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve()
            module = load_hook_module()
            common_args = [
                "--root",
                str(workspace),
                "--ratchet-baseline",
                "baseline.json",
                "--complexity-threshold",
                "7",
                "--require-tools",
            ]
            cli_args = module.parse_args([*common_args, "--files", "clean.py"])
            hook_args = module.parse_args([*common_args, "--hook"])
            event = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "cwd": str(workspace),
                "tool_input": {"file_path": "clean.py"},
            }

            cli_request, cli_errors = module.build_quality_gate_request(
                cli_args, None, workspace
            )
            hook_request, hook_errors = module.build_quality_gate_request(
                hook_args, event, workspace
            )

            self.assertEqual(cli_errors, [])
            self.assertEqual(hook_errors, [])
            for field in [
                "schema_version",
                "root",
                "files",
                "baseline_path",
                "strict",
                "complexity_threshold",
            ]:
                self.assertEqual(getattr(cli_request, field), getattr(hook_request, field))
            self.assertEqual(cli_request.adapter, "generic-cli")
            self.assertEqual(hook_request.adapter, "claude-code-post-tool-use")

    def run_files(
        self,
        workspace: Path,
        files: list[Path],
        *args: str,
        env: dict[str, str] | None = None,
        process_cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        return subprocess.run(
            [
                sys.executable,
                str(HOOK),
                "--format",
                "json",
                *args,
                "--files",
                *[str(path) for path in files],
            ],
            cwd=process_cwd or workspace,
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

    def test_public_python_api_without_docstring_reports_documentation_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "api.py"
            target.write_text(
                textwrap.dedent(
                    """
                    __all__ = ["public_api"]

                    def public_api(value):
                        return value

                    def _private_helper(value):
                        return value
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(HOOK), "--format", "json", "--files", str(target)],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            payload = json.loads(result.stdout)
            doc_issues = [issue for issue in payload["issues"] if issue["rule_id"] == "MNT_002"]
            self.assertEqual(len(doc_issues), 1)
            self.assertEqual(doc_issues[0]["file_path"], "api.py")
            self.assertIn("public_api", doc_issues[0]["message"])

    def test_private_python_helper_without_docstring_passes_documentation_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "helpers.py"
            target.write_text(
                "def _private_helper(value):\n    return value\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(HOOK), "--format", "json", "--files", str(target)],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["issues"], [])

    def test_python_pass_through_method_reports_design_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "service.py"
            target.write_text(
                textwrap.dedent(
                    """
                    class UserService:
                        def __init__(self, repository):
                            self.repository = repository

                        def get_user(self, user_id):
                            return self.repository.get_user(user_id)
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(HOOK), "--format", "json", "--files", str(target)],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            payload = json.loads(result.stdout)
            design_issues = [issue for issue in payload["issues"] if issue["rule_id"] == "DSN_001"]
            self.assertEqual(len(design_issues), 1)
            self.assertIn("get_user", design_issues[0]["message"])

    def test_python_method_with_boundary_logic_is_not_pass_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "service.py"
            target.write_text(
                textwrap.dedent(
                    """
                    class UserService:
                        def __init__(self, repository):
                            self.repository = repository

                        def get_user(self, user_id):
                            if user_id is None:
                                return None
                            return self.repository.get_user(user_id)
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(HOOK), "--format", "json", "--files", str(target)],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["issues"], [])

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
                "run_id",
                "rule_version",
                "timestamp",
                "duration_ms",
                "root",
                "source",
                "detectors",
                "scanned_files",
                "skipped_files",
                "rules_loaded",
                "metrics",
                "ratchet",
                "issues",
                "tool_errors",
                "summary",
            ]:
                self.assertIn(field, payload)
            self.assertEqual(payload["gate"], "post_tool_use_quality_gate")
            self.assertEqual(payload["status"], "fail")
            self.assertIsInstance(payload["run_id"], str)
            self.assertGreater(len(payload["run_id"]), 10)
            self.assertIsInstance(payload["duration_ms"], int)
            self.assertGreaterEqual(payload["duration_ms"], 0)
            self.assertEqual(payload["source"]["mode"], "direct_files")
            self.assertIn("ruff", payload["detectors"])
            self.assertIn("lizard", payload["detectors"])
            self.assertEqual(payload["scanned_files"], ["bad.py"])
            self.assertEqual(
                set(payload["rules_loaded"]),
                {"DSN_001", "IMP_004", "IMP_007", "MNT_001", "MNT_002"},
            )
            self.assertEqual(payload["ratchet"]["status"], "not_configured")
            self.assertEqual(payload["summary"]["issue_count"], len(payload["issues"]))
            self.assertEqual(payload["summary"]["ratchet_violation_count"], 0)
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

    def test_scan_report_does_not_include_doctor_only_install_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "clean.py"
            target.write_text("MAX_RETRIES = 3\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(HOOK), "--format", "json", "--files", str(target)],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema_version"], "quality-gate-report/v1")
            self.assertNotIn("tool_catalog", payload)
            self.assertNotIn("install_plan", payload)
            self.assertNotIn("quick_install_commands", payload)
            for detector in payload["detectors"].values():
                self.assertNotIn("install", detector)

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

    def test_ratchet_baseline_fails_when_touched_file_complexity_regresses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "route.py"
            target.write_text(
                textwrap.dedent(
                    """
                    def route(status, retries):
                        if status:
                            return "retry"
                        if retries:
                            return "escalate"
                        return "ok"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            baseline = workspace / "baseline.json"
            baseline.write_text(
                json.dumps(
                    {
                        "schema_version": "quality-gate-report/v1",
                        "metrics": {
                            "files": {
                                "route.py": {
                                    "python_max_cyclomatic_complexity": 2,
                                    "python_total_cyclomatic_complexity": 2,
                                    "magic_literal_count": 0,
                                    "hardcoded_endpoint_count": 0,
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--format",
                    "json",
                    "--complexity-threshold",
                    "10",
                    "--ratchet-baseline",
                    str(baseline),
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
            self.assertEqual(payload["issues"], [])
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(payload["ratchet"]["status"], "fail")
            self.assertEqual(payload["summary"]["ratchet_violation_count"], 1)
            metrics = {violation["metric"] for violation in payload["ratchet"]["violations"]}
            self.assertEqual(metrics, {"python_max_cyclomatic_complexity"})

    def test_ratchet_allows_total_complexity_growth_when_max_complexity_does_not_regress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "steps.py"
            target.write_text(
                textwrap.dedent(
                    """
                    def first(flag):
                        if flag:
                            return "yes"
                        return "no"

                    def second(flag):
                        if flag:
                            return "yes"
                        return "no"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            baseline = workspace / "baseline.json"
            baseline.write_text(
                json.dumps(
                    {
                        "schema_version": "quality-gate-report/v1",
                        "metrics": {
                            "files": {
                                "steps.py": {
                                    "python_max_cyclomatic_complexity": 2,
                                    "python_total_cyclomatic_complexity": 2,
                                    "magic_literal_count": 0,
                                    "hardcoded_endpoint_count": 0,
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--format",
                    "json",
                    "--complexity-threshold",
                    "10",
                    "--ratchet-baseline",
                    str(baseline),
                    "--files",
                    str(target),
                ],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["ratchet"]["status"], "pass")
            self.assertEqual(payload["summary"]["ratchet_violation_count"], 0)

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

    def test_require_tools_accepts_lizard_zero_function_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.py"
            target.write_text('APP_NAME = "demo"\n', encoding="utf-8")
            make_executable(
                bin_dir / "ruff",
                "#!/bin/sh\nprintf '%s\\n' '[]'\n",
            )
            make_executable(
                bin_dir / "lizard",
                lizard_script([target]),
            )

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["tool_errors"], [])
            self.assertEqual(report["detectors"]["lizard"]["run"]["status"], "succeeded")
            self.assertEqual(report["detectors"]["lizard"]["run"]["coverage"], "complete")

    def test_require_tools_ignores_irrelevant_eslint_for_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.py"
            target.write_text("def identity(value):\n    return value\n", encoding="utf-8")
            make_executable(bin_dir / "ruff", "#!/bin/sh\nprintf '%s\\n' '[]'\n")
            make_executable(
                bin_dir / "lizard",
                "#!/bin/sh\n"
                "printf '%s\\n' '2,1,8,1,2,1:1,clean.py,identity'\n",
            )

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "pass")
            self.assertFalse(report["detectors"]["eslint"]["available"])
            self.assertEqual(report["detectors"]["eslint"]["run"]["status"], "not_applicable")

    def test_non_strict_lizard_failure_uses_visible_python_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "complex.py"
            target.write_text(
                "def route(flag):\n"
                + "    if flag: flag = not flag\n" * 11
                + "    return flag\n",
                encoding="utf-8",
            )
            make_executable(bin_dir / "lizard", "#!/bin/sh\nprintf '%s\\n' 'malformed'\n")

            result = self.run_files(
                workspace,
                [target],
                "--complexity-threshold",
                "10",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "fail")
            self.assertIn("IMP_007", {issue["rule_id"] for issue in report["issues"]})
            self.assertEqual(report["detectors"]["lizard"]["run"]["status"], "failed")
            self.assertEqual(report["detectors"]["lizard"]["run"]["coverage"], "fallback")
            self.assertEqual(report["detectors"]["lizard"]["run"]["fallback"], "python_ast")

    def test_strict_lizard_failure_retains_error_and_fallback_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "complex.py"
            target.write_text(
                "def route(flag):\n"
                + "    if flag: flag = not flag\n" * 11
                + "    return flag\n",
                encoding="utf-8",
            )
            make_executable(bin_dir / "ruff", "#!/bin/sh\nprintf '%s\\n' '[]'\n")
            make_executable(bin_dir / "lizard", "#!/bin/sh\nprintf '%s\\n' 'malformed'\n")

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                "--complexity-threshold",
                "10",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("lizard", {error["tool"] for error in report["tool_errors"]})
            self.assertIn("IMP_007", {issue["rule_id"] for issue in report["issues"]})
            self.assertEqual(report["detectors"]["lizard"]["run"]["coverage"], "fallback")

    def test_eslint_ignored_typescript_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "typed.ts"
            target.write_text(
                "export function identity(value: string): string { return value; }\n",
                encoding="utf-8",
            )
            eslint_payload = json.dumps(
                [
                    {
                        "filePath": str(target),
                        "messages": [
                            {
                                "ruleId": None,
                                "severity": 1,
                                "message": "File ignored because no matching configuration was supplied.",
                            }
                        ],
                    }
                ]
            )
            make_executable(
                bin_dir / "eslint",
                f"#!/bin/sh\nprintf '%s\\n' '{eslint_payload}'\n",
            )
            make_executable(
                bin_dir / "lizard",
                "#!/bin/sh\n"
                "printf '%s\\n' '1,1,8,1,1,1:1,typed.ts,identity'\n",
            )

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("eslint", {error["tool"] for error in report["tool_errors"]})
            self.assertEqual(report["detectors"]["eslint"]["run"]["status"], "ignored")
            eslint_error = next(
                error["message"] for error in report["tool_errors"] if error["tool"] == "eslint"
            )
            self.assertIn("ignored", eslint_error)

    def test_eslint_reports_the_latest_variant_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "typed.ts"
            target.write_text("export const label: string = 'ok';\n", encoding="utf-8")
            ignored_payload = json.dumps(
                [
                    {
                        "filePath": str(target),
                        "messages": [
                            {
                                "ruleId": None,
                                "message": "File ignored by the first variant.",
                            }
                        ],
                    }
                ]
            )
            make_executable(
                bin_dir / "eslint",
                "#!/bin/sh\n"
                'case " $* " in\n'
                f"  *' --no-config-lookup '*) printf '%s\\n' '{ignored_payload}' ;;\n"
                "  *) printf '%s\\n' 'second variant failed' >&2; exit 2 ;;\n"
                "esac\n",
            )
            make_executable(bin_dir / "lizard", lizard_script([target]))

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            eslint_run = report["detectors"]["eslint"]["run"]
            self.assertEqual(eslint_run["status"], "failed")
            self.assertIn("second variant failed", eslint_run["message"])

    def test_eslint_runs_from_explicit_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            launch_dir = workspace / "launch"
            bin_dir = workspace / "bin"
            launch_dir.mkdir()
            bin_dir.mkdir()
            resolved_workspace = workspace.resolve()
            target = workspace / "bad.js"
            target.write_text("export function timeout() { return 5000; }\n", encoding="utf-8")
            eslint_issue = json.dumps(
                [
                    {
                        "filePath": "bad.js",
                        "messages": [
                            {
                                "ruleId": "no-magic-numbers",
                                "severity": 2,
                                "line": 1,
                                "message": "No magic number: 5000.",
                            }
                        ],
                    }
                ]
            )
            eslint_ignored = json.dumps(
                [
                    {
                        "filePath": str(target),
                        "messages": [
                            {
                                "ruleId": None,
                                "severity": 1,
                                "message": "File ignored because cwd did not match the project root.",
                            }
                        ],
                    }
                ]
            )
            make_executable(
                bin_dir / "eslint",
                "#!/bin/sh\n"
                f"if [ \"$PWD\" = \"{resolved_workspace}\" ]; then\n"
                f"  printf '%s\\n' '{eslint_issue}'\n"
                "else\n"
                f"  printf '%s\\n' '{eslint_ignored}'\n"
                "fi\n"
                "exit 1\n",
            )
            make_executable(
                bin_dir / "lizard",
                "#!/bin/sh\n"
                "printf '%s\\n' '1,1,8,1,1,1:1,bad.js,timeout'\n",
            )

            result = self.run_files(
                workspace,
                [target],
                "--root",
                str(resolved_workspace),
                "--require-tools",
                env={"PATH": str(bin_dir)},
                process_cwd=launch_dir,
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["tool_errors"], [])
            self.assertIn("IMP_004", {issue["rule_id"] for issue in report["issues"]})
            self.assertEqual(report["detectors"]["eslint"]["run"]["status"], "succeeded")
            eslint_issue_report = next(
                issue for issue in report["issues"] if issue["rule_id"] == "IMP_004"
            )
            self.assertEqual(eslint_issue_report["file_path"], "bad.js")

    def test_mixed_language_lizard_fallback_keeps_uncovered_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            python_target = workspace / "constants.py"
            javascript_target = workspace / "complex.js"
            python_target.write_text('APP_NAME = "demo"\n', encoding="utf-8")
            javascript_target.write_text(
                "export function route(flag) {\n"
                + "  if (flag) flag = !flag;\n" * 11
                + "  return flag;\n}\n",
                encoding="utf-8",
            )
            eslint_payload = json.dumps(
                [{"filePath": str(javascript_target), "messages": []}]
            )
            make_executable(
                bin_dir / "eslint",
                f"#!/bin/sh\nprintf '%s\\n' '{eslint_payload}'\n",
            )
            make_executable(bin_dir / "lizard", "#!/bin/sh\nprintf '%s\\n' 'malformed'\n")

            result = self.run_files(
                workspace,
                [python_target, javascript_target],
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("lizard", {error["tool"] for error in report["tool_errors"]})
            self.assertEqual(report["detectors"]["lizard"]["run"]["coverage"], "fallback")
            self.assertEqual(
                report["detectors"]["lizard"]["run"]["uncovered_files"],
                ["complex.js"],
            )

    def test_eslint_missing_requested_file_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            javascript_target = workspace / "clean.js"
            typescript_target = workspace / "typed.ts"
            javascript_target.write_text("export const label = 'ok';\n", encoding="utf-8")
            typescript_target.write_text("export const label: string = 'ok';\n", encoding="utf-8")
            eslint_payload = json.dumps(
                [{"filePath": str(javascript_target), "messages": []}]
            )
            make_executable(
                bin_dir / "eslint",
                f"#!/bin/sh\nprintf '%s\\n' '{eslint_payload}'\n",
            )
            make_executable(
                bin_dir / "lizard",
                lizard_script([javascript_target, typescript_target]),
            )

            result = self.run_files(
                workspace,
                [javascript_target, typescript_target],
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("typed.ts", report["detectors"]["eslint"]["run"]["message"])

    def test_malformed_ruff_location_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.py"
            target.write_text("def identity(value):\n    return value\n", encoding="utf-8")
            ruff_payload = json.dumps(
                [
                    {
                        "code": "PLR2004",
                        "filename": "clean.py",
                        "location": "invalid",
                        "message": "bad location",
                    }
                ]
            )
            make_executable(
                bin_dir / "ruff",
                f"#!/bin/sh\nprintf '%s\\n' '{ruff_payload}'\n",
            )
            make_executable(bin_dir / "lizard", lizard_script([target]))

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("ruff", {error["tool"] for error in report["tool_errors"]})

    def test_strict_ruff_nonzero_without_output_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.py"
            target.write_text('APP_NAME = "demo"\n', encoding="utf-8")
            make_executable(bin_dir / "ruff", "#!/bin/sh\nexit 1\n")
            make_executable(bin_dir / "lizard", lizard_script([target]))

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("ruff", {error["tool"] for error in report["tool_errors"]})

    def test_strict_ruff_zero_without_json_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.py"
            target.write_text('APP_NAME = "demo"\n', encoding="utf-8")
            make_executable(bin_dir / "ruff", "#!/bin/sh\nexit 0\n")
            make_executable(bin_dir / "lizard", lizard_script([target]))

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("ruff", {error["tool"] for error in report["tool_errors"]})

    def test_strict_ruff_exit_one_with_empty_json_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.py"
            target.write_text('APP_NAME = "demo"\n', encoding="utf-8")
            make_executable(bin_dir / "ruff", "#!/bin/sh\nprintf '[]\\n'\nexit 1\n")
            make_executable(bin_dir / "lizard", lizard_script([target]))

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("ruff", {error["tool"] for error in report["tool_errors"]})

    def test_detector_exec_format_error_is_structured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.py"
            target.write_text('APP_NAME = "demo"\n', encoding="utf-8")
            make_executable(bin_dir / "ruff", "not an executable format\n")
            make_executable(bin_dir / "lizard", lizard_script([target]))

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("ruff", {error["tool"] for error in report["tool_errors"]})

    def test_malformed_eslint_line_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "bad.js"
            target.write_text("export function timeout() { return 5000; }\n", encoding="utf-8")
            eslint_payload = json.dumps(
                [
                    {
                        "filePath": str(target),
                        "messages": [
                            {
                                "ruleId": "no-magic-numbers",
                                "line": "invalid",
                                "message": "bad line",
                            }
                        ],
                    }
                ]
            )
            make_executable(
                bin_dir / "eslint",
                f"#!/bin/sh\nprintf '%s\\n' '{eslint_payload}'\n",
            )
            make_executable(bin_dir / "lizard", lizard_script([target]))

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("eslint", {error["tool"] for error in report["tool_errors"]})

    def test_malformed_eslint_message_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.js"
            target.write_text("export const label = 'ok';\n", encoding="utf-8")
            eslint_payload = json.dumps(
                [{"filePath": str(target), "messages": ["malformed"]}]
            )
            make_executable(
                bin_dir / "eslint",
                f"#!/bin/sh\nprintf '%s\\n' '{eslint_payload}'\n",
            )
            make_executable(bin_dir / "lizard", lizard_script([target]))

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("eslint", {error["tool"] for error in report["tool_errors"]})

    def test_eslint_exit_one_without_diagnostics_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.js"
            target.write_text("export const LABEL = 'ok';\n", encoding="utf-8")
            eslint_payload = json.dumps([{"filePath": str(target), "messages": []}])
            make_executable(
                bin_dir / "eslint",
                f"#!/bin/sh\nprintf '%s\\n' '{eslint_payload}'\nexit 1\n",
            )
            make_executable(bin_dir / "lizard", lizard_script([target]))

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("eslint", {error["tool"] for error in report["tool_errors"]})

    def test_eslint_embedded_null_file_path_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.js"
            target.write_text("export const label = 'ok';\n", encoding="utf-8")
            eslint_payload = json.dumps([{"filePath": "\0", "messages": []}])
            make_executable(
                bin_dir / "eslint",
                f"#!/bin/sh\nprintf '%s\\n' '{eslint_payload}'\n",
            )
            make_executable(bin_dir / "lizard", lizard_script([target]))

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("eslint", {error["tool"] for error in report["tool_errors"]})

    def test_malformed_lizard_ccn_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.py"
            target.write_text('APP_NAME = "demo"\n', encoding="utf-8")
            make_executable(bin_dir / "ruff", "#!/bin/sh\nprintf '%s\\n' '[]'\n")
            make_executable(
                bin_dir / "lizard",
                "#!/bin/sh\nprintf '%s\\n' '1,invalid,8,1,1,1:1,clean.py,dummy'\n",
            )

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("lizard", {error["tool"] for error in report["tool_errors"]})

    def test_lizard_unrequested_file_result_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "high.go"
            target.write_text(
                "package demo\nfunc route(flag bool) bool {\n"
                + "  if flag { flag = !flag }\n" * 11
                + "  return flag\n}\n",
                encoding="utf-8",
            )
            make_executable(
                bin_dir / "lizard",
                lizard_script(
                    [target],
                    "1,1,8,1,1,1:1,other.go,other",
                ),
            )

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("lizard", {error["tool"] for error in report["tool_errors"]})

    def test_unreadable_python_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "unreadable.py"
            target.write_text('APP_NAME = "demo"\n', encoding="utf-8")
            target.chmod(0)
            try:
                result = self.run_files(
                    workspace,
                    [target],
                    env={"PATH": "/nonexistent"},
                )
            finally:
                target.chmod(0o600)

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("python-ast", {error["tool"] for error in report["tool_errors"]})

    def test_non_utf8_javascript_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "invalid.js"
            target.write_bytes(b"export const value = '\xff';\n")

            result = self.run_files(
                workspace,
                [target],
                env={"PATH": "/nonexistent"},
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("source-read", {error["tool"] for error in report["tool_errors"]})

    def test_python_syntax_error_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "invalid.py"
            target.write_text("def broken(:\n    pass\n", encoding="utf-8")

            result = self.run_files(
                workspace,
                [target],
                env={"PATH": "/nonexistent"},
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("python-ast", {error["tool"] for error in report["tool_errors"]})

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

    def test_unsupported_only_file_is_incomplete_not_pass(self) -> None:
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

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "incomplete")
            self.assertEqual(report["skipped_files"][0]["path"], "README.md")
            self.assertEqual(report["skipped_files"][0]["reason"], "unsupported_extension")
            self.assertEqual(report["summary"]["scanned_file_count"], 0)

    def test_empty_files_argument_is_incomplete_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)

            result = subprocess.run(
                [sys.executable, str(HOOK), "--format", "json", "--files"],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "incomplete")
            self.assertEqual(report["summary"]["scanned_file_count"], 0)

    def test_bash_payload_without_changed_files_is_incomplete_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "cwd": str(workspace),
                "tool_input": {"command": "true"},
            }

            result = self.run_hook(workspace, payload, "--format", "json")

            self.assertEqual(result.returncode, 2, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "incomplete")
            self.assertEqual(report["source"]["tool_name"], "Bash")
            self.assertEqual(report["summary"]["scanned_file_count"], 0)

    def test_doctor_reports_missing_detectors_in_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--require-tools",
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": "/nonexistent"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["schema_version"], "quality-gate-doctor/v1")
            self.assertEqual(report["status"], "fail")
            self.assertFalse(report["strict_ready"])
            failed_checks = {check["id"] for check in report["checks"] if check["status"] == "fail"}
            self.assertIn("detector.ruff", failed_checks)
            self.assertIn("detector.eslint", failed_checks)
            self.assertIn("detector.lizard", failed_checks)

    def test_doctor_json_explains_missing_detector_install_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--require-tools",
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": "/nonexistent"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            install_plan = {item["tool"]: item for item in report["install_plan"]}
            self.assertEqual(set(install_plan), {"ruff", "eslint", "lizard"})
            self.assertEqual(
                report["quick_install_commands"],
                [
                    "python3 -m pip install --upgrade ruff lizard",
                    "npm install -g eslint",
                ],
            )
            for detector in ["ruff", "eslint", "lizard"]:
                self.assertIn("description", install_plan[detector])
                self.assertIn("purpose", install_plan[detector])
                self.assertIn("install_command", install_plan[detector])
                self.assertIn("verify_command", install_plan[detector])
                self.assertIn("security_note", install_plan[detector])
                self.assertIn("curl | sh", install_plan[detector]["security_note"])
            self.assertIn("Python", install_plan["ruff"]["description"])
            self.assertIn("magic", install_plan["ruff"]["purpose"])
            self.assertEqual(
                install_plan["lizard"]["install_command"],
                "python3 -m pip install --upgrade lizard",
            )
            self.assertIn("cyclomatic complexity", install_plan["lizard"]["purpose"])
            self.assertEqual(install_plan["eslint"]["install_command"], "npm install -g eslint")
            self.assertIn("JavaScript", install_plan["eslint"]["description"])

    def test_doctor_text_explains_safe_detector_install_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--require-tools",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": "/nonexistent"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("Install missing detector tools:", result.stderr)
            self.assertIn("ruff: Fast Python linter", result.stderr)
            self.assertIn("python3 -m pip install --upgrade ruff", result.stderr)
            self.assertIn("lizard: Cyclomatic complexity analyzer", result.stderr)
            self.assertIn("python3 -m pip install --upgrade lizard", result.stderr)
            self.assertIn("eslint: JavaScript and TypeScript linter", result.stderr)
            self.assertIn("npm install -g eslint", result.stderr)
            self.assertIn("Do not use curl | sh", result.stderr)
            self.assertIn("Manual commands only", result.stderr)
            self.assertIn("Rerun --doctor --require-tools", result.stderr)

    def test_doctor_warns_about_missing_detectors_without_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": "/nonexistent"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "warn")
            self.assertFalse(report["strict_ready"])

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

    def test_lizard_headerless_csv_output_is_parsed_in_require_tools_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
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
                "#!/bin/sh\n"
                "printf '%s\\n' '10,12,80,3,11,\"route@1-11@complex.py\",\"complex.py\",\"route\",\"route( status, retries, region )\",1,11'\n",
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
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 2, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["tool_errors"], [])
            complexity_issues = [issue for issue in report["issues"] if issue["rule_id"] == "IMP_007"]
            self.assertGreaterEqual(len(complexity_issues), 1)
            self.assertEqual(complexity_issues[0]["file_path"], "complex.py")
            self.assertEqual(complexity_issues[0]["start_line"], 1)

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
                lizard_script([target]),
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
