from __future__ import annotations

import ast
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
MISSING_DETECTOR_ENV = {
    "PATH": "/nonexistent",
    "VCG_RUFF_BIN": "/nonexistent/ruff",
    "VCG_ESLINT_BIN": "/nonexistent/eslint",
    "VCG_LIZARD_BIN": "/nonexistent/lizard",
}


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


def doctor_lizard_script(emit_canary: bool = True) -> str:
    canary_row = (
        '        if "canary" in Path(path).name:\n'
        '            print(f"20,12,40,1,20,1:1,{path},classify")\n'
        if emit_canary
        else "        pass\n"
    )
    return (
        f"#!{sys.executable}\n"
        "import sys\n"
        "from pathlib import Path\n"
        "from xml.sax.saxutils import escape\n\n"
        'if "--version" in sys.argv:\n'
        '    print("1.23.0")\n'
        "    raise SystemExit(0)\n"
        'extensions = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}\n'
        "files = [arg for arg in sys.argv[1:] if Path(arg).suffix in extensions]\n"
        'if "--csv" in sys.argv:\n'
        '    print("NLOC,CCN,token,PARAM,length,location,file,function")\n'
        "    for path in files:\n"
        f"{canary_row}"
        "    raise SystemExit(0)\n"
        'items = "".join(f\'<item name="{escape(path)}" />\' for path in files)\n'
        "print(f'<cppncss><measure type=\"Function\" /><measure type=\"File\">"
        "{items}</measure></cppncss>')\n"
    )


def doctor_empty_lizard_script() -> str:
    return doctor_lizard_script(emit_canary=False)


def doctor_ruff_script() -> str:
    return textwrap.dedent(
        f"""\
        #!{sys.executable}
        import json
        import sys
        from pathlib import Path

        if "--version" in sys.argv:
            print("ruff 0.15.7")
            raise SystemExit(0)
        files = [arg for arg in sys.argv[1:] if Path(arg).suffix == ".py"]
        diagnostics = [
            {{
                "code": "PLR2004",
                "filename": path,
                "location": {{"row": 2}},
                "message": "canary magic",
            }}
            for path in files
            if "canary" in Path(path).name
        ]
        print(json.dumps(diagnostics))
        raise SystemExit(1 if diagnostics else 0)
        """
    )


