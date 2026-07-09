#!/usr/bin/env python3
"""PostToolUse quality gate for magic values and function complexity."""

from __future__ import annotations

import argparse
import ast
import csv
import dataclasses
import datetime as dt
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
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
    complexity_threshold: int

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
        default=int(os.environ.get("VCG_COMPLEXITY_THRESHOLD", DEFAULT_COMPLEXITY_THRESHOLD)),
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
                metric_values=issue.metric_values,
                code_snippet=issue.code_snippet,
            )
        )
    return hydrated


def determine_root(args: argparse.Namespace, event: dict[str, Any] | None) -> Path:
    raw_root = args.root or os.environ.get("CLAUDE_PROJECT_DIR")
    if raw_root is None and event is not None:
        raw_root = event.get("cwd")
    return Path(raw_root or os.getcwd()).expanduser().resolve()


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


def request_baseline_path(raw_path: Path | None, root: Path) -> Path | None:
    if raw_path is None:
        return None
    path = raw_path.expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve(strict=False)


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

    request = QualityGateRequest(
        schema_version=REQUEST_SCHEMA_VERSION,
        root=root,
        files=tuple(raw_files),
        mode=mode,
        adapter=adapter,
        hook_event_name=hook_event_name,
        tool_name=tool_name,
        baseline_path=request_baseline_path(args.ratchet_baseline, root),
        strict=args.require_tools,
        complexity_threshold=args.complexity_threshold,
    )
    return request, errors


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


def command_version(command: str) -> str | None:
    result, error = run_detector([command, "--version"])
    if error or result is None or result.returncode != 0:
        return None
    version = (result.stdout or result.stderr).strip().splitlines()
    return version[0] if version else None


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


def detector_inventory(include_install: bool = False) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for detector in REQUIRED_DETECTORS:
        path = shutil.which(detector)
        info: dict[str, Any] = {
            "available": path is not None,
            "path": path,
            "version": command_version(path) if path else None,
        }
        if include_install:
            info["install"] = detector_install_info(detector)
        inventory[detector] = info
    return inventory


def detector_remediation(detector: str) -> str:
    info = detector_install_info(detector)
    return (
        f"{info['description']} {info['purpose']} "
        f"Install with `{info['install_command']}` and verify with `{info['verify_command']}`. "
        f"{info['security_note']}"
    )


