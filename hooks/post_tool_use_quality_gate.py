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
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from tools.rule_loader import Rule, RuleValidationError, load_rules


RULE_VERSION = "2025.v1.0.cn"
REPORT_SCHEMA_VERSION = "quality-gate-report/v1"
TOOL_TIMEOUT_SECONDS = 30
EDIT_TOOLS = {"Edit", "Write", "MultiEdit"}
DEFAULT_COMPLEXITY_THRESHOLD = 10
DEFAULT_MAX_ISSUES = 25
MAX_TOTAL_METRICS = {"python_max_cyclomatic_complexity"}
RATCHET_METRICS = {
    "hardcoded_endpoint_count",
    "magic_literal_count",
    "python_max_cyclomatic_complexity",
}

PYTHON_EXTENSIONS = {".py"}
JS_TS_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan PostToolUse-edited files for magic values and complexity."
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
        return json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid hook JSON: {exc}") from exc


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


def run_detector(command: list[str]) -> tuple[subprocess.CompletedProcess[str] | None, ToolError | None]:
    tool = Path(command[0]).name
    try:
        return (
            subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=TOOL_TIMEOUT_SECONDS,
            ),
            None,
        )
    except subprocess.TimeoutExpired:
        return None, ToolError(tool, f"{tool} timed out after {TOOL_TIMEOUT_SECONDS}s.")


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


def event_scan_files(event: dict[str, Any], root: Path) -> tuple[list[Path], list[SkippedFile], list[ToolError]]:
    tool_name = str(event.get("tool_name", ""))
    raw_paths = collect_path_values(event.get("tool_input", {}))
    errors: list[ToolError] = []

    if tool_name == "Bash" and not raw_paths:
        raw_paths = git_changed_files(root)
    elif tool_name in EDIT_TOOLS and not raw_paths:
        errors.append(
            ToolError(
                "hook-input",
                f"PostToolUse payload for {tool_name} did not include a file path to scan.",
            )
        )

    files, skipped = resolve_scan_files(raw_paths, root)
    return files, skipped, errors


def relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


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
    except UnicodeDecodeError:
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
    except (SyntaxError, UnicodeDecodeError):
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
    except (SyntaxError, UnicodeDecodeError):
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
    except (SyntaxError, UnicodeDecodeError):
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
    except (SyntaxError, UnicodeDecodeError):
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


def run_ruff(files: list[Path], root: Path, require_tools: bool) -> tuple[list[Issue], list[ToolError], bool]:
    python_files = [path for path in files if path.suffix in PYTHON_EXTENSIONS]
    if not python_files:
        return [], [], True
    ruff = shutil.which("ruff")
    if not ruff:
        return [], [ToolError("ruff", "Ruff is required for Python PLR2004 magic-value checks.")], False

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
        ]
    )
    if timeout_error:
        return [], [timeout_error], True
    assert result is not None
    if require_tools and result.returncode not in {0, 1}:
        return [], [ToolError("ruff", result.stderr.strip() or "Ruff failed.")], True
    if not result.stdout.strip():
        if result.returncode not in {0, 1}:
            return [], [ToolError("ruff", result.stderr.strip() or "Ruff failed without JSON output.")], True
        return [], [], True

    try:
        diagnostics = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], [ToolError("ruff", "Ruff produced non-JSON output.")], True
    if not isinstance(diagnostics, list):
        return [], [ToolError("ruff", "Ruff JSON output must be an array.")], True

    issues: list[Issue] = []
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            return [], [ToolError("ruff", "Ruff JSON diagnostics must be objects.")], True
        if diagnostic.get("code") != "PLR2004":
            continue
        filename = Path(str(diagnostic.get("filename", ""))).resolve()
        location = diagnostic.get("location") or {}
        row = int(location.get("row") or 1)
        issues.append(
            Issue(
                rule_id="IMP_004",
                severity="M",
                category="IMP",
                file_path=relative_path(filename, root),
                start_line=row,
                end_line=row,
                message=diagnostic.get("message") or "Magic numeric literal detected by Ruff PLR2004.",
                detailed_explanation=(
                    "Ruff PLR2004 detected an unnamed comparison literal; "
                    "replace it with a named constant or a configuration value."
                ),
                suggested_action="FIX",
                code_snippet=None,
                metric_values={"detector": "ruff", "code": "PLR2004"},
            )
        )
    return issues, [], True


def run_eslint(files: list[Path], root: Path, require_tools: bool) -> tuple[list[Issue], list[ToolError], bool]:
    js_files = [path for path in files if path.suffix in JS_TS_EXTENSIONS]
    if not js_files:
        return [], [], True
    eslint = shutil.which("eslint")
    if not eslint:
        return [], [ToolError("eslint", "ESLint is required for JS/TS no-magic-numbers checks.")], False

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
    for command in command_variants:
        result, timeout_error = run_detector(command)
        if timeout_error:
            last_error = timeout_error.message
            continue
        assert result is not None
        if require_tools and result.returncode not in {0, 1}:
            last_error = result.stderr.strip() or "ESLint failed."
            continue
        if result.stdout.strip():
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                last_error = "ESLint produced non-JSON output."
                continue
            if not isinstance(payload, list):
                last_error = "ESLint JSON output must be an array."
                continue
            return parse_eslint_payload(payload, root), [], True
        last_error = result.stderr.strip()
    return [], [ToolError("eslint", last_error or "ESLint failed without JSON output.")], True


