#!/usr/bin/env python3
"""PostToolUse quality gate for magic values and function complexity."""

from __future__ import annotations

import argparse
import ast
import contextlib
import csv
import dataclasses
import datetime as dt
import io
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from tools.rule_loader import Rule, RuleValidationError, load_rules  # noqa: E402


RULE_VERSION = "2025.v1.0.cn"
REPORT_SCHEMA_VERSION = "quality-gate-report/v1"
DOCTOR_SCHEMA_VERSION = "quality-gate-doctor/v1"
REQUEST_SCHEMA_VERSION = "quality-gate-request/v1"
TOOL_TIMEOUT_SECONDS = 30
EDIT_TOOLS = {"Edit", "Write", "MultiEdit"}
REQUIRED_DETECTORS = ("ruff", "eslint", "lizard")
DETECTOR_OVERRIDE_ENV = {
    "ruff": "VCG_RUFF_BIN",
    "eslint": "VCG_ESLINT_BIN",
    "lizard": "VCG_LIZARD_BIN",
}
NODE_OVERRIDE_ENV = "VCG_NODE_BIN"
DOCTOR_REQUIRED_RULES = ("DSN_001", "IMP_004", "IMP_007", "MNT_001", "MNT_002")
MINIMUM_PYTHON_VERSION = (3, 11)
DOCTOR_PROFILE_DETECTORS = {
    "python": ("ruff", "lizard"),
    "javascript": ("eslint", "lizard"),
    "typescript": ("eslint", "lizard"),
}
DOCTOR_PROFILE_EXTENSIONS = {
    "python": (".py",),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "typescript": (".ts", ".tsx"),
}
DOCTOR_CANARY_RULES = ("IMP_004", "IMP_007")
DOCTOR_MAX_CANARY_THRESHOLD = 100
DOCTOR_PROFILE_CLEAN_SOURCE = {
    "python": 'APP_NAME = "demo"\n',
    "javascript": 'const LABEL = "ok";\n',
    "typescript": 'export const LABEL: string = "ok";\n',
}
TYPESCRIPT_PROFILE_SETUP = {
    "description": "Project-local TypeScript support for ESLint flat config.",
    "purpose": "Provides a TypeScript parser and configuration that can lint .ts/.tsx files.",
    "install_command": "npm install --save-dev eslint @eslint/js typescript typescript-eslint",
    "config_requirement": "Add eslint.config.mjs (or another supported eslint.config.*) at the project root and include TypeScript files.",
    "verify_command": "npx eslint path/to/file.ts",
    "documentation": "https://typescript-eslint.io/getting-started/",
    "security_note": "Run only in a trusted project because eslint.config.* is executable code. Use npm or an approved internal registry, review package.json and the lockfile, and do not use curl | sh installers.",
}
DETECTOR_INSTALLS: dict[str, dict[str, str]] = {
    "ruff": {
        "tool": "ruff",
        "description": "Fast Python linter.",
        "purpose": "Detects Python magic numeric literals through Ruff PLR2004 and complements the fallback AST scanner.",
        "install_command": "python3 -m pip install --upgrade ruff",
        "verify_command": "ruff --version",
        "security_note": "Install from PyPI or an approved internal mirror. Do not use curl | sh installers.",
    },
    "eslint": {
        "tool": "eslint",
        "description": "JavaScript and TypeScript linter.",
        "purpose": "Detects JavaScript and TypeScript magic numeric literals with no-magic-numbers.",
        "install_command": "npm install -g eslint",
        "verify_command": "eslint --version",
        "security_note": "Install from npm or an approved internal registry. Do not use curl | sh installers.",
    },
    "lizard": {
        "tool": "lizard",
        "description": "Cyclomatic complexity analyzer.",
        "purpose": "Measures cyclomatic complexity for IMP_007 and prevents complex functions from passing strict gate mode.",
        "install_command": "python3 -m pip install --upgrade lizard",
        "verify_command": "lizard --version",
        "security_note": "Install from PyPI or an approved internal mirror. Do not use curl | sh installers.",
    },
}
ADAPTER_TARGETS = [
    {
        "target": "generic-cli",
        "status": "smoke-tested",
        "entrypoint": "--files",
        "notes": "IDE-neutral file scan entrypoint.",
    },
    {
        "target": "claude-code",
        "status": "documented",
        "entrypoint": "--hook",
        "notes": "PostToolUse adapter contract; project hook smoke still required.",
    },
    {
        "target": "codex",
        "status": "planned",
        "entrypoint": "generic-cli",
        "notes": "Use the IDE-neutral CLI until a native event adapter is verified.",
    },
    {
        "target": "cursor",
        "status": "planned",
        "entrypoint": "generic-cli",
        "notes": "Use the IDE-neutral CLI until a native event adapter is verified.",
    },
    {
        "target": "qoder",
        "status": "planned",
        "entrypoint": "generic-cli",
        "notes": "Use the IDE-neutral CLI until a native event adapter is verified.",
    },
    {
        "target": "trae",
        "status": "planned",
        "entrypoint": "generic-cli",
        "notes": "Use the IDE-neutral CLI until a native event adapter is verified.",
    },
    {
        "target": "droid",
        "status": "planned",
        "entrypoint": "generic-cli",
        "notes": "Use the IDE-neutral CLI until a native event adapter is verified.",
    },
]
DEFAULT_COMPLEXITY_THRESHOLD = 10
DEFAULT_MAX_ISSUES = 25
JSON_INDENT = 2
MILLISECONDS_PER_SECOND = 1000
MAX_TOTAL_METRICS = {"python_max_cyclomatic_complexity"}
RATCHET_METRICS = {
    "hardcoded_endpoint_count",
    "magic_literal_count",
    "python_max_cyclomatic_complexity",
}

PYTHON_EXTENSIONS = {".py"}
JS_TS_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
TYPESCRIPT_EXTENSIONS = {".ts", ".tsx"}
SCANNED_EXTENSIONS = PYTHON_EXTENSIONS | JS_TS_EXTENSIONS | {
    ".go",
    ".java",
    ".kt",
    ".kts",
    ".cpp",
    ".cc",
    ".cxx",
    ".c",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".rs",
}

IGNORED_NUMBERS = {"-1", "0", "1", "0.0", "1.0"}
ALLOW_TOKEN = "ALLOW_MAGIC_NUMBER:"
NUMERIC_LITERAL_RE = re.compile(
    r"(?<![\w.])(-?(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?))(?![\w.])"
)
URL_LITERAL_RE = re.compile(
    r"""(?P<quote>['"])(?P<value>(?:https?://|localhost(?::\d+)?|(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?)[^'"]*)(?P=quote)"""
)
LIZARD_CSV_CCN_INDEX = 1
LIZARD_CSV_LOCATION_INDEX = 5
LIZARD_CSV_FILE_INDEX = 6
LIZARD_CSV_FUNCTION_INDEX = 7
LIZARD_CSV_START_LINE_INDEX = 9
LIZARD_CSV_MIN_COLUMNS = LIZARD_CSV_FUNCTION_INDEX + 1