def detector_install_plan(detectors: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    return [
        detector_install_info(detector)
        for detector in REQUIRED_DETECTORS
        if not detectors.get(detector, {}).get("available")
    ]


def quick_install_commands(install_plan: list[dict[str, str]]) -> list[str]:
    missing = {item["tool"] for item in install_plan}
    commands: list[str] = []
    python_tools = [detector for detector in ("ruff", "lizard") if detector in missing]
    if python_tools:
        commands.append(f"python3 -m pip install --upgrade {' '.join(python_tools)}")
    if "eslint" in missing:
        commands.append("npm install -g eslint")
    for item in install_plan:
        command = item["install_command"]
        if item["tool"] not in {"ruff", "lizard", "eslint"} and command not in commands:
            commands.append(command)
    return commands


def report_source(request: QualityGateRequest) -> dict[str, Any]:
    return request.source_schema()


def doctor_status(checks: list[DoctorCheck]) -> str:
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def build_doctor_report(root: Path, rules_dir: Path, require_tools: bool) -> dict[str, Any]:
    checks: list[DoctorCheck] = []
    checks.append(
        DoctorCheck(
            id="python.runtime",
            status="pass",
            message=f"Python runtime: {platform.python_version()}",
            detail={"executable": sys.executable, "version": platform.python_version()},
        )
    )
    checks.append(
        DoctorCheck(
            id="project.root",
            status="pass" if root.exists() else "fail",
            message=f"Project root {'exists' if root.exists() else 'does not exist'}: {root}",
            detail={"root": root.as_posix()},
            remediation=None if root.exists() else "Pass --root or run the command from the project root.",
        )
    )
    checks.append(
        DoctorCheck(
            id="script.executable",
            status="pass" if os.access(__file__, os.X_OK) else "warn",
            message=(
                "Hook script is executable."
                if os.access(__file__, os.X_OK)
                else "Hook script is not executable; invoke it with python3 or chmod +x it."
            ),
            detail={"path": Path(__file__).resolve().as_posix()},
            remediation=None if os.access(__file__, os.X_OK) else "Run via `python3` or set executable bit.",
        )
    )

    loaded_rules: list[str] = []
    try:
        loaded_rules = sorted(load_rules(rules_dir))
        checks.append(
            DoctorCheck(
                id="rules.load",
                status="pass",
                message=f"Loaded {len(loaded_rules)} rule(s).",
                detail={"rules_dir": rules_dir.as_posix(), "rules": loaded_rules},
                remediation=None,
            )
        )
    except RuleValidationError as exc:
        checks.append(
            DoctorCheck(
                id="rules.load",
                status="fail",
                message=str(exc),
                detail={"rules_dir": rules_dir.as_posix()},
                remediation="Fix the rule YAML or pass a valid --rules-dir.",
            )
        )

    detectors = detector_inventory(include_install=True)
    install_plan = detector_install_plan(detectors)
    for detector, info in detectors.items():
        available = bool(info["available"])
        checks.append(
            DoctorCheck(
                id=f"detector.{detector}",
                status="pass" if available else "fail" if require_tools else "warn",
                message=(
                    f"{detector} found at {info['path']}"
                    if available
                    else f"{detector} not found; strict --require-tools mode will fail closed."
                ),
                detail=info,
                remediation=None if available else detector_remediation(detector),
            )
        )

    strict_ready = all(bool(info["available"]) for info in detectors.values()) and all(
        check.status != "fail" for check in checks
    )
    status = doctor_status(checks)
    return {
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "status": status,
        "strict_ready": strict_ready,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "root": root.as_posix(),
        "rules_loaded": loaded_rules,
        "detectors": detectors,
        "tool_catalog": [detector_install_info(detector) for detector in REQUIRED_DETECTORS],
        "install_plan": install_plan,
        "quick_install_commands": quick_install_commands(install_plan),
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
    if report.get("install_plan"):
        lines.append("Install missing detector tools:")
        for item in report["install_plan"]:
            lines.append(f"- {item['tool']}: {item['description']} {item['purpose']}")
            lines.append(f"  install: {item['install_command']}")
            lines.append(f"  verify: {item['verify_command']}")
        if report.get("quick_install_commands"):
            lines.append("Quick install commands:")
            for command in report["quick_install_commands"]:
                lines.append(f"- {command}")
        lines.append(
            "Safety: use PyPI/npm or approved internal mirrors. Do not use curl | sh installers."
        )
        lines.append(
            "Manual commands only: adapters must not run them without explicit user approval."
        )
        lines.append("After installing: Rerun --doctor --require-tools.")
    lines.append("Next steps:")
    for step in report["next_steps"]:
        lines.append(f"- {step}")
    return "\n".join(lines)


def run_doctor(args: argparse.Namespace, root: Path) -> int:
    report = build_doctor_report(root, Path(args.rules_dir), args.require_tools)
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


def resolve_scan_files(raw_paths: list[str], root: Path) -> tuple[list[Path], list[SkippedFile]]:
    files: list[Path] = []
    skipped: list[SkippedFile] = []
    seen: set[Path] = set()
    for raw_path in raw_paths:
        if not raw_path:
            skipped.append(SkippedFile(path="", reason="empty_path"))
            continue
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve(strict=False)
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
    return files, skipped


def normalize_scan_files(raw_paths: list[str], root: Path) -> list[Path]:
    files, _ = resolve_scan_files(raw_paths, root)
    return files


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
    ruff = shutil.which("ruff")
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
    has_messages = any(True for _ in iter_eslint_messages(payload))
    if returncode == 1 and not has_messages:
        return "ESLint exited 1 but produced no diagnostics."
    if returncode == 0 and has_messages:
        return "ESLint exited 0 but produced diagnostics."
    return None


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


def run_eslint(
    files: list[Path], root: Path, _require_tools: bool
) -> tuple[list[Issue], list[ToolError], DetectorOutcome]:
    js_files = [path for path in files if path.suffix in JS_TS_EXTENSIONS]
    outcome_files = tuple(relative_path(path, root) for path in js_files)
    if not js_files:
        return [], [], DetectorOutcome("not_applicable", "none", ())
    eslint = shutil.which("eslint")
    if not eslint:
        message = "ESLint is required for JS/TS no-magic-numbers checks."
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
    base_command = [eslint, "--rule", rule_config, "--format", "json"]
    command_variants = [
        [*base_command, "--no-config-lookup", *[str(path) for path in js_files]],
        [*base_command, "--no-eslintrc", *[str(path) for path in js_files]],
    ]

    last_error = ""
    failure_status = "failed"
    for command in command_variants:
        result, timeout_error = run_detector(command, cwd=root)
        if timeout_error:
            failure_status = "failed"
            last_error = timeout_error.message
            continue
        assert result is not None
        if result.returncode not in {0, 1}:
            failure_status = "failed"
            last_error = result.stderr.strip() or "ESLint failed."
            continue
        if result.stdout.strip():
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                failure_status = "failed"
                last_error = "ESLint produced non-JSON output."
                continue
            if not isinstance(payload, list):
                failure_status = "failed"
                last_error = "ESLint JSON output must be an array."
                continue
            diagnostic_status, diagnostic_message = eslint_coverage_diagnostic(
                payload, js_files, root
            )
            if diagnostic_status is not None:
                failure_status = diagnostic_status
                last_error = diagnostic_message or "ESLint did not lint every requested file."
                continue
            consistency_error = eslint_exit_consistency_error(payload, result.returncode)
            if consistency_error:
                failure_status = "failed"
                last_error = consistency_error
                continue
            return (
                parse_eslint_payload(payload, root),
                [],
                DetectorOutcome("succeeded", "complete", outcome_files),
            )
        failure_status = "failed"
        last_error = result.stderr.strip()
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
    lizard = shutil.which("lizard")
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
        lines.append(
            "Fix the reported literals/complexity before continuing, or add a narrow "
            "ALLOW_MAGIC_NUMBER: reason, ticket comment for an intentional magic literal."
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
) -> dict[str, Any]:
    ratchet_violations = ratchet.get("violations", [])
    no_scanned_files = not files and not issues and not tool_errors and not ratchet_violations
    status = (
        "error"
        if tool_errors
        else "fail"
        if issues or ratchet_violations
        else "incomplete"
        if no_scanned_files
        else "pass"
    )
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
        },
    }