def doctor_eslint_script(
    reject_disabled_config: bool = False, allowed_root: Path | None = None
) -> str:
    return textwrap.dedent(
        f"""\
        #!{sys.executable}
        import json
        import sys
        from pathlib import Path

        if "--version" in sys.argv:
            print("v10.6.0")
            raise SystemExit(0)
        extensions = {{".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}}
        files = [arg for arg in sys.argv[1:] if Path(arg).suffix in extensions]
        allowed_root = {str(allowed_root.resolve()) if allowed_root else None!r}
        config_disabled = {reject_disabled_config!r} and any(
            option in sys.argv for option in ("--no-config-lookup", "--no-eslintrc")
        )
        payload = []
        for path in files:
            messages = []
            if allowed_root and not Path(path).is_relative_to(Path(allowed_root)):
                messages.append({{"ruleId": None, "message": "File ignored by scoped config."}})
            elif config_disabled:
                messages.append({{"ruleId": None, "message": "TypeScript config lookup was disabled."}})
            elif "canary" in Path(path).name:
                messages.append(
                    {{"ruleId": "no-magic-numbers", "line": 2, "message": "canary magic"}}
                )
            payload.append({{"filePath": path, "messages": messages}})
        print(json.dumps(payload))
        raise SystemExit(1 if any(item["messages"] and item["messages"][0].get("ruleId") for item in payload) else 0)
        """
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

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("MNT_001", result.stderr)
            self.assertIn("endpoint.py", result.stderr)

    def test_warn_decision_is_visible_and_allows_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "endpoint.py"
            target.write_text('API_URL = "http://localhost:3000/v1"\n', encoding="utf-8")
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Write",
                "cwd": str(workspace),
                "tool_input": {"file_path": "endpoint.py"},
            }

            result = self.run_hook(workspace, payload, "--format", "json")

            self.assertEqual(result.returncode, 0, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["decision"]["outcome"], "warn")
            self.assertEqual(report["summary"]["warn_count"], 1)
            self.assertEqual(report["issues"][0]["enforcement"], "warn")

    def test_policy_rejects_relaxed_complexity_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "clean.py"
            target.write_text('APP_NAME = "demo"\n', encoding="utf-8")

            result = self.run_files(
                workspace,
                [target],
                "--complexity-threshold",
                "11",
                env={"PATH": "/nonexistent"},
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertEqual(report["policy"]["complexity_threshold"], 10)
            self.assertIn("relax", report["tool_errors"][0]["message"])

    def test_policy_fails_closed_without_complexity_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            rules_dir = workspace / "rules"
            shutil.copytree(RULES_DIR, rules_dir)
            (rules_dir / "IMP_007.yml").unlink()
            target = workspace / "clean.py"
            target.write_text('APP_NAME = "demo"\n', encoding="utf-8")

            result = self.run_files(
                workspace,
                [target],
                "--rules-dir",
                str(rules_dir),
                env={"PATH": "/nonexistent"},
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertEqual(
                report["policy"]["complexity_threshold_source"],
                "fallback:DEFAULT_COMPLEXITY_THRESHOLD",
            )

    def test_yaml_threshold_and_tightening_sources_are_effective(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve()
            rules_dir = workspace / "rules"
            shutil.copytree(RULES_DIR, rules_dir)
            complexity_rule = rules_dir / "IMP_007.yml"
            complexity_rule.write_text(
                complexity_rule.read_text(encoding="utf-8").replace(
                    '"threshold": 10', '"threshold": 6'
                ),
                encoding="utf-8",
            )
            module = load_hook_module()
            rules = module.load_rules(rules_dir)

            yaml_args = module.parse_args(["--files"])
            cli_args = module.parse_args(["--complexity-threshold", "4", "--files"])
            yaml_request, _ = module.build_quality_gate_request(yaml_args, None, workspace)
            cli_request, _ = module.build_quality_gate_request(cli_args, None, workspace)
            with mock.patch.dict(
                os.environ, {"VCG_COMPLEXITY_THRESHOLD": "3"}, clear=False
            ):
                env_args = module.parse_args(["--files"])
                env_request, _ = module.build_quality_gate_request(
                    env_args, None, workspace
                )

            yaml_policy, yaml_errors = module.effective_policy(yaml_request, rules)
            cli_policy, cli_errors = module.effective_policy(cli_request, rules)
            env_policy, env_errors = module.effective_policy(env_request, rules)

            self.assertEqual(yaml_errors + cli_errors + env_errors, [])
            self.assertEqual(yaml_policy["complexity_threshold"], 6)
            self.assertEqual(cli_policy["complexity_threshold"], 4)
            self.assertEqual(cli_policy["complexity_threshold_source"], "cli")
            self.assertEqual(env_policy["complexity_threshold"], 3)
            self.assertIn("environment", env_policy["complexity_threshold_source"])

    def test_mixed_enforcement_uses_strongest_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "mixed.py"
            target.write_text(
                'API_URL = "http://localhost:3000/v1"\n'
                "def retry(value):\n    return value > 3\n",
                encoding="utf-8",
            )

            result = self.run_files(
                workspace,
                [target],
                env={"PATH": "/nonexistent"},
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["decision"]["outcome"], "block")
            self.assertGreaterEqual(report["summary"]["block_count"], 1)
            self.assertGreaterEqual(report["summary"]["warn_count"], 1)

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

            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            doc_issues = [issue for issue in payload["issues"] if issue["rule_id"] == "MNT_002"]
            self.assertEqual(len(doc_issues), 1)
            self.assertEqual(doc_issues[0]["file_path"], "api.py")
            self.assertEqual(doc_issues[0]["enforcement"], "observe")
            self.assertEqual(payload["decision"]["outcome"], "observe")
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

            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            design_issues = [issue for issue in payload["issues"] if issue["rule_id"] == "DSN_001"]
            self.assertEqual(len(design_issues), 1)
            self.assertEqual(design_issues[0]["enforcement"], "observe")
            self.assertEqual(payload["decision"]["outcome"], "observe")
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

            self.assertEqual(result.returncode, 0, result.stderr)
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

            self.assertEqual(result.returncode, 0, result.stderr)
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
                env=MISSING_DETECTOR_ENV,
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

    def test_eslint_does_not_mask_modern_variant_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.js"
            target.write_text("export const label = 'ok';\n", encoding="utf-8")
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
            self.assertEqual(eslint_run["status"], "ignored")
            self.assertIn("ignored by the first variant", eslint_run["message"])

    def test_eslint_falls_back_when_modern_option_is_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.js"
            target.write_text("export const label = 'ok';\n", encoding="utf-8")
            clean_payload = json.dumps([{"filePath": str(target), "messages": []}])
            make_executable(
                bin_dir / "eslint",
                "#!/bin/sh\n"
                'case " $* " in\n'
                "  *' --no-config-lookup '*) printf '%s\\n' "
                "\"Invalid option '--no-config-lookup'\" >&2; exit 2 ;;\n"
                f"  *) printf '%s\\n' '{clean_payload}' ;;\n"
                "esac\n",
            )
            make_executable(bin_dir / "lizard", lizard_script([target]))

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 0, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["detectors"]["eslint"]["run"]["status"], "succeeded")

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

    def test_eslint_ignores_unrelated_project_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.ts"
            target.write_text("export const label: string = 'ok';\n", encoding="utf-8")
            warning_payload = json.dumps(
                [
                    {
                        "filePath": str(target),
                        "messages": [
                            {
                                "ruleId": "@typescript-eslint/no-unused-vars",
                                "severity": 1,
                                "line": 1,
                                "message": "Unrelated project warning.",
                            }
                        ],
                    }
                ]
            )
            make_executable(
                bin_dir / "eslint",
                f"#!/bin/sh\nprintf '%s\\n' '{warning_payload}'\n",
            )
            make_executable(bin_dir / "lizard", lizard_script([target]))

            result = self.run_files(
                workspace,
                [target],
                "--require-tools",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 0, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["detectors"]["eslint"]["run"]["status"], "succeeded")
            self.assertEqual(report["issues"], [])

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
                env={**os.environ, **MISSING_DETECTOR_ENV},
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

    def test_doctor_python_profile_probes_only_python_detectors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            rules_dir = workspace / "rules"
            bin_dir.mkdir()
            shutil.copytree(RULES_DIR, rules_dir)
            make_executable(bin_dir / "ruff", doctor_ruff_script())
            make_executable(bin_dir / "lizard", doctor_lizard_script())

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--profile",
                    "python",
                    "--require-tools",
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                    "--rules-dir",
                    str(rules_dir),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": str(bin_dir)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["strict_ready"])
            self.assertEqual(report["selected_profiles"], ["python"])
            profile = report["profiles"]["python"]
            self.assertEqual(profile["status"], "pass")
            self.assertEqual(profile["probes"]["clean"]["decision"]["outcome"], "pass")
            self.assertEqual(profile["probes"]["canary"]["decision"]["outcome"], "block")
            self.assertEqual(
                set(profile["probes"]["canary"]["decision"]["rule_ids"]["block"]),
                {"IMP_004", "IMP_007"},
            )
            self.assertEqual(
                set(profile["probes"]["canary"]["detector_evidence"]),
                {"ruff", "lizard"},
            )
            for evidence in profile["probes"]["canary"]["evidence_by_file"].values():
                self.assertEqual(set(evidence["rule_ids"]), {"IMP_004", "IMP_007"})
                self.assertEqual(set(evidence["detectors"]), {"ruff", "lizard"})
            launch = report["adapter_launch"]
            self.assertTrue(launch["ready"])
            self.assertEqual(launch["core_argv"][0], str(Path(sys.executable).resolve()))
            self.assertEqual(launch["core_argv"][1], str(HOOK.resolve()))
            self.assertEqual(
                launch["environment"]["VCG_RUFF_BIN"],
                str((bin_dir / "ruff").resolve()),
            )
            self.assertIn("VCG_LIZARD_BIN=", launch["claude_posix_command"])
            self.assertEqual(launch["validated_profiles"], ["python"])
            self.assertEqual(launch["project_root"], str(workspace.resolve()))
            self.assertEqual(launch["rules_dir"], str(rules_dir.resolve()))
            self.assertNotIn(
                "detector.eslint",
                {check["id"] for check in report["checks"]},
            )

            clean_file = workspace / "clean.py"
            clean_file.write_text('APP_NAME = "demo"\n', encoding="utf-8")
            launch_dir = workspace / "unrelated-launch-directory"
            launch_dir.mkdir()
            scan = subprocess.run(
                [*launch["generic_cli_argv"], "--files", str(clean_file)],
                cwd=launch_dir,
                env={**os.environ, "PATH": str(bin_dir), **launch["environment"]},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(scan.returncode, 0, scan.stdout or scan.stderr)
            scan_report = json.loads(scan.stdout)
            self.assertEqual(scan_report["root"], str(workspace.resolve()))
            self.assertEqual(scan_report["scanned_files"], ["clean.py"])

    def test_doctor_rejects_non_discriminating_detector_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            make_executable(
                bin_dir / "ruff",
                "#!/bin/sh\n"
                'if [ "$1" = "--version" ]; then printf \'ruff 0.15.7\\n\'; '
                "else printf '[]\\n'; fi\n",
            )
            make_executable(bin_dir / "lizard", doctor_empty_lizard_script())

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--profile",
                    "python",
                    "--require-tools",
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": str(bin_dir)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            profile = json.loads(result.stdout)["profiles"]["python"]
            self.assertEqual(profile["status"], "fail")
            self.assertEqual(profile["reason"], "probe_expectation_failed")
            self.assertNotEqual(
                set(profile["probes"]["canary"]["detector_evidence"]),
                {"ruff", "lizard"},
            )

    def test_doctor_javascript_profile_probes_only_javascript_detectors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            make_executable(
                bin_dir / "node",
                "#!/bin/sh\nexec \"$@\"\n",
            )
            make_executable(bin_dir / "eslint", doctor_eslint_script())
            make_executable(bin_dir / "lizard", doctor_lizard_script())

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--profile",
                    "javascript",
                    "--require-tools",
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": str(bin_dir)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["strict_ready"])
            self.assertEqual(report["selected_profiles"], ["javascript"])
            profile = report["profiles"]["javascript"]
            self.assertEqual(profile["status"], "pass")
            self.assertEqual(profile["probes"]["clean"]["decision"]["outcome"], "pass")
            self.assertEqual(profile["probes"]["canary"]["decision"]["outcome"], "block")
            self.assertEqual(
                set(profile["probes"]["canary"]["detector_evidence"]),
                {"eslint", "lizard"},
            )
            self.assertEqual(
                {Path(path).suffix for path in profile["probes"]["clean"]["scanned_files"]},
                {".js", ".jsx", ".mjs", ".cjs"},
            )
            self.assertEqual(
                report["adapter_launch"]["environment"]["VCG_NODE_BIN"],
                str((bin_dir / "node").resolve()),
            )
            self.assertEqual(report["adapter_launch"]["scan_profile"], "javascript")
            self.assertEqual(
                report["adapter_launch"]["generic_cli_argv"][-2:],
                ["--scan-profile", "javascript"],
            )
            for evidence in profile["probes"]["canary"]["evidence_by_file"].values():
                self.assertEqual(set(evidence["rule_ids"]), {"IMP_004", "IMP_007"})
                self.assertEqual(set(evidence["detectors"]), {"eslint", "lizard"})

            first_evidence = next(
                iter(profile["probes"]["canary"]["evidence_by_file"].values())
            )
            first_evidence["detectors"] = ["eslint"]
            module = load_hook_module()
            self.assertFalse(
                module.doctor_profile_probes_passed(
                    profile["probes"],
                    ("eslint", "lizard"),
                )
            )
            self.assertNotIn(
                "detector.ruff",
                {check["id"] for check in report["checks"]},
            )

    def test_doctor_finds_project_local_eslint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            local_bin = workspace / "node_modules" / ".bin"
            bin_dir.mkdir()
            local_bin.mkdir(parents=True)
            make_executable(local_bin / "eslint", doctor_eslint_script())
            make_executable(
                bin_dir / "eslint",
                "#!/bin/sh\n"
                'if [ "$1" = "--version" ]; then printf \'v0.0.0-global\\n\'; exit 0; fi\n'
                "printf 'global eslint must not run\\n' >&2\n"
                "exit 2\n",
            )
            make_executable(bin_dir / "lizard", doctor_lizard_script())

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--profile",
                    "javascript",
                    "--require-tools",
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": str(bin_dir)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["strict_ready"])
            self.assertEqual(
                report["detectors"]["eslint"]["path"],
                str((local_bin / "eslint").resolve()),
            )

    def test_doctor_does_not_execute_project_local_ruff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            local_bin = workspace / "node_modules" / ".bin"
            bin_dir.mkdir()
            local_bin.mkdir(parents=True)
            make_executable(bin_dir / "ruff", doctor_ruff_script())
            make_executable(bin_dir / "lizard", doctor_lizard_script())
            make_executable(
                local_bin / "ruff",
                "#!/bin/sh\nprintf 'project-local ruff must not run\\n' >&2\nexit 2\n",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--profile",
                    "python",
                    "--require-tools",
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": str(bin_dir)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(
                report["detectors"]["ruff"]["path"],
                str((bin_dir / "ruff").resolve()),
            )

    def test_scan_profile_fails_closed_outside_certified_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            target = workspace / "clean.js"
            target.write_text("const LABEL = 'ok';\n", encoding="utf-8")
            make_executable(bin_dir / "eslint", doctor_eslint_script())
            make_executable(bin_dir / "lizard", lizard_script([target]))

            result = self.run_files(
                workspace,
                [target],
                "--scan-profile",
                "python",
                env={"PATH": str(bin_dir)},
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertEqual(report["policy"]["scan_profile"], "python")
            self.assertIn("profile-scope", {error["tool"] for error in report["tool_errors"]})
            self.assertEqual(report["scanned_files"], [])
            self.assertEqual(report["skipped_files"][0]["reason"], "outside_scan_profile")
            self.assertEqual(report["detectors"]["eslint"]["run"]["status"], "not_applicable")
            self.assertEqual(report["detectors"]["lizard"]["run"]["status"], "not_applicable")

    def test_windows_eslint_prefix_pins_node_and_javascript_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            local_bin = workspace / "node_modules" / ".bin"
            eslint_entrypoint = workspace / "node_modules" / "eslint" / "bin" / "eslint.js"
            node = workspace / "node.exe"
            local_bin.mkdir(parents=True)
            eslint_entrypoint.parent.mkdir(parents=True)
            (local_bin / "eslint.cmd").write_text("@echo off\n", encoding="utf-8")
            eslint_entrypoint.write_text("// eslint entrypoint\n", encoding="utf-8")
            node.write_bytes(b"node")
            node.chmod(0o755)

            module = load_hook_module()
            with mock.patch.dict(os.environ, {"VCG_NODE_BIN": str(node)}):
                prefix = module.eslint_command_prefix(
                    str(local_bin / "eslint.cmd"), platform_name="nt"
                )

            self.assertEqual(prefix, [str(node.resolve()), str(eslint_entrypoint.resolve())])

    def test_doctor_all_profiles_require_discriminating_probes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            make_executable(bin_dir / "ruff", doctor_ruff_script())
            make_executable(bin_dir / "eslint", doctor_eslint_script())
            make_executable(bin_dir / "lizard", doctor_lizard_script())

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--profile",
                    "all",
                    "--require-tools",
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": str(bin_dir)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["strict_ready"])
            self.assertEqual(report["selected_profiles"], ["python", "javascript", "typescript"])
            self.assertEqual(
                {name: profile["status"] for name, profile in report["profiles"].items()},
                {"python": "pass", "javascript": "pass", "typescript": "pass"},
            )

    def test_doctor_typescript_profile_fails_on_ignored_parser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            make_executable(
                bin_dir / "eslint",
                "#!/bin/sh\n"
                'if [ "$1" = "--version" ]; then printf \'v10.6.0\\n\'; exit 0; fi\n'
                'last=""; for arg in "$@"; do last="$arg"; done\n'
                "printf '[{\"filePath\":\"%s\",\"messages\":[{\"ruleId\":null,"
                "\"message\":\"File ignored because no matching configuration was supplied.\"}]}]\\n' "
                '"$last"\n',
            )
            make_executable(bin_dir / "lizard", doctor_lizard_script())

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--profile",
                    "typescript",
                    "--require-tools",
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": str(bin_dir)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertFalse(report["strict_ready"])
            profile = report["profiles"]["typescript"]
            self.assertEqual(profile["status"], "fail")
            self.assertIn("parser", profile["remediation"].lower())
            self.assertEqual(
                profile["setup"]["install_command"],
                "npm install --save-dev eslint @eslint/js typescript typescript-eslint",
            )
            self.assertEqual(profile["setup"]["verify_command"], "npx eslint path/to/file.ts")
            self.assertIn("Do not install silently", profile["remediation"])
            launch = report["adapter_launch"]
            self.assertFalse(launch["ready"])
            self.assertEqual(launch["validated_profiles"], [])
            self.assertIsNone(launch["generic_cli_argv"])
            self.assertIsNone(launch["claude_hook_argv"])

    def test_doctor_typescript_profile_uses_project_eslint_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            source_dir = workspace / "src"
            bin_dir = workspace / "bin"
            source_dir.mkdir()
            bin_dir.mkdir()
            (source_dir / "existing.ts").write_text(
                "export const existing: string = 'ok';\n",
                encoding="utf-8",
            )
            make_executable(
                bin_dir / "eslint",
                doctor_eslint_script(reject_disabled_config=True),
            )
            make_executable(bin_dir / "lizard", doctor_lizard_script())

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--profile",
                    "typescript",
                    "--require-tools",
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": str(bin_dir)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["strict_ready"])
            profile = report["profiles"]["typescript"]
            self.assertEqual(profile["status"], "pass")
            self.assertEqual(profile["probe_directory"], "src")
            self.assertEqual(profile["probes"]["clean"]["decision"]["outcome"], "pass")
            self.assertEqual(profile["probes"]["canary"]["decision"]["outcome"], "block")
            self.assertEqual(
                {Path(path).suffix for path in profile["probes"]["clean"]["scanned_files"]},
                {".ts", ".tsx"},
            )
            for evidence in profile["probes"]["canary"]["evidence_by_file"].values():
                self.assertEqual(set(evidence["rule_ids"]), {"IMP_004", "IMP_007"})
                self.assertEqual(set(evidence["detectors"]), {"eslint", "lizard"})
            self.assertEqual(
                list(workspace.glob("vcg-doctor-typescript-*")),
                [],
                "doctor fixtures must be cleaned automatically",
            )
            self.assertEqual(list(source_dir.glob("vcg-doctor-typescript-*")), [])

    def test_doctor_probe_dir_overrides_scoped_typescript_heuristic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            examples_dir = workspace / "examples"
            source_dir = workspace / "src"
            bin_dir = workspace / "bin"
            examples_dir.mkdir()
            source_dir.mkdir()
            bin_dir.mkdir()
            (examples_dir / "first.ts").write_text("export const first = 'ok';\n", encoding="utf-8")
            (source_dir / "real.ts").write_text("export const real = 'ok';\n", encoding="utf-8")
            make_executable(
                bin_dir / "eslint",
                doctor_eslint_script(allowed_root=source_dir),
            )
            make_executable(bin_dir / "lizard", doctor_lizard_script())

            module = load_hook_module()
            self.assertEqual(
                module.doctor_profile_probe_directory("typescript", workspace),
                examples_dir.resolve(),
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--profile",
                    "typescript",
                    "--probe-dir",
                    "src",
                    "--require-tools",
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": str(bin_dir)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["strict_ready"])
            self.assertEqual(report["profiles"]["typescript"]["probe_directory"], "src")

    def test_doctor_rejects_probe_dir_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "project"
            workspace.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--profile",
                    "python",
                    "--probe-dir",
                    "..",
                    "--require-tools",
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            check = next(item for item in report["checks"] if item["id"] == "probe.directory")
            self.assertEqual(check["status"], "fail")
            self.assertFalse(check["detail"]["inside_root"])
            self.assertEqual(report["profiles"]["python"]["probes"], {})

    def test_python_runtime_check_rejects_pre_311(self) -> None:
        module = load_hook_module()

        check = module.python_runtime_check((3, 10, 14), "3.10.14")

        self.assertEqual(check.status, "fail")
        self.assertIn("3.11", check.remediation)

    def test_doctor_canary_tracks_configured_complexity_threshold(self) -> None:
        module = load_hook_module()

        source = module.doctor_canary_source("python", 20)
        function = ast.parse(source).body[0]

        self.assertEqual(module.python_cyclomatic_complexity(function), 21)
        self.assertEqual(source.count("if value =="), 20)

    def test_doctor_fails_when_required_rule_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bin_dir = workspace / "bin"
            rules_dir = workspace / "rules"
            bin_dir.mkdir()
            rules_dir.mkdir()
            shutil.copy(RULES_DIR / "IMP_007.yml", rules_dir / "IMP_007.yml")
            make_executable(bin_dir / "ruff", doctor_ruff_script())
            make_executable(bin_dir / "lizard", doctor_lizard_script())

            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOK),
                    "--doctor",
                    "--profile",
                    "python",
                    "--require-tools",
                    "--rules-dir",
                    str(rules_dir),
                    "--format",
                    "json",
                    "--root",
                    str(workspace),
                ],
                cwd=workspace,
                env={**os.environ, "PATH": str(bin_dir)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
            report = json.loads(result.stdout)
            self.assertFalse(report["strict_ready"])
            rules_check = next(check for check in report["checks"] if check["id"] == "rules.load")
            self.assertEqual(rules_check["status"], "fail")
            self.assertIn("IMP_004", rules_check["detail"]["missing_rules"])
            self.assertEqual(report["profiles"]["python"]["probes"], {})

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
                env={**os.environ, **MISSING_DETECTOR_ENV},
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
                    "npm install --save-dev eslint @eslint/js typescript typescript-eslint",
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
            self.assertEqual(
                install_plan["eslint"]["install_command"],
                "npm install --save-dev eslint @eslint/js typescript typescript-eslint",
            )
            self.assertIn("eslint.config", install_plan["eslint"]["config_requirement"])
            self.assertEqual(
                install_plan["eslint"]["documentation"],
                "https://typescript-eslint.io/getting-started/",
            )
            self.assertIn("trusted project", install_plan["eslint"]["security_note"])
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
                env={**os.environ, **MISSING_DETECTOR_ENV},
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
            self.assertIn(
                "npm install --save-dev eslint @eslint/js typescript typescript-eslint",
                result.stderr,
            )
            self.assertNotIn("npm install -g eslint", result.stderr)
            self.assertIn("configure: Add eslint.config.mjs", result.stderr)
            self.assertIn("docs: https://typescript-eslint.io/getting-started/", result.stderr)
            self.assertIn("trusted project", result.stderr)
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