@dataclasses.dataclass(frozen=True)
class Issue:
    rule_id: str
    severity: str
    category: str
    file_path: str
    start_line: int
    end_line: int
    message: str
    detailed_explanation: str
    suggested_action: str
    enforcement: str = "block"
    metric_values: dict[str, Any] | None = None
    code_snippet: str | None = None

    def to_schema(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "category": self.category,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "message": self.message,
            "detailed_explanation": self.detailed_explanation,
            "suggested_action": self.suggested_action,
            "enforcement": self.enforcement,
            "rule_version": RULE_VERSION,
            "scan_timestamp": dt.datetime.now(dt.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        if self.metric_values:
            payload["metric_values"] = self.metric_values
        if self.code_snippet:
            payload["code_snippet"] = self.code_snippet
        return payload


@dataclasses.dataclass(frozen=True)
class ToolError:
    tool: str
    message: str


@dataclasses.dataclass(frozen=True)
class SkippedFile:
    path: str
    reason: str


@dataclasses.dataclass(frozen=True)
class RatchetViolation:
    file_path: str
    metric: str
    baseline: int
    current: int
    message: str


@dataclasses.dataclass(frozen=True)
class DoctorCheck:
    id: str
    status: str
    message: str
    detail: dict[str, Any] | None = None
    remediation: str | None = None


@dataclasses.dataclass(frozen=True)
class DetectorOutcome:
    status: str
    coverage: str
    files: tuple[str, ...]
    fallback: str | None = None
    message: str | None = None
    uncovered_files: tuple[str, ...] = ()

    def to_schema(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class QualityGateRequest:
    schema_version: str
    root: Path
    files: tuple[str, ...]
    mode: str
    adapter: str
    hook_event_name: str | None
    tool_name: str | None
    baseline_path: Path | None
    strict: bool
    complexity_threshold: int | None
    complexity_threshold_source: str | None

    def source_schema(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "adapter": self.adapter,
            "hook_event_name": self.hook_event_name,
            "tool_name": self.tool_name,
            "request_schema_version": self.schema_version,
        }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan PostToolUse-edited files for magic values and complexity."
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Check local dependencies, rule loading, and adapter readiness.",
    )
    parser.add_argument(
        "--profile",
        choices=("all", "python", "javascript", "typescript"),
        default="all",
        help="Language profile to verify in doctor mode.",
    )
    parser.add_argument(
        "--probe-dir",
        help="Project-relative source directory for doctor fixtures when config is scoped.",
    )
    parser.add_argument(
        "--scan-profile",
        choices=("all", "python", "javascript", "typescript"),
        default="all",
        help="Fail closed if scan inputs exceed the language profile certified by doctor.",
    )
    parser.add_argument(
        "--hook",
        action="store_true",
        help="Read a Claude Code PostToolUse JSON payload from stdin and use exit 2 on failure.",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Files to scan directly instead of reading a hook payload.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Project root. Defaults to CLAUDE_PROJECT_DIR, hook cwd, or the process cwd.",
    )
    parser.add_argument(
        "--complexity-threshold",
        type=int,
        default=None,
        help="Maximum allowed cyclomatic complexity per function.",
    )
    parser.add_argument(
        "--require-tools",
        action="store_true",
        help="Fail closed when Ruff, ESLint, or lizard is required but unavailable.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format. Hook failures still write human feedback to stderr.",
    )
    parser.add_argument(
        "--rules-dir",
        default=str(SCRIPT_ROOT / "rules"),
        help="Directory containing rule YAML files.",
    )
    parser.add_argument(
        "--max-issues",
        type=int,
        default=int(os.environ.get("VCG_MAX_ISSUES", DEFAULT_MAX_ISSUES)),
        help="Maximum issue count to print in text feedback.",
    )
    parser.add_argument(
        "--ratchet-baseline",
        type=Path,
        default=None,
        help="Optional previous JSON report whose touched-file metrics must not regress.",
    )
    return parser.parse_args(argv)


def load_hook_event() -> dict[str, Any]:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid hook JSON: {exc}") from exc
    if not isinstance(event, dict):
        raise ValueError("Hook JSON must be an object.")
    return event


def apply_rule_metadata(issues: list[Issue], rules: dict[str, Rule]) -> list[Issue]:
    hydrated: list[Issue] = []
    for issue in issues:
        rule = rules.get(issue.rule_id)
        if rule is None:
            hydrated.append(issue)
            continue
        hydrated.append(
            Issue(
                rule_id=issue.rule_id,
                severity=rule.sev,
                category=rule.cat,
                file_path=issue.file_path,
                start_line=issue.start_line,
                end_line=issue.end_line,
                message=issue.message,
                detailed_explanation=rule.rat,
                suggested_action=rule.act,
                enforcement=str(rule.gate["enforcement"]),
                metric_values=issue.metric_values,
                code_snippet=issue.code_snippet,
            )
        )
    return hydrated


def request_root(
    args: argparse.Namespace,
    event: dict[str, Any] | None,
    process_cwd: Path,
) -> tuple[Path, list[ToolError]]:
    errors: list[ToolError] = []
    event_root = event.get("cwd") if event is not None else None
    if event_root is not None and (
        not isinstance(event_root, str) or not event_root.strip()
    ):
        errors.append(
            ToolError("hook-input", "Hook `cwd` must be a non-empty string when present.")
        )
        event_root = None
    raw_root = args.root or os.environ.get("CLAUDE_PROJECT_DIR") or event_root
    try:
        root = Path(raw_root or process_cwd).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        errors.append(ToolError("hook-input", f"Project root could not be resolved: {exc}"))
        root = process_cwd.resolve()
    return root, errors


def request_baseline_path(
    raw_path: Path | None, root: Path
) -> tuple[Path | None, list[ToolError]]:
    if raw_path is None:
        return None, []
    try:
        path = raw_path.expanduser()
        if not path.is_absolute():
            path = root / path
        return path.resolve(strict=False), []
    except (OSError, RuntimeError, ValueError) as exc:
        return None, [
            ToolError(
                "ratchet-baseline",
                f"Ratchet baseline path could not be resolved: {exc}",
            )
        ]


def event_string(
    event: dict[str, Any] | None,
    key: str,
    errors: list[ToolError],
) -> str | None:
    if event is None or event.get(key) is None:
        return None
    value = event[key]
    if not isinstance(value, str):
        errors.append(ToolError("hook-input", f"Hook `{key}` must be a string when present."))
        return None
    return value


def claude_candidate_paths(
    event: dict[str, Any] | None,
    root: Path,
    tool_name: str | None,
    errors: list[ToolError],
) -> list[str]:
    if event is None:
        return []
    raw_paths = collect_path_values(event.get("tool_input", {}))
    if tool_name == "Bash" and not raw_paths:
        return git_changed_files(root)
    if tool_name in EDIT_TOOLS and not raw_paths:
        errors.append(
            ToolError(
                "hook-input",
                f"PostToolUse payload for {tool_name} did not include a file path to scan.",
            )
        )
    return raw_paths


def build_quality_gate_request(
    args: argparse.Namespace,
    event: dict[str, Any] | None,
    process_cwd: Path,
) -> tuple[QualityGateRequest, list[ToolError]]:
    root, errors = request_root(args, event, process_cwd)
    hook_event_name = event_string(event, "hook_event_name", errors)
    tool_name = event_string(event, "tool_name", errors)
    conflict = args.hook and args.files is not None

    if conflict:
        errors.append(ToolError("hook-input", "--hook and --files cannot be used together."))
        mode = "invalid"
        adapter = "invalid-mixed-input"
        raw_files: list[str] = []
    elif args.hook:
        mode = "hook"
        adapter = "claude-code-post-tool-use"
        raw_files = claude_candidate_paths(event, root, tool_name, errors)
    else:
        mode = "direct_files"
        adapter = "generic-cli"
        raw_files = list(args.files or [])
        if args.files is None:
            errors.append(ToolError("hook-input", "No --files provided and --hook was not set."))

    threshold = args.complexity_threshold
    threshold_source = "cli" if threshold is not None else None
    env_threshold = os.environ.get("VCG_COMPLEXITY_THRESHOLD")
    if threshold is None and env_threshold is not None:
        try:
            threshold = int(env_threshold)
            threshold_source = "environment:VCG_COMPLEXITY_THRESHOLD"
        except ValueError:
            errors.append(
                ToolError(
                    "rule-config",
                    "VCG_COMPLEXITY_THRESHOLD must be an integer.",
                )
            )

    baseline_path, baseline_errors = request_baseline_path(args.ratchet_baseline, root)
    errors.extend(baseline_errors)

    request = QualityGateRequest(
        schema_version=REQUEST_SCHEMA_VERSION,
        root=root,
        files=tuple(raw_files),
        mode=mode,
        adapter=adapter,
        hook_event_name=hook_event_name,
        tool_name=tool_name,
        baseline_path=baseline_path,
        strict=args.require_tools,
        complexity_threshold=threshold,
        complexity_threshold_source=threshold_source,
    )
    return request, errors


def effective_policy(
    request: QualityGateRequest, rules: dict[str, Rule]
) -> tuple[dict[str, Any], list[ToolError]]:
    errors: list[ToolError] = []
    complexity_rule = rules.get("IMP_007")
    baseline = DEFAULT_COMPLEXITY_THRESHOLD
    source = "fallback:DEFAULT_COMPLEXITY_THRESHOLD"
    if complexity_rule and complexity_rule.gate:
        configured = complexity_rule.gate.get("threshold")
        if isinstance(configured, int) and not isinstance(configured, bool):
            baseline = configured
            source = "rules:IMP_007.gate.threshold"
    else:
        errors.append(
            ToolError(
                "rule-config",
                "Effective policy requires rules/IMP_007.yml with gate.threshold.",
            )
        )

    requested = request.complexity_threshold
    effective = baseline
    if requested is not None:
        if requested <= 0:
            errors.append(ToolError("rule-config", "Complexity threshold must be positive."))
        elif requested > baseline:
            errors.append(
                ToolError(
                    "rule-config",
                    f"Complexity threshold {requested} would relax the rules baseline {baseline}.",
                )
            )
        else:
            effective = requested
            source = request.complexity_threshold_source or "request"
    return {
        "complexity_threshold": effective,
        "complexity_threshold_source": source,
        "complexity_threshold_baseline": baseline,
    }, errors


def collect_path_values(value: Any, key_hint: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_lower = key.lower()
            nested_hint = key_hint or key_lower
            if isinstance(nested, str) and (
                key_lower in {"file_path", "path", "notebook_path", "target_file", "old_path", "new_path"}
                or key_lower.endswith("_path")
                or key_lower.endswith("_file")
            ):
                paths.append(nested)
            else:
                paths.extend(collect_path_values(nested, nested_hint))
    elif isinstance(value, list):
        for item in value:
            paths.extend(collect_path_values(item, key_hint))
    elif isinstance(value, str) and key_hint in {"file_path", "path", "notebook_path"}:
        paths.append(value)
    return paths


def run_detector(
    command: list[str], cwd: Path | None = None
) -> tuple[subprocess.CompletedProcess[str] | None, ToolError | None]:
    tool = Path(command[0]).name
    try:
        return (
            subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=TOOL_TIMEOUT_SECONDS,
                cwd=cwd,
            ),
            None,
        )
    except subprocess.TimeoutExpired:
        return None, ToolError(tool, f"{tool} timed out after {TOOL_TIMEOUT_SECONDS}s.")
    except (OSError, UnicodeError, ValueError) as exc:
        return None, ToolError(tool, f"{tool} could not run: {exc}")


def command_version(command: str | list[str]) -> str | None:
    command_prefix = [command] if isinstance(command, str) else command
    result, error = run_detector([*command_prefix, "--version"])
    if error or result is None or result.returncode != 0:
        return None
    version = (result.stdout or result.stderr).strip().splitlines()
    return version[0] if version else None


def find_detector(detector: str, root: Path | None = None) -> str | None:
    override = os.environ.get(DETECTOR_OVERRIDE_ENV[detector])
    if override:
        return executable_path(Path(override))
    if detector == "eslint" and root is not None:
        local_path = shutil.which(detector, path=str(root / "node_modules" / ".bin"))
        if local_path:
            return executable_path(Path(local_path))
    path = shutil.which(detector)
    if path:
        return executable_path(Path(path))
    if detector == "eslint":
        return None
    sibling_name = f"{detector}.exe" if os.name == "nt" else detector
    return executable_path(Path(sys.executable).resolve().parent / sibling_name)


def executable_path(path: Path) -> str | None:
    try:
        resolved = path.expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if resolved.is_file() and (os.name == "nt" or os.access(resolved, os.X_OK)):
        return str(resolved)
    return None


def find_node_runtime(eslint: str | None = None) -> str | None:
    override = os.environ.get(NODE_OVERRIDE_ENV)
    if override:
        return executable_path(Path(override))
    if eslint:
        sibling_name = "node.exe" if os.name == "nt" else "node"
        sibling = executable_path(Path(eslint).resolve().parent / sibling_name)
        if sibling:
            return sibling
    path = shutil.which("node")
    return executable_path(Path(path)) if path else None


def eslint_command_prefix(eslint: str, platform_name: str = os.name) -> list[str]:
    node = find_node_runtime(eslint)
    if node:
        entrypoint = windows_eslint_entrypoint(eslint) if platform_name == "nt" else eslint
        return [node, entrypoint]
    return [eslint]


def windows_eslint_entrypoint(eslint: str) -> str:
    eslint_path = Path(eslint).resolve()
    if eslint_path.suffix.lower() in {".js", ".mjs", ".cjs"}:
        return str(eslint_path)
    candidates = (
        eslint_path.parent.parent / "eslint" / "bin" / "eslint.js",
        eslint_path.parent / "node_modules" / "eslint" / "bin" / "eslint.js",
    )
    return str(next((path.resolve() for path in candidates if path.is_file()), eslint_path))


def detector_install_info(detector: str) -> dict[str, str]:
    info = DETECTOR_INSTALLS.get(detector)
    if info:
        return dict(info)
    return {
        "tool": detector,
        "description": f"{detector} detector.",
        "purpose": "Required by strict quality gate mode.",
        "install_command": f"Install `{detector}` with your approved package manager.",
        "verify_command": f"{detector} --version",
        "security_note": "Use an approved package source. Do not use curl | sh installers.",
    }


def detector_install_info_for_profiles(
    detector: str, profiles: tuple[str, ...]
) -> dict[str, str]:
    info = detector_install_info(detector)
    if detector == "eslint" and "typescript" in profiles:
        for field in (
            "purpose",
            "install_command",
            "config_requirement",
            "verify_command",
            "documentation",
            "security_note",
        ):
            info[field] = TYPESCRIPT_PROFILE_SETUP[field]
    return info


def detector_inventory(
    root: Path | None = None, include_install: bool = False
) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for detector in REQUIRED_DETECTORS:
        path = find_detector(detector, root)
        node_runtime = detector_node_runtime(detector, path)
        info: dict[str, Any] = {
            "available": path is not None,
            "path": path,
            "version": detector_version(detector, path, node_runtime),
            "override_env": DETECTOR_OVERRIDE_ENV[detector],
            "override_value": os.environ.get(DETECTOR_OVERRIDE_ENV[detector]),
        }
        if detector == "eslint":
            info.update(
                {
                    "node_runtime": node_runtime,
                    "node_override_env": NODE_OVERRIDE_ENV,
                    "node_override_value": os.environ.get(NODE_OVERRIDE_ENV),
                }
            )
        if include_install:
            info["install"] = detector_install_info(detector)
        inventory[detector] = info
    return inventory


def detector_node_runtime(detector: str, path: str | None) -> str | None:
    if detector != "eslint" or path is None:
        return None
    return find_node_runtime(path)


def detector_version(
    detector: str, path: str | None, node_runtime: str | None
) -> str | None:
    if path is None:
        return None
    if detector == "eslint":
        return command_version(eslint_command_prefix(path)) if node_runtime else None
    return command_version(path)


def detector_remediation(detector: str, profiles: tuple[str, ...] = ()) -> str:
    info = detector_install_info_for_profiles(detector, profiles)
    return (
        f"{info['description']} {info['purpose']} "
        f"Install with `{info['install_command']}` and verify with `{info['verify_command']}`. "
        f"{info['security_note']}"
    )


def detector_install_plan(
    detectors: dict[str, dict[str, Any]],
    required_detectors: tuple[str, ...] = REQUIRED_DETECTORS,
    profiles: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    return [
        detector_install_info_for_profiles(detector, profiles)
        for detector in required_detectors
        if not detectors.get(detector, {}).get("available")
    ]


def quick_install_commands(install_plan: list[dict[str, str]]) -> list[str]:
    missing = {item["tool"] for item in install_plan}
    commands_by_tool = {item["tool"]: item["install_command"] for item in install_plan}
    commands: list[str] = []
    python_tools = [detector for detector in ("ruff", "lizard") if detector in missing]
    if python_tools:
        commands.append(f"python3 -m pip install --upgrade {' '.join(python_tools)}")
    if "eslint" in missing:
        commands.append(commands_by_tool["eslint"])
    commands.extend(custom_install_commands(install_plan, commands))
    return commands


def custom_install_commands(
    install_plan: list[dict[str, str]], existing_commands: list[str]
) -> list[str]:
    standard_tools = {"ruff", "lizard", "eslint"}
    return [
        item["install_command"]
        for item in install_plan
        if item["tool"] not in standard_tools
        and item["install_command"] not in existing_commands
    ]


def report_source(request: QualityGateRequest) -> dict[str, Any]:
    return request.source_schema()


def doctor_status(checks: list[DoctorCheck]) -> str:
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def python_runtime_check(
    version_info: tuple[int, ...] = tuple(sys.version_info[:3]),
    version: str = platform.python_version(),
) -> DoctorCheck:
    supported = version_info >= MINIMUM_PYTHON_VERSION
    minimum = ".".join(str(part) for part in MINIMUM_PYTHON_VERSION)
    return DoctorCheck(
        id="python.runtime",
        status="pass" if supported else "fail",
        message=f"Python runtime: {version}",
        detail={
            "executable": sys.executable,
            "version": version,
            "minimum_version": minimum,
        },
        remediation=None if supported else f"Install and run with Python {minimum} or newer.",
    )


def selected_doctor_profiles(profile: str) -> tuple[str, ...]:
    if profile == "all":
        return tuple(DOCTOR_PROFILE_DETECTORS)
    return (profile,)


def required_profile_detectors(profiles: tuple[str, ...]) -> tuple[str, ...]:
    required = {
        detector
        for profile in profiles
        for detector in DOCTOR_PROFILE_DETECTORS[profile]
    }
    return tuple(detector for detector in REQUIRED_DETECTORS if detector in required)


def profile_remediation(profile: str) -> str:
    if profile == "typescript":
        return (
            f"Install project-local TypeScript lint support with "
            f"`{TYPESCRIPT_PROFILE_SETUP['install_command']}`, add a matching "
            "eslint.config.* file that enables the TypeScript parser, verify with "
            f"`{TYPESCRIPT_PROFILE_SETUP['verify_command']}`, then rerun "
            "--doctor --profile typescript --probe-dir <covered-source-dir> --require-tools. "
            "Do not install silently."
        )
    tools = " and ".join(DOCTOR_PROFILE_DETECTORS[profile])
    return f"Install and verify {tools}, then rerun --doctor --profile {profile}."


def doctor_canary_source(profile: str, complexity_threshold: int) -> str:
    values = range(2, complexity_threshold + 2)
    if profile == "python":
        conditions = "".join(
            f"    if value == {value}:\n        return '{value}'\n" for value in values
        )
        return f"def classify(value):\n{conditions}    return 'other'\n"
    parameter = "value: number" if profile == "typescript" else "value"
    return_type = ": string" if profile == "typescript" else ""
    conditions = "".join(
        f"  if (value === {value}) return '{value}';\n" for value in values
    )
    export_prefix = "export " if profile == "typescript" else ""
    return (
        f"{export_prefix}function classify({parameter}){return_type} {{\n"
        f"{conditions}  return 'other';\n}}\n"
    )


def run_doctor_profile_probe(
    profile: str,
    rules: dict[str, Rule],
    project_root: Path,
    probe_directory_override: Path | None = None,
) -> dict[str, Any]:
    probe_directory: Path | None = None
    try:
        probe_directory = doctor_profile_probe_directory(
            profile, project_root, probe_directory_override
        )
        complexity_threshold = int(rules["IMP_007"].gate["threshold"])
        with doctor_fixture_targets(
            profile, probe_directory, complexity_threshold
        ) as targets:
            return execute_doctor_profile_probe(
                profile, rules, project_root, probe_directory, targets
            )
    except OSError as exc:
        message = f"Could not create or use the doctor fixture under {project_root}: {exc}"
        return {
            "status": "fail",
            "reason": "fixture_setup_failed",
            "required_detectors": list(DOCTOR_PROFILE_DETECTORS[profile]),
            "expected_canary_rule_ids": list(DOCTOR_CANARY_RULES),
            "probe_directory": (
                relative_path(probe_directory, project_root)
                if probe_directory is not None
                else None
            ),
            "probes": {},
            "tool_errors": [{"tool": "doctor-fixture", "message": message}],
            "setup": TYPESCRIPT_PROFILE_SETUP if profile == "typescript" else None,
            "remediation": "Use a writable project root, then rerun doctor.",
        }


def doctor_profile_probe_directory(
    profile: str, project_root: Path, override: Path | None = None
) -> Path:
    if override is not None:
        return override
    if profile != "typescript":
        return project_root
    excluded_directories = {".git", ".venv", "dist", "build", "node_modules", "vendor"}
    for current_root, directories, filenames in os.walk(project_root):
        directories[:] = sorted(
            directory for directory in directories if directory not in excluded_directories
        )
        for filename in sorted(filenames):
            if is_typescript_probe_source(filename):
                return Path(current_root).resolve()
    for common_directory in ("src", "app", "lib"):
        candidate = project_root / common_directory
        if candidate.is_dir():
            return candidate.resolve()
    return project_root


def is_typescript_probe_source(filename: str) -> bool:
    return (
        Path(filename).suffix in TYPESCRIPT_EXTENSIONS
        and not filename.endswith(".d.ts")
        and not filename.startswith(("eslint.config.", "vcg-doctor-"))
    )


@contextlib.contextmanager
def doctor_fixture_targets(
    profile: str, probe_directory: Path, complexity_threshold: int
):
    targets: dict[str, list[Path]] = {"clean": [], "canary": []}
    probe_sources = {
        "clean": DOCTOR_PROFILE_CLEAN_SOURCE[profile],
        "canary": doctor_canary_source(profile, complexity_threshold),
    }
    with contextlib.ExitStack() as cleanup:
        for probe_name, content in probe_sources.items():
            for extension in DOCTOR_PROFILE_EXTENSIONS[profile]:
                descriptor, raw_path = tempfile.mkstemp(
                    prefix=f"vcg-doctor-{profile}-{probe_name}-",
                    suffix=extension,
                    dir=probe_directory,
                )
                os.close(descriptor)
                target = Path(raw_path).resolve()
                cleanup.callback(target.unlink, missing_ok=True)
                target.write_text(content, encoding="utf-8")
                targets[probe_name].append(target)
        yield targets


def execute_doctor_probe_scan(
    profile: str,
    probe_name: str,
    targets: list[Path],
    rules: dict[str, Rule],
    project_root: Path,
) -> dict[str, Any]:
    request = QualityGateRequest(
        schema_version=REQUEST_SCHEMA_VERSION,
        root=project_root,
        files=tuple(relative_path(target, project_root) for target in targets),
        mode="doctor_probe",
        adapter="doctor",
        hook_event_name=None,
        tool_name=None,
        baseline_path=None,
        strict=True,
        complexity_threshold=None,
        complexity_threshold_source=None,
    )
    policy, policy_errors = effective_policy(request, rules)
    files, skipped, path_errors = resolve_scan_files(list(request.files), request.root)
    issues, tool_errors, outcomes = scan_files(
        files,
        request.root,
        policy["complexity_threshold"],
        request.strict,
    )
    issues = apply_rule_metadata(issues, rules)
    errors = dedupe_tool_errors([*policy_errors, *path_errors, *tool_errors])
    decision = build_decision(
        issues,
        errors,
        files,
        {"status": "not_configured", "violations": []},
    )
    return {
        "expected_decision": "pass" if probe_name == "clean" else "block",
        "expected_rule_ids": [] if probe_name == "clean" else list(DOCTOR_CANARY_RULES),
        "decision": decision,
        "rule_ids": sorted({issue.rule_id for issue in issues}),
        "detector_evidence": issue_detector_evidence(issues),
        "evidence_by_file": issue_evidence_by_file(issues, files, project_root),
        "detectors": profile_detector_schemas(profile, outcomes),
        "scanned_files": [relative_path(path, project_root) for path in files],
        "skipped_files": [dataclasses.asdict(item) for item in skipped],
        "tool_errors": [dataclasses.asdict(error) for error in errors],
    }


def issue_detector_evidence(issues: list[Issue]) -> list[str]:
    return sorted(
        {
            str(issue.metric_values["detector"])
            for issue in issues
            if issue.metric_values and issue.metric_values.get("detector")
        }
    )


def issue_evidence_by_file(
    issues: list[Issue], files: list[Path], root: Path
) -> dict[str, dict[str, list[str]]]:
    evidence = {
        relative_path(path, root): {"rule_ids": [], "detectors": []} for path in files
    }
    for issue in issues:
        file_evidence = evidence.get(issue.file_path)
        if file_evidence is None:
            continue
        file_evidence["rule_ids"].append(issue.rule_id)
        detector = issue.metric_values.get("detector") if issue.metric_values else None
        if detector:
            file_evidence["detectors"].append(str(detector))
    for file_evidence in evidence.values():
        file_evidence["rule_ids"] = sorted(set(file_evidence["rule_ids"]))
        file_evidence["detectors"] = sorted(set(file_evidence["detectors"]))
    return evidence


def profile_detector_schemas(
    profile: str, outcomes: dict[str, DetectorOutcome]
) -> dict[str, dict[str, Any]]:
    required = DOCTOR_PROFILE_DETECTORS[profile]
    return {
        name: outcome.to_schema()
        for name, outcome in outcomes.items()
        if name in required
    }


def doctor_probe_detector_coverage_passed(
    probe: dict[str, Any], required_detectors: tuple[str, ...]
) -> bool:
    return all(
        probe["detectors"].get(detector, {}).get("status") == "succeeded"
        and probe["detectors"].get(detector, {}).get("coverage") == "complete"
        for detector in required_detectors
    )


def doctor_profile_probes_passed(
    probes: dict[str, dict[str, Any]], required_detectors: tuple[str, ...]
) -> bool:
    clean = probes["clean"]
    canary = probes["canary"]
    canary_rules = set(canary["decision"]["rule_ids"]["block"])
    detector_evidence = set(canary["detector_evidence"])
    return (
        clean["decision"]["outcome"] == "pass"
        and not clean["skipped_files"]
        and canary["decision"]["outcome"] == "block"
        and not canary["skipped_files"]
        and set(DOCTOR_CANARY_RULES).issubset(canary_rules)
        and set(required_detectors).issubset(detector_evidence)
        and canary_file_evidence_passed(canary, required_detectors)
        and all(
            doctor_probe_detector_coverage_passed(probe, required_detectors)
            for probe in probes.values()
        )
    )


def canary_file_evidence_passed(
    canary: dict[str, Any], required_detectors: tuple[str, ...]
) -> bool:
    expected_rules = set(DOCTOR_CANARY_RULES)
    expected_detectors = set(required_detectors)
    return all(
        expected_rules.issubset(set(file_evidence["rule_ids"]))
        and expected_detectors.issubset(set(file_evidence["detectors"]))
        for file_evidence in canary["evidence_by_file"].values()
    ) and bool(canary["evidence_by_file"])


def execute_doctor_profile_probe(
    profile: str,
    rules: dict[str, Rule],
    project_root: Path,
    probe_directory: Path,
    targets: dict[str, list[Path]],
) -> dict[str, Any]:
    required_detectors = DOCTOR_PROFILE_DETECTORS[profile]
    probes = {
        name: execute_doctor_probe_scan(profile, name, paths, rules, project_root)
        for name, paths in targets.items()
    }
    passed = doctor_profile_probes_passed(probes, required_detectors)
    tool_errors = list(
        {
            (error["tool"], error["message"]): error
            for probe in probes.values()
            for error in probe["tool_errors"]
        }.values()
    )
    return {
        "status": "pass" if passed else "fail",
        "reason": None if passed else "probe_expectation_failed",
        "required_detectors": list(required_detectors),
        "expected_canary_rule_ids": list(DOCTOR_CANARY_RULES),
        "probe_directory": relative_path(probe_directory, project_root) or ".",
        "probes": probes,
        "tool_errors": tool_errors,
        "setup": TYPESCRIPT_PROFILE_SETUP if profile == "typescript" else None,
        "remediation": None if passed else profile_remediation(profile),
    }


def doctor_environment_checks(
    root: Path, root_errors: list[ToolError] | None = None
) -> tuple[list[DoctorCheck], DoctorCheck]:
    root_errors = root_errors or []
    runtime_check = python_runtime_check()
    checks = [
        runtime_check,
        doctor_project_root_check(root, root_errors),
        doctor_script_check(),
    ]
    return checks, runtime_check


def doctor_project_root_check(
    root: Path, root_errors: list[ToolError]
) -> DoctorCheck:
    root_is_directory = root.is_dir() and not root_errors
    if root_is_directory:
        message = f"Project root is a directory: {root}"
    elif root_errors:
        message = "; ".join(error.message for error in root_errors)
    else:
        message = f"Project root is missing or not a directory: {root}"
    return DoctorCheck(
        id="project.root",
        status="pass" if root_is_directory else "fail",
        message=message,
        detail={
            "root": root.as_posix(),
            "errors": [dataclasses.asdict(error) for error in root_errors],
        },
        remediation=None
        if root_is_directory
        else "Pass --root or run the command from the project root.",
    )


def doctor_script_check() -> DoctorCheck:
    script_executable = os.access(__file__, os.X_OK)
    return DoctorCheck(
        id="script.executable",
        status="pass" if script_executable else "warn",
        message=(
            "Hook script is executable."
            if script_executable
            else "Hook script is not executable; invoke it with python3 or chmod +x it."
        ),
        detail={"path": Path(__file__).resolve().as_posix()},
        remediation=None
        if script_executable
        else "Run via `python3` or set executable bit.",
    )


def doctor_rules_check(
    rules_dir: Path,
) -> tuple[dict[str, Rule], list[str], DoctorCheck]:
    try:
        rules = load_rules(rules_dir)
    except RuleValidationError as exc:
        return {}, [], DoctorCheck(
            id="rules.load",
            status="fail",
            message=str(exc),
            detail={"rules_dir": rules_dir.as_posix()},
            remediation="Fix the rule YAML or pass a valid --rules-dir.",
        )
    loaded_rules = sorted(rules)
    missing_rules = sorted(set(DOCTOR_REQUIRED_RULES) - set(rules))
    if missing_rules:
        return rules, loaded_rules, DoctorCheck(
            id="rules.load",
            status="fail",
            message=f"Missing required quality gate rule(s): {', '.join(missing_rules)}.",
            detail={
                "rules_dir": rules_dir.as_posix(),
                "rules": loaded_rules,
                "required_rules": list(DOCTOR_REQUIRED_RULES),
                "missing_rules": missing_rules,
            },
            remediation="Restore the required rule YAML files, then rerun doctor.",
        )
    complexity_threshold = int(rules["IMP_007"].gate["threshold"])
    if complexity_threshold > DOCTOR_MAX_CANARY_THRESHOLD:
        return rules, loaded_rules, DoctorCheck(
            id="rules.load",
            status="fail",
            message=(
                f"IMP_007 threshold {complexity_threshold} exceeds the doctor canary limit "
                f"{DOCTOR_MAX_CANARY_THRESHOLD}."
            ),
            detail={
                "rules_dir": rules_dir.as_posix(),
                "rules": loaded_rules,
                "complexity_threshold": complexity_threshold,
                "doctor_canary_limit": DOCTOR_MAX_CANARY_THRESHOLD,
            },
            remediation="Use a probeable complexity threshold, then rerun doctor.",
        )
    return rules, loaded_rules, DoctorCheck(
        id="rules.load",
        status="pass",
        message=f"Loaded {len(loaded_rules)} rule(s).",
        detail={"rules_dir": rules_dir.as_posix(), "rules": loaded_rules},
        remediation=None,
    )


def resolve_doctor_rules_directory(
    rules_dir: Path,
) -> tuple[Path, DoctorCheck | None]:
    try:
        return rules_dir.expanduser().resolve(), None
    except (OSError, RuntimeError, ValueError) as exc:
        return rules_dir, DoctorCheck(
            id="rules.load",
            status="fail",
            message=f"Rules directory could not be resolved: {exc}",
            detail={
                "requested": str(rules_dir),
                "resolved": None,
                "error": str(exc),
            },
            remediation="Pass an existing, non-cyclic --rules-dir, then rerun doctor.",
        )


def load_scan_rules(raw_rules_dir: str) -> tuple[dict[str, Rule], list[ToolError]]:
    try:
        rules_dir = Path(raw_rules_dir).expanduser().resolve()
        return load_rules(rules_dir), []
    except (OSError, RuntimeError, ValueError) as exc:
        return {}, [
            ToolError("rule-config", f"Rules directory could not be resolved: {exc}")
        ]
    except RuleValidationError as exc:
        return {}, [ToolError("rule-config", str(exc))]


def doctor_detector_checks(
    detectors: dict[str, dict[str, Any]],
    required_detectors: tuple[str, ...],
    profiles: tuple[str, ...],
    require_tools: bool,
) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    for detector in required_detectors:
        info = detectors[detector]
        available = bool(info["available"])
        ready = detector_ready(detector, info)
        node_missing = detector == "eslint" and available and not info["node_runtime"]
        checks.append(
            DoctorCheck(
                id=f"detector.{detector}",
                status="pass" if ready else "fail" if require_tools else "warn",
                message=(
                    f"{detector} found at {info['path']}"
                    if ready
                    else f"{detector} found, but its Node runtime could not be resolved."
                    if node_missing
                    else f"{detector} not found; strict --require-tools mode will fail closed."
                ),
                detail=info,
                remediation=None
                if ready
                else (
                    "Install a supported Node.js runtime through an approved package source, "
                    "set VCG_NODE_BIN to its absolute executable path, verify with "
                    "`node --version` and `eslint --version`, then rerun doctor."
                )
                if node_missing
                else detector_remediation(detector, profiles),
            )
        )
    return checks


def detector_ready(detector: str, info: dict[str, Any]) -> bool:
    return bool(
        info["available"]
        and (detector != "eslint" or info.get("node_runtime"))
    )


def unavailable_profile_probe(profile: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "reason": "prerequisites_unmet",
        "required_detectors": list(DOCTOR_PROFILE_DETECTORS[profile]),
        "expected_canary_rule_ids": list(DOCTOR_CANARY_RULES),
        "probe_directory": None,
        "probes": {},
        "tool_errors": [],
        "setup": TYPESCRIPT_PROFILE_SETUP if profile == "typescript" else None,
        "remediation": (
            "Resolve the failed runtime, rule, or detector checks. "
            f"Then rerun --doctor --profile {profile} --require-tools."
        ),
    }


def doctor_profile_checks(
    profiles: tuple[str, ...],
    rules: dict[str, Rule],
    rules_ready: bool,
    runtime_ready: bool,
    root_ready: bool,
    project_root: Path,
    probe_directory: Path | None,
    probe_directory_ready: bool,
    detectors: dict[str, dict[str, Any]],
    require_tools: bool,
) -> tuple[dict[str, dict[str, Any]], list[DoctorCheck]]:
    results: dict[str, dict[str, Any]] = {}
    checks: list[DoctorCheck] = []
    for profile in profiles:
        detector_names = DOCTOR_PROFILE_DETECTORS[profile]
        detectors_ready = all(
            detector_ready(name, detectors[name]) for name in detector_names
        )
        result = (
            run_doctor_profile_probe(profile, rules, project_root, probe_directory)
            if doctor_profile_prerequisites_ready(
                runtime_ready,
                rules_ready,
                root_ready,
                probe_directory_ready,
                detectors_ready,
            )
            else unavailable_profile_probe(profile)
        )
        passed = result["status"] == "pass"
        results[profile] = result
        checks.append(
            DoctorCheck(
                id=f"profile.{profile}.smoke",
                status=doctor_profile_check_status(passed, require_tools),
                message=(
                    f"{profile} profile smoke passed."
                    if passed
                    else f"{profile} profile smoke failed."
                ),
                detail=result,
                remediation=result["remediation"],
            )
        )
    return results, checks


def doctor_profile_prerequisites_ready(
    runtime_ready: bool,
    rules_ready: bool,
    root_ready: bool,
    probe_directory_ready: bool,
    detectors_ready: bool,
) -> bool:
    return all(
        (
            runtime_ready,
            rules_ready,
            root_ready,
            probe_directory_ready,
            detectors_ready,
        )
    )


def doctor_profile_check_status(passed: bool, require_tools: bool) -> str:
    if passed:
        return "pass"
    return "fail" if require_tools else "warn"


def requested_doctor_probe_directory(
    project_root: Path, raw_probe_directory: str | None
) -> tuple[Path | None, DoctorCheck | None]:
    if raw_probe_directory is None:
        return None, None
    try:
        raw_path = Path(raw_probe_directory).expanduser()
        candidate = (
            raw_path if raw_path.is_absolute() else project_root / raw_path
        ).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return None, DoctorCheck(
            id="probe.directory",
            status="fail",
            message="Doctor probe directory could not be resolved.",
            detail={
                "requested": raw_probe_directory,
                "resolved": None,
                "inside_root": False,
                "error": str(exc),
            },
            remediation=(
                "Pass an existing, non-cyclic project-relative --probe-dir covered by "
                "the selected language config."
            ),
        )
    try:
        candidate.relative_to(project_root)
        inside_root = True
    except ValueError:
        inside_root = False
    valid = inside_root and candidate.is_dir()
    check = DoctorCheck(
        id="probe.directory",
        status="pass" if valid else "fail",
        message=(
            f"Doctor probe directory: {candidate}"
            if valid
            else f"Doctor probe directory must be an existing directory under {project_root}."
        ),
        detail={
            "requested": raw_probe_directory,
            "resolved": candidate.as_posix(),
            "inside_root": inside_root,
        },
        remediation=None
        if valid
        else "Pass a project-relative --probe-dir covered by the selected language config.",
    )
    return (candidate if valid else None), check


def adapter_scan_profile(
    validated_profiles: tuple[str, ...], ready: bool
) -> str | None:
    if not ready:
        return None
    return validated_profiles[0] if len(validated_profiles) == 1 else "all"


def adapter_launch_contract(
    detectors: dict[str, dict[str, Any]],
    requested_profiles: tuple[str, ...],
    validated_profiles: tuple[str, ...],
    ready: bool,
    project_root: Path,
    rules_dir: Path,
) -> dict[str, Any]:
    core_argv = [str(Path(sys.executable).resolve()), str(Path(__file__).resolve())]
    scan_profile = adapter_scan_profile(validated_profiles, ready)
    environment = {
        DETECTOR_OVERRIDE_ENV[detector]: str(info["path"])
        for detector, info in detectors.items()
        if info.get("path")
    }
    node_runtime = (
        detectors["eslint"].get("node_runtime")
        if "eslint" in required_profile_detectors(requested_profiles)
        else None
    )
    if node_runtime:
        environment[NODE_OVERRIDE_ENV] = node_runtime
    pinned_arguments = [
        "--root",
        str(project_root),
        "--rules-dir",
        str(rules_dir),
        "--require-tools",
        "--scan-profile",
        str(scan_profile),
    ]
    generic_cli_argv = (
        [
            *core_argv,
            "--format",
            "json",
            *pinned_arguments,
        ]
        if ready
        else None
    )
    claude_hook_argv = (
        [
            *core_argv,
            "--hook",
            *pinned_arguments,
        ]
        if ready
        else None
    )
    assignments = [f"{name}={shlex.quote(path)}" for name, path in environment.items()]
    claude_posix_command = (
        " ".join([*assignments, shlex.join(claude_hook_argv)])
        if claude_hook_argv
        else None
    )
    return {
        "ready": ready,
        "core_argv": core_argv,
        "generic_cli_argv": generic_cli_argv,
        "claude_hook_argv": claude_hook_argv,
        "environment": environment,
        "requested_profiles": list(requested_profiles),
        "validated_profiles": list(validated_profiles),
        "scan_profile": scan_profile,
        "project_root": str(project_root),
        "rules_dir": str(rules_dir),
        "node_runtime": node_runtime,
        "claude_posix_command": claude_posix_command,
        "notes": (
            "Native adapters append --files to generic_cli_argv. Claude Code consumes "
            "claude_hook_argv. Launch fields remain null until every requested profile passes. "
            "Project root and rules directory are pinned. Regenerate doctor output after "
            "tools, project paths, or rules move or change."
        ),
    }


def doctor_readiness(
    profiles: dict[str, dict[str, Any]], checks: list[DoctorCheck]
) -> tuple[bool, tuple[str, ...]]:
    validated_profiles = tuple(
        name for name, result in profiles.items() if result["status"] == "pass"
    )
    ready = len(validated_profiles) == len(profiles) and all(
        check.status != "fail" for check in checks
    )
    return ready, validated_profiles


def build_doctor_report(
    root: Path,
    rules_dir: Path,
    require_tools: bool,
    profile: str = "all",
    raw_probe_directory: str | None = None,
    root_errors: list[ToolError] | None = None,
) -> dict[str, Any]:
    checks, runtime_check = doctor_environment_checks(root, root_errors)
    root_check = next(check for check in checks if check.id == "project.root")
    probe_directory, probe_directory_check = requested_doctor_probe_directory(
        root, raw_probe_directory
    )
    if probe_directory_check:
        checks.append(probe_directory_check)
    rules_dir, rules_resolution_check = resolve_doctor_rules_directory(rules_dir)
    if rules_resolution_check:
        rules, loaded_rules, rules_check = {}, [], rules_resolution_check
    else:
        rules, loaded_rules, rules_check = doctor_rules_check(rules_dir)
    checks.append(rules_check)
    detectors = detector_inventory(root, include_install=True)
    selected_profiles = selected_doctor_profiles(profile)
    required_detectors = required_profile_detectors(selected_profiles)
    install_plan = detector_install_plan(detectors, required_detectors, selected_profiles)
    for detector in REQUIRED_DETECTORS:
        detectors[detector]["install"] = detector_install_info_for_profiles(
            detector, selected_profiles
        )
    checks.extend(
        doctor_detector_checks(
            detectors, required_detectors, selected_profiles, require_tools
        )
    )
    profiles, profile_checks = doctor_profile_checks(
        selected_profiles,
        rules,
        rules_check.status == "pass",
        runtime_check.status == "pass",
        root_check.status == "pass",
        root,
        probe_directory,
        probe_directory_check is None or probe_directory_check.status == "pass",
        detectors,
        require_tools,
    )
    checks.extend(profile_checks)
    strict_ready, validated_profiles = doctor_readiness(profiles, checks)
    status = doctor_status(checks)
    return {
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "status": status,
        "strict_ready": strict_ready,
        "selected_profiles": list(selected_profiles),
        "profiles": profiles,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "root": root.as_posix(),
        "requested_probe_directory": (
            probe_directory.as_posix() if probe_directory is not None else None
        ),
        "rules_loaded": loaded_rules,
        "detectors": detectors,
        "tool_catalog": [
            detector_install_info_for_profiles(detector, selected_profiles)
            for detector in REQUIRED_DETECTORS
        ],
        "install_plan": install_plan,
        "quick_install_commands": quick_install_commands(install_plan),
        "adapter_launch": adapter_launch_contract(
            detectors,
            selected_profiles,
            validated_profiles,
            strict_ready,
            root,
            rules_dir,
        ),
        "adapter_targets": ADAPTER_TARGETS,
        "checks": [dataclasses.asdict(check) for check in checks],
        "next_steps": doctor_next_steps(status, strict_ready),
    }


def doctor_next_steps(status: str, strict_ready: bool) -> list[str]:
    if strict_ready:
        return [
            "Run a direct file scan with --files before enabling an IDE hook.",
            "Enable the target adapter only after its smoke test passes.",
        ]
    if status == "fail":
        return [
            "Follow the remediation field on each failed check.",
            "Rerun --doctor --require-tools before enabling strict adapter mode.",
        ]
    return [
        "Fallback detectors can run, but install ruff, eslint, and lizard before strict gate mode.",
        "Use docs/ADAPTERS.md to choose a verified target path.",
    ]


def render_doctor_text(report: dict[str, Any]) -> str:
    lines = [
        f"Quality gate doctor: {report['status']}",
        f"strict_ready: {str(report['strict_ready']).lower()}",
    ]
    for check in report["checks"]:
        lines.append(f"- {check['status']}: {check['id']}: {check['message']}")
        if check.get("remediation"):
            lines.append(f"  remediation: {check['remediation']}")
    lines.extend(render_doctor_install_plan(report))
    lines.extend(render_adapter_launch(report["adapter_launch"]))
    lines.append("Next steps:")
    for step in report["next_steps"]:
        lines.append(f"- {step}")
    return "\n".join(lines)


def render_doctor_install_plan(report: dict[str, Any]) -> list[str]:
    if not report.get("install_plan"):
        return []
    lines = ["Install missing detector tools:"]
    for item in report["install_plan"]:
        lines.append(f"- {item['tool']}: {item['description']} {item['purpose']}")
        lines.append(f"  install: {item['install_command']}")
        if item.get("config_requirement"):
            lines.append(f"  configure: {item['config_requirement']}")
        lines.append(f"  verify: {item['verify_command']}")
        if item.get("documentation"):
            lines.append(f"  docs: {item['documentation']}")
        lines.append(f"  safety: {item['security_note']}")
    if report.get("quick_install_commands"):
        lines.append("Quick install commands:")
        lines.extend(f"- {command}" for command in report["quick_install_commands"])
    lines.extend(
        [
            "Safety: use PyPI/npm or approved internal mirrors. Do not use curl | sh installers.",
            "Manual commands only: adapters must not run them without explicit user approval.",
            "After installing: Rerun --doctor --require-tools.",
        ]
    )
    return lines


def render_adapter_launch(launch: dict[str, Any]) -> list[str]:
    if not launch["ready"]:
        return ["Adapter launch is not ready; resolve failed doctor checks first."]
    return [
        "Reproducible Claude Code POSIX launch:",
        f"- {launch['claude_posix_command']}",
        "Native adapters should append --files to adapter_launch.generic_cli_argv.",
    ]


def run_doctor(
    args: argparse.Namespace, root: Path, root_errors: list[ToolError] | None = None
) -> int:
    report = build_doctor_report(
        root,
        Path(args.rules_dir),
        args.require_tools,
        args.profile,
        args.probe_dir,
        root_errors,
    )
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=JSON_INDENT))
    else:
        output = render_doctor_text(report)
        stream = sys.stderr if report["status"] == "fail" else sys.stdout
        print(output, file=stream)
    return 1 if report["status"] == "fail" else 0


def git_changed_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "-z"],
        capture_output=True,
        text=False,
        check=False,
    )
    if result.returncode != 0:
        return []

    entries = result.stdout.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status = entry[:2].decode("utf-8", errors="replace")
        path = entry[3:].decode("utf-8", errors="replace")
        if status.startswith("R") or status.startswith("C"):
            if index < len(entries):
                new_path = entries[index].decode("utf-8", errors="replace")
                index += 1
                paths.append(new_path)
            continue
        if not status.startswith("D"):
            paths.append(path)
    return paths