def main(argv: list[str]) -> int:
    started_at = time.monotonic()
    run_id = str(uuid.uuid4())
    args = parse_args(argv)
    event: dict[str, Any] | None = None
    input_errors: list[ToolError] = []

    if args.doctor:
        root = determine_root(args, None)
        return run_doctor(args, root)

    if args.hook:
        try:
            event = load_hook_event()
        except ValueError as exc:
            input_errors.append(ToolError("hook-input", str(exc)))

    request, request_errors = build_quality_gate_request(args, event, Path.cwd())
    input_errors.extend(request_errors)
    root = request.root
    rule_errors: list[ToolError] = []
    rules: dict[str, Rule] = {}
    try:
        rules = load_rules(Path(args.rules_dir))
    except RuleValidationError as exc:
        rule_errors.append(ToolError("rule-config", str(exc)))

    files, skipped_files = resolve_scan_files(list(request.files), root)

    metrics = collect_quality_metrics(files, root)
    ratchet, ratchet_errors = evaluate_ratchet(metrics, request.baseline_path)
    detectors = detector_inventory()
    issues, tool_errors, detector_outcomes = scan_files(
        files, root, request.complexity_threshold, request.strict
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
    )

    if args.format == "json":
        print(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=JSON_INDENT,
            )
        )
    elif report["status"] != "pass":
        print(
            render_feedback(issues, all_errors, skipped_files, files, ratchet, args.max_issues),
            file=sys.stderr,
        )

    if report["status"] != "pass":
        return 2 if args.hook else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