def parse_eslint_payload(payload: Any, root: Path) -> list[Issue]:
    issues: list[Issue] = []
    if not isinstance(payload, list):
        return issues
    for file_result in payload:
        if not isinstance(file_result, dict):
            continue
        filename = Path(str(file_result.get("filePath", ""))).resolve()
        for message in file_result.get("messages", []):
            if not isinstance(message, dict):
                continue
            if message.get("ruleId") != "no-magic-numbers":
                continue
            row = int(message.get("line") or 1)
            issues.append(
                Issue(
                    rule_id="IMP_004",
                    severity="M",
                    category="IMP",
                    file_path=relative_path(filename, root),
                    start_line=row,
                    end_line=row,
                    message=message.get("message") or "Magic numeric literal detected by ESLint.",
                    detailed_explanation=(
                        "ESLint no-magic-numbers detected an unnamed numeric literal; "
                        "replace it with a named constant or a configuration value."
                    ),
                    suggested_action="FIX",
                    metric_values={"detector": "eslint", "rule": "no-magic-numbers"},
                )
            )
    return issues


def run_lizard(
    files: list[Path], root: Path, threshold: int, require_tools: bool
) -> tuple[list[Issue], list[ToolError], bool]:
    if not files:
        return [], [], True
    lizard = shutil.which("lizard")
    if not lizard:
        return [], [ToolError("lizard", "lizard is required for function complexity checks.")], False

    result, timeout_error = run_detector([lizard, "--csv", *[str(path) for path in files]])
    if timeout_error:
        return [], [timeout_error], True
    assert result is not None
    if require_tools and result.returncode not in {0, 1}:
        return [], [ToolError("lizard", result.stderr.strip() or "lizard failed.")], True
    if result.returncode not in {0, 1} and not result.stdout.strip():
        return [], [ToolError("lizard", result.stderr.strip() or "lizard failed without CSV output.")], True
    if require_tools and not result.stdout.strip():
        return [], [ToolError("lizard", "lizard produced empty CSV output.")], True

    issues: list[Issue] = []
    reader = csv.DictReader(io.StringIO(result.stdout))
    required_fields = {"CCN", "location", "file", "function"}
    if reader.fieldnames is None or not required_fields.issubset(set(reader.fieldnames)):
        return [], [ToolError("lizard", "lizard CSV output is missing required fields.")], True
    for row in reader:
        try:
            ccn = int(float(row.get("CCN", "0")))
        except ValueError:
            continue
        if ccn <= threshold:
            continue
        file_path = Path(row.get("file") or "").resolve()
        location = row.get("location") or "1"
        line_text = location.split(":", 1)[0]
        try:
            line = int(line_text)
        except ValueError:
            line = 1
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
    return issues, [], True


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


def scan_files(
    files: list[Path], root: Path, threshold: int, require_tools: bool
) -> tuple[list[Issue], list[ToolError]]:
    issues: list[Issue] = []
    tool_errors: list[ToolError] = []

    ruff_issues, ruff_errors, ruff_available = run_ruff(files, root, require_tools)
    eslint_issues, eslint_errors, eslint_available = run_eslint(files, root, require_tools)
    lizard_issues, lizard_errors, lizard_available = run_lizard(files, root, threshold, require_tools)
    issues.extend(ruff_issues)
    issues.extend(eslint_issues)
    issues.extend(lizard_issues)

    if require_tools:
        if not ruff_available:
            tool_errors.extend(ruff_errors)
        if not eslint_available:
            tool_errors.extend(eslint_errors)
        if not lizard_available:
            tool_errors.extend(lizard_errors)
        tool_errors.extend(
            error for error in [*ruff_errors, *eslint_errors, *lizard_errors] if error not in tool_errors
        )

    for path in files:
        issues.extend(scan_magic_values_builtin(path, root))
        issues.extend(scan_python_public_api_docstrings(path, root))
        issues.extend(scan_python_pass_through_functions(path, root))
        if not lizard_available and path.suffix in PYTHON_EXTENSIONS:
            issues.extend(scan_python_complexity_builtin(path, root, threshold))

    return dedupe_issues(issues), tool_errors


def render_feedback(
    issues: list[Issue],
    tool_errors: list[ToolError],
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
) -> dict[str, Any]:
    ratchet_violations = ratchet.get("violations", [])
    status = "error" if tool_errors else "fail" if issues or ratchet_violations else "pass"
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "gate": "post_tool_use_quality_gate",
        "status": status,
        "rule_version": RULE_VERSION,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "root": root.as_posix(),
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
    args = parse_args(argv)
    event: dict[str, Any] | None = None
    input_errors: list[ToolError] = []

    if args.hook:
        try:
            event = load_hook_event()
        except ValueError as exc:
            input_errors.append(ToolError("hook-input", str(exc)))

    root = determine_root(args, event)
    rule_errors: list[ToolError] = []
    rules: dict[str, Rule] = {}
    try:
        rules = load_rules(Path(args.rules_dir))
    except RuleValidationError as exc:
        rule_errors.append(ToolError("rule-config", str(exc)))

    skipped_files: list[SkippedFile] = []
    if args.files is not None:
        files, skipped_files = resolve_scan_files(args.files, root)
    elif event is not None:
        files, skipped_files, input_errors = event_scan_files(event, root)
    else:
        input_errors.append(ToolError("hook-input", "No --files provided and --hook was not set."))
        files = []

    metrics = collect_quality_metrics(files, root)
    ratchet, ratchet_errors = evaluate_ratchet(metrics, args.ratchet_baseline)
    issues, tool_errors = scan_files(files, root, args.complexity_threshold, args.require_tools)
    all_errors = [*input_errors, *rule_errors, *tool_errors, *ratchet_errors]
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

    if args.format == "json":
        print(
            json.dumps(
                build_report(issues, all_errors, files, skipped_files, root, rules, metrics, ratchet),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif issues or all_errors or ratchet.get("violations"):
        print(render_feedback(issues, all_errors, ratchet, args.max_issues), file=sys.stderr)

    if issues or all_errors or ratchet.get("violations"):
        return 2 if args.hook else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