def resolve_scan_files(
    raw_paths: list[str], root: Path
) -> tuple[list[Path], list[SkippedFile], list[ToolError]]:
    files: list[Path] = []
    skipped: list[SkippedFile] = []
    errors: list[ToolError] = []
    seen: set[Path] = set()
    for raw_path in raw_paths:
        if not raw_path:
            skipped.append(SkippedFile(path="", reason="empty_path"))
            continue
        try:
            candidate = Path(raw_path).expanduser()
            if not candidate.is_absolute():
                candidate = root / candidate
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            skipped.append(SkippedFile(path=raw_path, reason="unresolvable_path"))
            errors.append(
                ToolError(
                    "path-resolution",
                    f"Scan path {raw_path!r} could not be resolved: {exc}",
                )
            )
            continue
        try:
            resolved.relative_to(root)
        except ValueError:
            skipped.append(SkippedFile(path=raw_path, reason="outside_root"))
            continue
        if resolved in seen:
            skipped.append(SkippedFile(path=relative_path(resolved, root), reason="duplicate"))
            continue
        if resolved.suffix not in SCANNED_EXTENSIONS:
            skipped.append(SkippedFile(path=relative_path(resolved, root), reason="unsupported_extension"))
            continue
        if resolved.is_file():
            files.append(resolved)
            seen.add(resolved)
        else:
            skipped.append(SkippedFile(path=relative_path(resolved, root), reason="not_a_file"))
    return files, skipped, errors


def normalize_scan_files(raw_paths: list[str], root: Path) -> list[Path]:
    files, _, _ = resolve_scan_files(raw_paths, root)
    return files


def enforce_scan_profile(
    files: list[Path], profile: str, root: Path
) -> tuple[list[Path], list[SkippedFile], list[ToolError]]:
    if profile == "all":
        return files, [], []
    allowed_extensions = set(DOCTOR_PROFILE_EXTENSIONS[profile])
    in_scope = [path for path in files if path.suffix in allowed_extensions]
    outside_profile = [path for path in files if path.suffix not in allowed_extensions]
    if not outside_profile:
        return in_scope, [], []
    names = [relative_path(path, root) for path in outside_profile]
    skipped = [SkippedFile(path=name, reason="outside_scan_profile") for name in names]
    errors = [
        ToolError("profile-scope", f"Scan profile {profile} does not certify: {', '.join(names)}.")
    ]
    return in_scope, skipped, errors


def relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_detector_path(raw_path: str, root: Path) -> Path | None:
    try:
        path = Path(raw_path)
        if not path.is_absolute():
            path = root / path
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def has_allow_magic(lines: list[str], line_index: int) -> bool:
    start = max(0, line_index - 2)
    return any(ALLOW_TOKEN in lines[idx] for idx in range(start, line_index + 1))


def is_constant_definition(line: str, suffix: str) -> bool:
    stripped = line.strip()
    if suffix in PYTHON_EXTENSIONS:
        return bool(re.match(r"^[A-Z][A-Z0-9_]*(?:\s*:\s*[^=]+)?\s*=", stripped))
    if suffix in JS_TS_EXTENSIONS:
        return bool(
            re.match(
                r"^(?:export\s+)?(?:const|let|var)\s+[A-Z][A-Z0-9_]*(?:\s*:\s*[^=]+)?\s*=",
                stripped,
            )
        )
    return bool(
        re.match(
            r"^(?:(?:public|private|protected|static|final|const|constexpr|readonly)\s+)*"
            r".*\b[A-Z][A-Z0-9_]*\b\s*=",
            stripped,
        )
    )


def mask_string_literals(line: str) -> str:
    chars = list(line)
    quote: str | None = None
    escaped = False
    for index, char in enumerate(chars):
        if quote is None:
            if char in {"'", '"'}:
                quote = char
                chars[index] = " "
            continue
        chars[index] = " "
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == quote:
            quote = None
    return "".join(chars)


def strip_inline_comment(line: str, suffix: str) -> str:
    masked = mask_string_literals(line)
    comment_markers = ["#"] if suffix in PYTHON_EXTENSIONS else ["//", "#"]
    cut = len(line)
    for marker in comment_markers:
        index = masked.find(marker)
        if index != -1:
            cut = min(cut, index)
    return line[:cut]


def scan_magic_values_builtin(path: Path, root: Path) -> list[Issue]:
    rel = relative_path(path, root)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    issues: list[Issue] = []
    for line_index, line in enumerate(lines):
        line_number = line_index + 1
        allow_magic = has_allow_magic(lines, line_index)
        constant_definition = is_constant_definition(line, path.suffix)

        for url_match in URL_LITERAL_RE.finditer(line):
            value = url_match.group("value")
            issues.append(
                Issue(
                    rule_id="MNT_001",
                    severity="L",
                    category="MNT",
                    file_path=rel,
                    start_line=line_number,
                    end_line=line_number,
                    message="Hardcoded endpoint or host literal should move behind configuration.",
                    detailed_explanation=(
                        "配置硬编码会让环境切换、部署和测试复用变得脆弱；"
                        "把端点、主机或端口放入命名配置边界。"
                    ),
                    suggested_action="RCM",
                    code_snippet=line.strip(),
                    metric_values={"literal": value},
                )
            )

        code_line = strip_inline_comment(line, path.suffix)
        masked_line = mask_string_literals(code_line)
        if allow_magic or constant_definition:
            continue
        for match in NUMERIC_LITERAL_RE.finditer(masked_line):
            literal = match.group(1)
            if literal in IGNORED_NUMBERS:
                continue
            issues.append(
                Issue(
                    rule_id="IMP_004",
                    severity="M",
                    category="IMP",
                    file_path=rel,
                    start_line=line_number,
                    end_line=line_number,
                    message=f"Magic numeric literal `{literal}` should be named or configured.",
                    detailed_explanation=(
                        "魔法值硬编码会隐藏领域含义并增加维护风险；"
                        "请提取为表达意图的常量、配置项，或用 ALLOW_MAGIC_NUMBER 说明例外。"
                    ),
                    suggested_action="FIX",
                    code_snippet=line.strip(),
                    metric_values={"literal": literal},
                )
            )
    return issues


class PythonComplexityVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: str, threshold: int) -> None:
        self.rel_path = rel_path
        self.threshold = threshold
        self.issues: list[Issue] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node, node.name)
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.visit(child)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function(node, node.name)
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.visit(child)

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> None:
        complexity = python_cyclomatic_complexity(node)
        if complexity <= self.threshold:
            return
        self.issues.append(
            Issue(
                rule_id="IMP_007",
                severity="M",
                category="IMP",
                file_path=self.rel_path,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                message=f"Function `{name}` has cyclomatic complexity {complexity}.",
                detailed_explanation=(
                    "复杂逻辑会显著提高理解、测试和修改成本；"
                    "请拆分分支、提取命名步骤，或降低单函数职责。"
                ),
                suggested_action="RCM",
                metric_values={
                    "cyclomatic_complexity": complexity,
                    "threshold": self.threshold,
                    "detector": "python_ast_fallback",
                },
            )
        )


def python_cyclomatic_complexity(node: ast.AST) -> int:
    complexity = 1
    stack = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += max(1, len(child.values) - 1)
        elif isinstance(child, ast.comprehension):
            complexity += 1 + len(child.ifs)
        elif hasattr(ast, "Match") and isinstance(child, ast.Match):
            complexity += len(child.cases)
        stack.extend(ast.iter_child_nodes(child))
    return complexity


def scan_python_complexity_builtin(path: Path, root: Path, threshold: int) -> list[Issue]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    visitor = PythonComplexityVisitor(relative_path(path, root), threshold)
    visitor.visit(tree)
    return visitor.issues


def exported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        for item in node.value.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                names.add(item.value)
    return names


def scan_python_public_api_docstrings(path: Path, root: Path) -> list[Issue]:
    if path.suffix not in PYTHON_EXTENSIONS:
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    exports = exported_names(tree)
    if not exports:
        return []

    issues: list[Issue] = []
    rel = relative_path(path, root)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name not in exports or ast.get_docstring(node):
            continue
        issues.append(
            Issue(
                rule_id="MNT_002",
                severity="L",
                category="MNT",
                file_path=rel,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                message=f"Exported Python API `{node.name}` should have a docstring.",
                detailed_explanation=(
                    "公开 API 缺少契约注释会让调用者依赖实现细节；"
                    "请在导出对象上写明意图、参数语义、边界行为和不变量。"
                ),
                suggested_action="RCM",
                metric_values={"detector": "python_ast_public_api_docstring", "export": node.name},
            )
        )
    return issues


def body_without_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = list(node.body)
    if not body:
        return body
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return body[1:]
    return body


def function_parameter_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    parameters = [arg.arg for arg in [*node.args.posonlyargs, *node.args.args]]
    if parameters and parameters[0] in {"self", "cls"}:
        parameters = parameters[1:]
    return parameters


def delegated_call_from_statement(statement: ast.stmt) -> ast.Call | None:
    if isinstance(statement, ast.Return) and isinstance(statement.value, ast.Call):
        return statement.value
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
        return statement.value
    return None


def is_pure_pass_through_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = body_without_docstring(node)
    if len(body) != 1:
        return False
    call = delegated_call_from_statement(body[0])
    if call is None or call.keywords:
        return False
    parameters = function_parameter_names(node)
    if not parameters or len(call.args) != len(parameters):
        return False
    call_arg_names = [arg.id for arg in call.args if isinstance(arg, ast.Name)]
    return call_arg_names == parameters


def scan_python_pass_through_functions(path: Path, root: Path) -> list[Issue]:
    if path.suffix not in PYTHON_EXTENSIONS:
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []

    issues: list[Issue] = []
    rel = relative_path(path, root)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not is_pure_pass_through_function(node):
            continue
        issues.append(
            Issue(
                rule_id="DSN_001",
                severity="L",
                category="DSN",
                file_path=rel,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                message=f"Function `{node.name}` only delegates its parameters to another call.",
                detailed_explanation=(
                    "纯透传函数通常说明当前抽象层没有增加设计价值；"
                    "请合并这一层，或补充它承担的语义、边界处理或信息隐藏职责。"
                ),
                suggested_action="RCM",
                metric_values={"detector": "python_ast_pass_through_function"},
            )
        )
    return issues


def python_complexity_metrics(path: Path) -> dict[str, int]:
    metrics = {
        "python_function_count": 0,
        "python_max_cyclomatic_complexity": 0,
        "python_total_cyclomatic_complexity": 0,
    }
    if path.suffix not in PYTHON_EXTENSIONS:
        return metrics
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return metrics

    complexities = [
        python_cyclomatic_complexity(node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not complexities:
        return metrics
    return {
        "python_function_count": len(complexities),
        "python_max_cyclomatic_complexity": max(complexities),
        "python_total_cyclomatic_complexity": sum(complexities),
    }


def collect_quality_metrics(files: list[Path], root: Path) -> dict[str, Any]:
    file_metrics: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    for path in files:
        rel = relative_path(path, root)
        literal_issues = scan_magic_values_builtin(path, root)
        metrics = {
            "magic_literal_count": sum(1 for issue in literal_issues if issue.rule_id == "IMP_004"),
            "hardcoded_endpoint_count": sum(1 for issue in literal_issues if issue.rule_id == "MNT_001"),
            **python_complexity_metrics(path),
        }
        file_metrics[rel] = metrics
        merge_quality_totals(totals, metrics)

    return {
        "files": file_metrics,
        "totals": dict(sorted(totals.items())),
    }


def merge_quality_totals(totals: dict[str, int], metrics: dict[str, int]) -> None:
    for metric, value in metrics.items():
        if metric in MAX_TOTAL_METRICS:
            totals[metric] = max(totals.get(metric, 0), value)
        else:
            totals[metric] = totals.get(metric, 0) + value


def load_baseline_metrics(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: unable to read ratchet baseline: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: ratchet baseline must be a JSON object")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict) or not isinstance(metrics.get("files"), dict):
        raise ValueError(f"{path}: ratchet baseline must include metrics.files")
    return metrics


def ratchet_violation_for_metric(
    file_path: str,
    metric: str,
    current_value: int,
    baseline_file: dict[str, Any],
) -> RatchetViolation | None:
    baseline_value = baseline_file.get(metric)
    if not isinstance(baseline_value, int):
        return None
    if current_value <= baseline_value:
        return None
    return RatchetViolation(
        file_path=file_path,
        metric=metric,
        baseline=baseline_value,
        current=current_value,
        message=(
            f"{metric} regressed from {baseline_value} to {current_value} "
            f"for touched file {file_path}."
        ),
    )


def ratchet_violations_for_file(
    file_path: str,
    metrics: dict[str, int],
    baseline_files: dict[str, Any],
) -> list[RatchetViolation]:
    baseline_file = baseline_files.get(file_path)
    if not isinstance(baseline_file, dict):
        return []
    violations = []
    for metric, current_value in metrics.items():
        if metric not in RATCHET_METRICS:
            continue
        violation = ratchet_violation_for_metric(file_path, metric, current_value, baseline_file)
        if violation is not None:
            violations.append(violation)
    return violations


def evaluate_ratchet(
    current_metrics: dict[str, Any], baseline_path: Path | None
) -> tuple[dict[str, Any], list[ToolError]]:
    if baseline_path is None:
        return {"status": "not_configured", "violations": []}, []
    try:
        baseline_metrics = load_baseline_metrics(baseline_path)
    except ValueError as exc:
        return {
            "status": "error",
            "baseline": str(baseline_path),
            "violations": [],
        }, [ToolError("quality-ratchet", str(exc))]

    violations: list[RatchetViolation] = []
    baseline_files = baseline_metrics["files"]
    for file_path, metrics in current_metrics["files"].items():
        violations.extend(ratchet_violations_for_file(file_path, metrics, baseline_files))

    return {
        "status": "fail" if violations else "pass",
        "baseline": str(baseline_path),
        "violations": [dataclasses.asdict(violation) for violation in violations],
    }, []


def parse_ruff_diagnostics(
    diagnostics: list[Any], root: Path
) -> tuple[list[Issue], str | None]:
    issues: list[Issue] = []
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            return [], "Ruff JSON diagnostics must be objects."
        if diagnostic.get("code") != "PLR2004":
            continue
        raw_filename = diagnostic.get("filename")
        location = diagnostic.get("location")
        if not isinstance(raw_filename, str) or not raw_filename:
            return [], "Ruff PLR2004 diagnostics must include a filename."
        if not isinstance(location, dict):
            return [], "Ruff PLR2004 diagnostics must include an object location."
        try:
            row = int(location.get("row"))
        except (TypeError, ValueError):
            return [], "Ruff PLR2004 diagnostics must include a numeric location row."
        filename = resolve_detector_path(raw_filename, root)
        if filename is None:
            return [], "Ruff PLR2004 diagnostic filename could not be resolved."
        issues.append(
            Issue(
                rule_id="IMP_004",
                severity="M",
                category="IMP",
                file_path=relative_path(filename, root),
                start_line=row,
                end_line=row,
                message=diagnostic.get("message")
                or "Magic numeric literal detected by Ruff PLR2004.",
                detailed_explanation=(
                    "Ruff PLR2004 detected an unnamed comparison literal; "
                    "replace it with a named constant or a configuration value."
                ),
                suggested_action="FIX",
                code_snippet=None,
                metric_values={"detector": "ruff", "code": "PLR2004"},
            )
        )
    return issues, None


def ruff_exit_consistency_error(diagnostics: list[Any], returncode: int) -> str | None:
    if returncode == 1 and not diagnostics:
        return "Ruff exited 1 but produced no diagnostics."
    if returncode == 0 and diagnostics:
        return "Ruff exited 0 but produced diagnostics."
    return None


def parse_ruff_result(
    result: subprocess.CompletedProcess[str], root: Path
) -> tuple[list[Issue], str | None]:
    if result.returncode not in {0, 1}:
        return [], result.stderr.strip() or "Ruff failed."
    if not result.stdout.strip():
        return [], result.stderr.strip() or "Ruff failed without JSON output."
    try:
        diagnostics = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], "Ruff produced non-JSON output."
    if not isinstance(diagnostics, list):
        return [], "Ruff JSON output must be an array."
    consistency_error = ruff_exit_consistency_error(diagnostics, result.returncode)
    if consistency_error:
        return [], consistency_error
    return parse_ruff_diagnostics(diagnostics, root)


def run_ruff(
    files: list[Path], root: Path, _require_tools: bool
) -> tuple[list[Issue], list[ToolError], DetectorOutcome]:
    python_files = [path for path in files if path.suffix in PYTHON_EXTENSIONS]
    outcome_files = tuple(relative_path(path, root) for path in python_files)
    if not python_files:
        return [], [], DetectorOutcome("not_applicable", "none", ())
    ruff = find_detector("ruff", root)
    if not ruff:
        message = "Ruff is required for Python PLR2004 magic-value checks."
        return [], [ToolError("ruff", message)], DetectorOutcome(
            "missing", "none", outcome_files, message=message
        )

    result, timeout_error = run_detector(
        [
            ruff,
            "check",
            "--select",
            "PLR2004",
            "--output-format",
            "json",
            "--no-cache",
            "--",
            *[str(path) for path in python_files],
        ],
        cwd=root,
    )
    if timeout_error:
        return [], [timeout_error], DetectorOutcome(
            "failed", "none", outcome_files, message=timeout_error.message
        )
    assert result is not None
    issues, parse_error = parse_ruff_result(result, root)
    if parse_error:
        return [], [ToolError("ruff", parse_error)], DetectorOutcome(
            "failed", "none", outcome_files, message=parse_error
        )
    return issues, [], DetectorOutcome("succeeded", "complete", outcome_files)


def iter_eslint_messages(payload: list[Any]):
    for file_result in payload:
        if not isinstance(file_result, dict):
            continue
        messages = file_result.get("messages", [])
        if not isinstance(messages, list):
            continue
        for message in messages:
            if isinstance(message, dict):
                yield message


def eslint_payload_errors(payload: list[Any], root: Path) -> list[str]:
    errors: list[str] = []
    for result in payload:
        if not isinstance(result, dict):
            errors.append("ESLint JSON file results must be objects.")
            continue
        raw_file_path = result.get("filePath")
        if not isinstance(raw_file_path, str) or not raw_file_path:
            errors.append("ESLint JSON file results must include a filePath.")
        elif resolve_detector_path(raw_file_path, root) is None:
            errors.append("ESLint JSON file result filePath could not be resolved.")
        messages = result.get("messages", [])
        if not isinstance(messages, list):
            errors.append("ESLint JSON file result messages must be an array.")
        elif any(not isinstance(message, dict) for message in messages):
            errors.append("ESLint JSON messages must be objects.")
    return errors


def eslint_reported_files(payload: list[Any], root: Path) -> set[Path]:
    reported: set[Path] = set()
    for result in payload:
        if not isinstance(result, dict):
            continue
        raw_file_path = result.get("filePath")
        if not isinstance(raw_file_path, str) or not raw_file_path:
            continue
        file_path = resolve_detector_path(raw_file_path, root)
        if file_path is not None:
            reported.add(file_path)
    return reported


def eslint_missing_files(
    payload: list[Any], expected_files: list[Path], root: Path
) -> list[str]:
    reported_files = eslint_reported_files(payload, root)
    return [
        relative_path(path, root)
        for path in expected_files
        if path.resolve() not in reported_files
    ]


def eslint_magic_line_error(payload: list[Any]) -> str | None:
    for message in iter_eslint_messages(payload):
        if message.get("ruleId") != "no-magic-numbers":
            continue
        if not isinstance(message.get("line") or 1, int):
            return "ESLint no-magic-numbers diagnostics must include a numeric line."
    return None


def eslint_exit_consistency_error(payload: list[Any], returncode: int) -> str | None:
    messages = list(iter_eslint_messages(payload))
    has_gate_diagnostics = any(
        message.get("ruleId") == "no-magic-numbers" for message in messages
    )
    if returncode == 1 and not messages:
        return "ESLint exited 1 but produced no diagnostics."
    if returncode == 0 and has_gate_diagnostics:
        return "ESLint exited 0 but produced no-magic-numbers diagnostics."
    return None


def eslint_option_unsupported(message: str, option: str) -> bool:
    normalized_message = message.lower()
    option_key = option.removeprefix("--").removeprefix("no-")
    markers = ("invalid option", "unknown option", "unrecognized option")
    return option_key in normalized_message and any(
        marker in normalized_message for marker in markers
    )


def eslint_coverage_diagnostic(
    payload: list[Any], expected_files: list[Path], root: Path
) -> tuple[str | None, str | None]:
    messages = eslint_payload_errors(payload, root)
    missing_files = eslint_missing_files(payload, expected_files, root)
    if missing_files:
        messages.append(f"ESLint omitted requested file(s): {', '.join(missing_files)}.")

    diagnostics = [
        message
        for message in iter_eslint_messages(payload)
        if message.get("ruleId") is None or message.get("fatal")
    ]
    diagnostic_messages = [
        str(message.get("message") or "ESLint emitted an unclassified diagnostic.")
        for message in diagnostics
    ]
    messages.extend(diagnostic_messages)
    line_error = eslint_magic_line_error(payload)
    if line_error:
        messages.append(line_error)
    if not messages:
        return None, None
    status = (
        "ignored"
        if any("ignored" in message.lower() for message in diagnostic_messages)
        else "failed"
    )
    return status, "; ".join(messages)


def eslint_command_variants(
    eslint_prefix: list[str], rule_config: str, files: list[Path]
) -> list[list[str]]:
    base_command = [*eslint_prefix, "--rule", rule_config, "--format", "json"]
    file_arguments = [str(path) for path in files]
    if any(path.suffix in TYPESCRIPT_EXTENSIONS for path in files):
        return [[*base_command, *file_arguments]]
    parser_options = json.dumps(
        {"ecmaFeatures": {"jsx": True}, "sourceType": "module"}
    )
    extension_arguments = [
        item
        for extension in sorted({path.suffix for path in files})
        for item in ("--ext", extension)
    ]
    configured_command = [
        *base_command,
        "--parser-options",
        parser_options,
        *extension_arguments,
    ]
    return [
        [*configured_command, "--no-config-lookup", *file_arguments],
        [*configured_command, "--no-eslintrc", *file_arguments],
    ]


def run_eslint(
    files: list[Path], root: Path, _require_tools: bool
) -> tuple[list[Issue], list[ToolError], DetectorOutcome]:
    js_files = [path for path in files if path.suffix in JS_TS_EXTENSIONS]
    outcome_files = tuple(relative_path(path, root) for path in js_files)
    if not js_files:
        return [], [], DetectorOutcome("not_applicable", "none", ())
    eslint = find_detector("eslint", root)
    if not eslint:
        message = "ESLint is required for JS/TS no-magic-numbers checks."
        return [], [ToolError("eslint", message)], DetectorOutcome(
            "missing", "none", outcome_files, message=message
        )
    node_runtime = find_node_runtime(eslint)
    if not node_runtime:
        message = (
            "ESLint requires an absolute Node runtime; set VCG_NODE_BIN and rerun doctor."
        )
        return [], [ToolError("eslint", message)], DetectorOutcome(
            "missing", "none", outcome_files, message=message
        )

    rule_config = json.dumps(
        {
            "no-magic-numbers": [
                "error",
                {
                    "ignore": [-1, 0, 1],
                    "ignoreArrayIndexes": True,
                    "enforceConst": True,
                },
            ]
        }
    )
    command_variants = eslint_command_variants(
        eslint_command_prefix(eslint), rule_config, js_files
    )

    last_error = ""
    failure_status = "failed"
    for command in command_variants:
        result, timeout_error = run_detector(command, cwd=root)
        if timeout_error:
            failure_status = "failed"
            last_error = timeout_error.message
            break
        assert result is not None
        if result.returncode not in {0, 1}:
            failure_status = "failed"
            last_error = result.stderr.strip() or "ESLint failed."
            if "--no-config-lookup" in command and eslint_option_unsupported(
                last_error, "--no-config-lookup"
            ):
                continue
            break
        if result.stdout.strip():
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                failure_status = "failed"
                last_error = "ESLint produced non-JSON output."
                break
            if not isinstance(payload, list):
                failure_status = "failed"
                last_error = "ESLint JSON output must be an array."
                break
            diagnostic_status, diagnostic_message = eslint_coverage_diagnostic(
                payload, js_files, root
            )
            if diagnostic_status is not None:
                failure_status = diagnostic_status
                last_error = diagnostic_message or "ESLint did not lint every requested file."
                break
            consistency_error = eslint_exit_consistency_error(payload, result.returncode)
            if consistency_error:
                failure_status = "failed"
                last_error = consistency_error
                break
            return (
                parse_eslint_payload(payload, root),
                [],
                DetectorOutcome("succeeded", "complete", outcome_files),
            )
        failure_status = "failed"
        last_error = result.stderr.strip()
        break
    message = last_error or "ESLint failed without JSON output."
    return [], [ToolError("eslint", message)], DetectorOutcome(
        failure_status, "none", outcome_files, message=message
    )


def eslint_issue_from_message(
    message: dict[str, Any], filename: Path, root: Path
) -> Issue | None:
    if message.get("ruleId") != "no-magic-numbers":
        return None
    line = message.get("line") or 1
    if not isinstance(line, int):
        return None
    return Issue(
        rule_id="IMP_004",
        severity="M",
        category="IMP",
        file_path=relative_path(filename, root),
        start_line=line,
        end_line=line,
        message=message.get("message") or "Magic numeric literal detected by ESLint.",
        detailed_explanation=(
            "ESLint no-magic-numbers detected an unnamed numeric literal; "
            "replace it with a named constant or a configuration value."
        ),
        suggested_action="FIX",
        metric_values={"detector": "eslint", "rule": "no-magic-numbers"},
    )


def parse_eslint_payload(payload: Any, root: Path) -> list[Issue]:
    issues: list[Issue] = []
    if not isinstance(payload, list):
        return issues
    for file_result in payload:
        if not isinstance(file_result, dict):
            continue
        raw_filename = file_result.get("filePath")
        if not isinstance(raw_filename, str) or not raw_filename:
            continue
        filename = resolve_detector_path(raw_filename, root)
        if filename is None:
            continue
        for message in file_result.get("messages", []):
            if not isinstance(message, dict):
                continue
            issue = eslint_issue_from_message(message, filename, root)
            if issue:
                issues.append(issue)
    return issues


def lizard_row_values(
    row: dict[str, str], expected_files: set[Path], root: Path
) -> tuple[int, Path, int, str | None]:
    try:
        ccn = int(float(row.get("CCN", "0")))
    except (TypeError, ValueError):
        return 0, root, 0, "lizard CSV output contains a non-numeric CCN value."
    raw_file_path = row.get("file")
    if not raw_file_path:
        return 0, root, 0, "lizard CSV output contains an empty file path."
    file_path = resolve_detector_path(raw_file_path, root)
    if file_path is None:
        return 0, root, 0, "lizard CSV file path could not be resolved."
    if file_path not in expected_files:
        rel = relative_path(file_path, root)
        return 0, root, 0, f"lizard reported an unrequested file: {rel}."
    location = row.get("start_line") or row.get("location") or "1"
    try:
        line = int(location.split(":", 1)[0])
    except ValueError:
        return 0, root, 0, "lizard CSV output contains a non-numeric start line."
    return ccn, file_path, line, None


def parse_lizard_rows(
    rows: list[dict[str, str]], expected_files: set[Path], root: Path, threshold: int
) -> tuple[list[Issue], set[Path], str | None]:
    issues: list[Issue] = []
    covered_files: set[Path] = set()
    for row in rows:
        ccn, file_path, line, row_error = lizard_row_values(row, expected_files, root)
        if row_error:
            return [], set(), row_error
        covered_files.add(file_path)
        if ccn <= threshold:
            continue
        function = row.get("function") or "<unknown>"
        issues.append(
            Issue(
                rule_id="IMP_007",
                severity="M",
                category="IMP",
                file_path=relative_path(file_path, root),
                start_line=line,
                end_line=line,
                message=f"Function `{function}` has cyclomatic complexity {ccn}.",
                detailed_explanation=(
                    "lizard detected a function over the configured complexity threshold; "
                    "split the function or simplify branching before continuing."
                ),
                suggested_action="RCM",
                metric_values={
                    "cyclomatic_complexity": ccn,
                    "threshold": threshold,
                    "detector": "lizard",
                },
            )
        )
    return issues, covered_files, None


def parse_lizard_xml_files(output: str, root: Path) -> tuple[set[Path], str | None]:
    try:
        xml_root = ET.fromstring(output)
    except ET.ParseError:
        return set(), "lizard XML coverage probe produced malformed XML."
    file_measure = next(
        (measure for measure in xml_root.findall("measure") if measure.get("type") == "File"),
        None,
    )
    if file_measure is None:
        return set(), "lizard XML coverage probe omitted the File measure."

    reported_files: set[Path] = set()
    for item in file_measure.findall("item"):
        raw_file_path = item.get("name")
        if not raw_file_path:
            return set(), "lizard XML coverage probe contains an empty file path."
        file_path = resolve_detector_path(raw_file_path, root)
        if file_path is None:
            return set(), "lizard XML coverage file path could not be resolved."
        reported_files.add(file_path)
    return reported_files, None


def lizard_coverage_difference_error(
    reported_files: set[Path], files: list[Path], root: Path
) -> str | None:
    expected_files = {path.resolve() for path in files}
    missing = expected_files - reported_files
    unexpected = reported_files - expected_files
    if missing:
        names = ", ".join(sorted(relative_path(path, root) for path in missing))
        return f"lizard XML coverage omitted requested file(s): {names}."
    if unexpected:
        names = ", ".join(sorted(relative_path(path, root) for path in unexpected))
        return f"lizard XML coverage reported unrequested file(s): {names}."
    return None


def lizard_xml_coverage_error(
    lizard: str, files: list[Path], root: Path
) -> str | None:
    result, run_error = run_detector(
        [lizard, "--xml", *[str(path) for path in files]], cwd=root
    )
    if run_error:
        return run_error.message
    assert result is not None
    if result.returncode != 0:
        return result.stderr.strip() or "lizard XML coverage probe failed."
    if not result.stdout.strip():
        return "lizard XML coverage probe produced empty output."
    reported_files, parse_error = parse_lizard_xml_files(result.stdout, root)
    if parse_error:
        return parse_error
    return lizard_coverage_difference_error(reported_files, files, root)


def run_lizard(
    files: list[Path], root: Path, threshold: int, _require_tools: bool
) -> tuple[list[Issue], list[ToolError], DetectorOutcome]:
    outcome_files = tuple(relative_path(path, root) for path in files)
    if not files:
        return [], [], DetectorOutcome("not_applicable", "none", ())
    lizard = find_detector("lizard", root)
    if not lizard:
        message = "lizard is required for function complexity checks."
        return [], [ToolError("lizard", message)], DetectorOutcome(
            "missing", "none", outcome_files, message=message
        )

    result, run_error = run_detector(
        [lizard, "--csv", *[str(path) for path in files]], cwd=root
    )
    if run_error:
        return [], [run_error], DetectorOutcome(
            "failed", "none", outcome_files, message=run_error.message
        )
    assert result is not None
    if result.returncode not in {0, 1}:
        message = result.stderr.strip() or "lizard failed."
        return [], [ToolError("lizard", message)], DetectorOutcome(
            "failed", "none", outcome_files, message=message
        )
    if not result.stdout.strip() and result.returncode == 1:
        message = result.stderr.strip() or "lizard failed without CSV output."
        return [], [ToolError("lizard", message)], DetectorOutcome(
            "failed", "none", outcome_files, message=message
        )

    rows: list[dict[str, str]] = []
    if result.stdout.strip():
        rows, valid_csv = parse_lizard_csv(result.stdout)
        if not valid_csv:
            message = "lizard CSV output is missing required fields."
            return [], [ToolError("lizard", message)], DetectorOutcome(
                "failed", "none", outcome_files, message=message
            )

    expected_files = {path.resolve() for path in files}
    issues, covered_files, parse_error = parse_lizard_rows(
        rows, expected_files, root, threshold
    )
    if parse_error:
        return [], [ToolError("lizard", parse_error)], DetectorOutcome(
            "failed", "none", outcome_files, message=parse_error
        )
    uncovered_files = [path for path in files if path.resolve() not in covered_files]
    coverage_error = (
        lizard_xml_coverage_error(lizard, uncovered_files, root)
        if uncovered_files
        else None
    )
    if coverage_error:
        return [], [ToolError("lizard", coverage_error)], DetectorOutcome(
            "failed", "none", outcome_files, message=coverage_error
        )
    return issues, [], DetectorOutcome("succeeded", "complete", outcome_files)


def parse_lizard_csv(output: str) -> tuple[list[dict[str, str]], bool]:
    required_fields = {"CCN", "location", "file", "function"}
    reader = csv.DictReader(io.StringIO(output))
    if reader.fieldnames and required_fields.issubset(set(reader.fieldnames)):
        return list(reader), True

    rows: list[dict[str, str]] = []
    for columns in csv.reader(io.StringIO(output)):
        if not columns or not any(column.strip() for column in columns):
            continue
        if len(columns) < LIZARD_CSV_MIN_COLUMNS:
            return [], False
        rows.append(
            {
                "CCN": columns[LIZARD_CSV_CCN_INDEX],
                "location": columns[LIZARD_CSV_LOCATION_INDEX],
                "file": columns[LIZARD_CSV_FILE_INDEX],
                "function": columns[LIZARD_CSV_FUNCTION_INDEX],
                "start_line": (
                    columns[LIZARD_CSV_START_LINE_INDEX]
                    if len(columns) > LIZARD_CSV_START_LINE_INDEX
                    else columns[LIZARD_CSV_LOCATION_INDEX]
                ),
            }
        )
    return rows, bool(rows)


def dedupe_issues(issues: list[Issue]) -> list[Issue]:
    seen: set[tuple[str, str, int]] = set()
    deduped: list[Issue] = []
    for issue in issues:
        key = (issue.rule_id, issue.file_path, issue.start_line)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def dedupe_tool_errors(errors: list[ToolError]) -> list[ToolError]:
    seen: set[tuple[str, str]] = set()
    deduped: list[ToolError] = []
    for error in errors:
        key = (error.tool, error.message)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(error)
    return deduped


def source_preflight_errors(files: list[Path], root: Path) -> list[ToolError]:
    errors: list[ToolError] = []
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            tool = "python-ast" if path.suffix in PYTHON_EXTENSIONS else "source-read"
            errors.append(
                ToolError(
                    tool,
                    f"{relative_path(path, root)} could not be read as UTF-8 source: {exc}",
                )
            )
            continue
        if path.suffix not in PYTHON_EXTENSIONS:
            continue
        try:
            ast.parse(source)
        except SyntaxError as exc:
            errors.append(
                ToolError(
                    "python-ast",
                    f"{relative_path(path, root)} could not be parsed by the Python runtime: {exc}",
                )
            )
    return errors


def with_fallback(outcome: DetectorOutcome, fallback: str) -> DetectorOutcome:
    if outcome.status not in {"missing", "failed", "ignored"}:
        return outcome
    return dataclasses.replace(outcome, coverage="fallback", fallback=fallback)


def apply_lizard_fallback(
    files: list[Path],
    root: Path,
    threshold: int,
    outcome: DetectorOutcome,
) -> tuple[list[Issue], DetectorOutcome]:
    python_files = [path for path in files if path.suffix in PYTHON_EXTENSIONS]
    if not python_files or outcome.status not in {"missing", "failed"}:
        return [], outcome
    issues = [
        issue
        for path in python_files
        for issue in scan_python_complexity_builtin(path, root, threshold)
    ]
    uncovered_files = tuple(
        relative_path(path, root)
        for path in files
        if path.suffix not in PYTHON_EXTENSIONS
    )
    fallback_outcome = with_fallback(outcome, "python_ast")
    return issues, dataclasses.replace(
        fallback_outcome,
        uncovered_files=uncovered_files,
    )


def detector_errors_for_scan(
    results: tuple[tuple[list[ToolError], DetectorOutcome], ...], require_tools: bool
) -> list[ToolError]:
    return [
        error
        for errors, outcome in results
        if require_tools or outcome.coverage == "none" or outcome.uncovered_files
        for error in errors
    ]


def scan_files(
    files: list[Path], root: Path, threshold: int, require_tools: bool
) -> tuple[list[Issue], list[ToolError], dict[str, DetectorOutcome]]:
    issues: list[Issue] = []
    tool_errors = source_preflight_errors(files, root)

    ruff_issues, ruff_errors, ruff_outcome = run_ruff(files, root, require_tools)
    eslint_issues, eslint_errors, eslint_outcome = run_eslint(files, root, require_tools)
    lizard_issues, lizard_errors, lizard_outcome = run_lizard(
        files, root, threshold, require_tools
    )
    issues.extend(ruff_issues)
    issues.extend(eslint_issues)
    issues.extend(lizard_issues)

    if any(path.suffix in PYTHON_EXTENSIONS for path in files):
        ruff_outcome = with_fallback(ruff_outcome, "builtin_literal_scan")

    eslint_files = [path for path in files if path.suffix in JS_TS_EXTENSIONS]
    has_typescript = any(path.suffix in TYPESCRIPT_EXTENSIONS for path in eslint_files)
    if eslint_files and not has_typescript:
        eslint_outcome = with_fallback(eslint_outcome, "builtin_literal_scan")

    fallback_issues, lizard_outcome = apply_lizard_fallback(
        files, root, threshold, lizard_outcome
    )
    issues.extend(fallback_issues)

    detector_results = (
        (ruff_errors, ruff_outcome),
        (eslint_errors, eslint_outcome),
        (lizard_errors, lizard_outcome),
    )
    tool_errors.extend(detector_errors_for_scan(detector_results, require_tools))

    for path in files:
        issues.extend(scan_magic_values_builtin(path, root))
        issues.extend(scan_python_public_api_docstrings(path, root))
        issues.extend(scan_python_pass_through_functions(path, root))

    outcomes = {
        "ruff": ruff_outcome,
        "eslint": eslint_outcome,
        "lizard": lizard_outcome,
    }
    return dedupe_issues(issues), dedupe_tool_errors(tool_errors), outcomes


def render_feedback(
    issues: list[Issue],
    tool_errors: list[ToolError],
    skipped_files: list[SkippedFile],
    files: list[Path],
    ratchet: dict[str, Any],
    max_issues: int,
    decision_outcome: str,
) -> str:
    lines: list[str] = []
    if tool_errors:
        lines.append("Quality gate setup failed:")
        for error in tool_errors:
            lines.append(f"- {error.tool}: {error.message}")
    ratchet_violations = ratchet.get("violations", [])
    if ratchet_violations:
        lines.append(f"Quality ratchet found {len(ratchet_violations)} regression(s):")
        for violation in ratchet_violations[:max_issues]:
            lines.append(
                f"- {violation['file_path']}: {violation['metric']} "
                f"{violation['baseline']} -> {violation['current']}"
            )
    if issues:
        lines.append(f"Quality gate found {len(issues)} issue(s):")
        for issue in issues[:max_issues]:
            lines.append(
                f"- {issue.rule_id} [{issue.severity}/{issue.suggested_action}] "
                f"{issue.file_path}:{issue.start_line}: {issue.message}"
            )
            if issue.code_snippet:
                lines.append(f"  code: {issue.code_snippet}")
        remaining = len(issues) - max_issues
        if remaining > 0:
            lines.append(f"- ... {remaining} more issue(s) omitted")
    if skipped_files and not files and not issues and not tool_errors and not ratchet_violations:
        lines.append("Quality gate did not scan any supported files:")
        for skipped in skipped_files[:max_issues]:
            lines.append(f"- {skipped.path or '<empty>'}: {skipped.reason}")
    if issues or ratchet_violations:
        disposition = (
            "Fix the blocking findings before continuing."
            if decision_outcome == "block"
            else "These findings are non-blocking; keep them visible for follow-up."
        )
        lines.append(
            f"{disposition} Intentional magic literals still require a narrow "
            "ALLOW_MAGIC_NUMBER: reason, ticket comment."
        )
    return "\n".join(lines)


def build_report(
    issues: list[Issue],
    tool_errors: list[ToolError],
    files: list[Path],
    skipped_files: list[SkippedFile],
    root: Path,
    rules: dict[str, Rule],
    metrics: dict[str, Any],
    ratchet: dict[str, Any],
    run_id: str,
    started_at: float,
    source: dict[str, Any],
    detectors: dict[str, dict[str, Any]],
    decision: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    ratchet_violations = ratchet.get("violations", [])
    status = {
        "error": "error",
        "block": "fail",
        "incomplete": "incomplete",
    }.get(decision["outcome"], "pass")
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "gate": "post_tool_use_quality_gate",
        "status": status,
        "run_id": run_id,
        "rule_version": RULE_VERSION,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "duration_ms": int((time.monotonic() - started_at) * MILLISECONDS_PER_SECOND),
        "root": root.as_posix(),
        "source": source,
        "decision": decision,
        "policy": policy,
        "detectors": detectors,
        "scanned_files": [relative_path(path, root) for path in files],
        "skipped_files": [dataclasses.asdict(skipped) for skipped in skipped_files],
        "rules_loaded": sorted(rules),
        "metrics": metrics,
        "ratchet": ratchet,
        "issues": [issue.to_schema() for issue in issues],
        "tool_errors": [dataclasses.asdict(error) for error in tool_errors],
        "summary": {
            "issue_count": len(issues),
            "tool_error_count": len(tool_errors),
            "ratchet_violation_count": len(ratchet_violations),
            "scanned_file_count": len(files),
            "skipped_file_count": len(skipped_files),
            **decision["enforcement_counts"],
        },
    }


def build_decision(
    issues: list[Issue],
    tool_errors: list[ToolError],
    files: list[Path],
    ratchet: dict[str, Any],
) -> dict[str, Any]:
    counts = {"block_count": 0, "warn_count": 0, "observe_count": 0}
    rule_ids: dict[str, set[str]] = {"block": set(), "warn": set(), "observe": set()}
    for issue in issues:
        key = f"{issue.enforcement}_count"
        counts[key] += 1
        rule_ids[issue.enforcement].add(issue.rule_id)

    if tool_errors:
        outcome = "error"
    elif not files and not issues and not ratchet.get("violations"):
        outcome = "incomplete"
    elif ratchet.get("violations") or counts["block_count"]:
        outcome = "block"
    elif counts["warn_count"]:
        outcome = "warn"
    elif counts["observe_count"]:
        outcome = "observe"
    else:
        outcome = "pass"
    return {
        "outcome": outcome,
        "enforcement_counts": counts,
        "rule_ids": {key: sorted(value) for key, value in rule_ids.items()},
    }


def main(argv: list[str]) -> int:
    started_at = time.monotonic()
    run_id = str(uuid.uuid4())
    args = parse_args(argv)
    event: dict[str, Any] | None = None
    input_errors: list[ToolError] = []

    if args.doctor:
        root, root_errors = request_root(args, None, Path.cwd())
        return run_doctor(args, root, root_errors)

    if args.hook:
        try:
            event = load_hook_event()
        except ValueError as exc:
            input_errors.append(ToolError("hook-input", str(exc)))

    request, request_errors = build_quality_gate_request(args, event, Path.cwd())
    input_errors.extend(request_errors)
    root = request.root
    rules, rule_errors = load_scan_rules(args.rules_dir)
    policy, policy_errors = effective_policy(request, rules)
    policy["scan_profile"] = args.scan_profile
    rule_errors.extend(policy_errors)

    files, skipped_files, path_errors = resolve_scan_files(list(request.files), root)
    files, profile_skipped, profile_errors = enforce_scan_profile(
        files, args.scan_profile, root
    )
    skipped_files.extend(profile_skipped)
    input_errors.extend([*path_errors, *profile_errors])

    metrics = collect_quality_metrics(files, root)
    ratchet, ratchet_errors = evaluate_ratchet(metrics, request.baseline_path)
    detectors = detector_inventory(root)
    issues, tool_errors, detector_outcomes = scan_files(
        files, root, policy["complexity_threshold"], request.strict
    )
    for detector, outcome in detector_outcomes.items():
        detectors[detector]["run"] = outcome.to_schema()
    all_errors = dedupe_tool_errors(
        [*input_errors, *rule_errors, *tool_errors, *ratchet_errors]
    )
    if rules:
        missing_issue_rules = sorted({issue.rule_id for issue in issues} - set(rules))
        if missing_issue_rules:
            all_errors.append(
                ToolError(
                    "rule-config",
                    f"Missing metadata for emitted rule(s): {', '.join(missing_issue_rules)}",
                )
            )
        issues = apply_rule_metadata(issues, rules)

    source = report_source(request)
    decision = build_decision(issues, all_errors, files, ratchet)
    report = build_report(
        issues,
        all_errors,
        files,
        skipped_files,
        root,
        rules,
        metrics,
        ratchet,
        run_id,
        started_at,
        source,
        detectors,
        decision,
        policy,
    )

    if args.format == "json":
        print(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=JSON_INDENT,
            )
        )
    elif decision["outcome"] != "pass":
        print(
            render_feedback(
                issues,
                all_errors,
                skipped_files,
                files,
                ratchet,
                args.max_issues,
                decision["outcome"],
            ),
            file=sys.stderr,
        )

    if decision["outcome"] in {"error", "block", "incomplete"}:
        return 2 if args.hook else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
