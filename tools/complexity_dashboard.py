#!/usr/bin/env python3
"""Build APOSD_02a complexity signals from local repository evidence."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import itertools
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "complexity-dashboard/v1"
DEFAULT_ISSUE_PATTERN = r"(?:\b(?:issue|spec|adr)[:=]\s*|#)([A-Za-z0-9][A-Za-z0-9_.-]*)"
EXCLUDED_PATH_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}
EXCLUDED_SUFFIXES = {
    ".lock",
    ".min.css",
    ".min.js",
    ".pyc",
}
EXCLUDED_FILENAMES = {
    ".DS_Store",
}
TOP_LIMIT = 10


def run_git(repo: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def iter_commits(repo: Path, since: str | None, until: str) -> list[dict[str, str]]:
    revision = f"{since}..{until}" if since else until
    output = run_git(repo, ["log", "--reverse", "--format=%H%x00%s", revision])
    commits: list[dict[str, str]] = []
    for line in output.splitlines():
        if not line:
            continue
        commit_hash, _, subject = line.partition("\0")
        commits.append({"hash": commit_hash, "subject": subject})
    return commits


def changed_files_for_commit(repo: Path, commit_hash: str) -> list[str]:
    output = run_git(repo, ["show", "--format=", "--name-only", "--diff-filter=ACMRT", commit_hash])
    files = []
    for raw_path in output.splitlines():
        path = raw_path.strip()
        if path and not is_excluded_path(path):
            files.append(path)
    return sorted(set(files))


def is_excluded_path(path: str) -> bool:
    candidate = Path(path)
    if candidate.name in EXCLUDED_FILENAMES:
        return True
    if any(part in EXCLUDED_PATH_PARTS for part in candidate.parts):
        return True
    return any(path.endswith(suffix) for suffix in EXCLUDED_SUFFIXES)


def logical_change_id(subject: str, issue_re: re.Pattern[str], commit_hash: str) -> tuple[str, bool]:
    match = issue_re.search(subject)
    if match:
        return match.group(1), False
    return f"commit:{commit_hash[:12]}", True


def module_for_path(path: str) -> str:
    parts = Path(path).parts
    if len(parts) > 1:
        return parts[0]
    return "root"


def top_items(counter: collections.Counter[str], limit: int = TOP_LIMIT) -> list[list[Any]]:
    return [[key, value] for key, value in counter.most_common(limit)]


def numeric_summary(values: list[int]) -> dict[str, int | float]:
    if not values:
        return {"average": 0, "median": 0, "max": 0}
    return {
        "average": sum(values) / len(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def build_change_amplification(
    repo: Path,
    since: str | None,
    until: str,
    issue_pattern: str,
) -> dict[str, Any]:
    issue_re = re.compile(issue_pattern, re.IGNORECASE)
    commits = iter_commits(repo, since, until)
    logical_changes: dict[str, dict[str, Any]] = {}
    file_counts: collections.Counter[str] = collections.Counter()
    cochange_counts: collections.Counter[tuple[str, str]] = collections.Counter()
    ungrouped_commit_count = 0

    for commit in commits:
        commit_hash = commit["hash"]
        files = changed_files_for_commit(repo, commit_hash)
        if not files:
            continue
        change_id, ungrouped = logical_change_id(commit["subject"], issue_re, commit_hash)
        if ungrouped:
            ungrouped_commit_count += 1
        entry = logical_changes.setdefault(
            change_id,
            {"commits": [], "files": set(), "modules": set()},
        )
        entry["commits"].append(commit_hash)
        entry["files"].update(files)
        entry["modules"].update(module_for_path(path) for path in files)
        file_counts.update(files)
        cochange_counts.update(tuple(pair) for pair in itertools.combinations(files, 2))

    serializable_changes = {
        change_id: {
            "commits": entry["commits"],
            "files": sorted(entry["files"]),
            "modules": sorted(entry["modules"]),
            "file_count": len(entry["files"]),
            "module_count": len(entry["modules"]),
        }
        for change_id, entry in sorted(logical_changes.items())
    }
    file_summary = numeric_summary([entry["file_count"] for entry in serializable_changes.values()])
    module_summary = numeric_summary([entry["module_count"] for entry in serializable_changes.values()])

    return {
        "status": "present",
        "commit_count": sum(len(entry["commits"]) for entry in serializable_changes.values()),
        "logical_change_count": len(serializable_changes),
        "ungrouped_commit_count": ungrouped_commit_count,
        "changed_files": sorted(file_counts),
        "average_files_per_logical_change": file_summary["average"],
        "median_files_per_logical_change": file_summary["median"],
        "max_files_per_logical_change": file_summary["max"],
        "average_modules_per_logical_change": module_summary["average"],
        "median_modules_per_logical_change": module_summary["median"],
        "max_modules_per_logical_change": module_summary["max"],
        "logical_changes": serializable_changes,
        "top_changed_files": top_items(file_counts),
        "top_cochange_pairs": [
            [left, right, count] for (left, right), count in cochange_counts.most_common(TOP_LIMIT)
        ],
        "goodhart_note": (
            "Grouped by logical change id when present; ungrouped commits are reported separately "
            "so small commit slicing does not silently improve the signal."
        ),
    }


def as_non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return max(0, int(value))
    return 0


def read_records(path: Path) -> tuple[list[dict[str, Any]], int]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"{path}: {exc}") from exc
    stripped = text.strip()
    if not stripped:
        return [], 0
    malformed = 0
    if stripped.startswith("["):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return [], 1
        if not isinstance(payload, list):
            return [], 1
        records = [item for item in payload if isinstance(item, dict)]
        return records, len(payload) - len(records)

    records = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(payload, dict):
            records.append(payload)
        else:
            malformed += 1
    return records, malformed


def parse_context_log(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "status": "absent",
            "interpretation": (
                "No context log supplied; context footprint is unavailable and must not be inferred."
            ),
        }
    records, malformed = read_records(path)
    files = set()
    source_counts: collections.Counter[str] = collections.Counter()
    total_bytes = 0
    total_tokens = 0

    for record in records:
        file_path = record.get("path") or record.get("file")
        if isinstance(file_path, str) and file_path:
            files.add(file_path)
        source = record.get("source") if isinstance(record.get("source"), str) else "unknown"
        source_counts[source] += 1
        total_bytes += as_non_negative_int(record.get("bytes"))
        total_tokens += as_non_negative_int(record.get("tokens"))

    return {
        "status": "present",
        "read_count": len(records),
        "unique_file_count": len(files),
        "files": sorted(files),
        "total_bytes": total_bytes,
        "total_tokens": total_tokens,
        "source_counts": dict(sorted(source_counts.items())),
        "malformed_record_count": malformed,
        "interpretation": (
            "Context footprint is not a standalone quality score; interpret it with rework, "
            "review findings, and escaped defects."
        ),
    }


def files_from_defect(record: dict[str, Any]) -> list[str]:
    files = record.get("files")
    if isinstance(files, list):
        return sorted({item for item in files if isinstance(item, str) and item})
    file_path = record.get("file")
    if isinstance(file_path, str) and file_path:
        return [file_path]
    return []


def parse_defect_log(path: Path | None, changed_files: set[str]) -> dict[str, Any]:
    if path is None:
        return {
            "status": "absent",
            "interpretation": (
                "No defect log supplied; escaped defect correlation is unavailable and unknown "
                "sources must not be treated as zero defects."
            ),
        }
    records, malformed = read_records(path)
    source_counts: collections.Counter[str] = collections.Counter()
    defects_overlapping_recent_changes = []
    unknown_source_count = 0

    for index, record in enumerate(records, start=1):
        source = record.get("source") if isinstance(record.get("source"), str) else "unknown"
        if source == "unknown":
            unknown_source_count += 1
        source_counts[source] += 1
        defect_files = files_from_defect(record)
        if changed_files.intersection(defect_files):
            defect_id = record.get("id") if isinstance(record.get("id"), str) else f"defect:{index}"
            defects_overlapping_recent_changes.append(defect_id)

    return {
        "status": "present",
        "defect_count": len(records),
        "unknown_source_count": unknown_source_count,
        "source_counts": dict(sorted(source_counts.items())),
        "overlap_recent_changed_file_count": len(defects_overlapping_recent_changes),
        "defects_overlapping_recent_changes": defects_overlapping_recent_changes,
        "malformed_record_count": malformed,
        "interpretation": (
            "Escaped defect correlation is a periodic calibration signal; missing or unknown "
            "sources stay visible instead of being counted as clean."
        ),
    }


def build_dashboard(
    repo: Path,
    since: str | None = None,
    until: str = "HEAD",
    issue_pattern: str = DEFAULT_ISSUE_PATTERN,
    context_log: Path | None = None,
    defects: Path | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    amplification = build_change_amplification(repo, since, until, issue_pattern)
    changed_files = set(amplification["changed_files"])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "git_range": {
            "repo": str(repo),
            "since": since,
            "until": until,
        },
        "change_amplification": amplification,
        "context_footprint": parse_context_log(context_log),
        "escaped_defect_correlation": parse_defect_log(defects, changed_files),
        "notes": [
            "APOSD_02a signals are periodic design-calibration signals, not single-turn merge blockers.",
            "Round-level gates should use immediately computable quantities such as complexity, smells, coverage, and test results.",
        ],
    }


def render_text(report: dict[str, Any]) -> str:
    amplification = report["change_amplification"]
    context = report["context_footprint"]
    defects = report["escaped_defect_correlation"]
    lines = [
        f"schema: {report['schema_version']}",
        f"range: {report['git_range']['since'] or '<root>'}..{report['git_range']['until']}",
        "",
        "change_amplification:",
        f"  commits: {amplification['commit_count']}",
        f"  logical_changes: {amplification['logical_change_count']}",
        f"  avg_files_per_change: {amplification['average_files_per_logical_change']}",
        f"  max_files_per_change: {amplification['max_files_per_logical_change']}",
        f"  ungrouped_commits: {amplification['ungrouped_commit_count']}",
        "",
        "context_footprint:",
        f"  status: {context['status']}",
        f"  reads: {context.get('read_count', 0)}",
        f"  unique_files: {context.get('unique_file_count', 0)}",
        f"  bytes: {context.get('total_bytes', 0)}",
        f"  tokens: {context.get('total_tokens', 0)}",
        "",
        "escaped_defect_correlation:",
        f"  status: {defects['status']}",
        f"  defects: {defects.get('defect_count', 0)}",
        f"  unknown_sources: {defects.get('unknown_source_count', 0)}",
        f"  overlaps_recent_changes: {defects.get('overlap_recent_changed_file_count', 0)}",
    ]
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."), help="Git repository to inspect")
    parser.add_argument("--since", help="Start revision for the git range, excluded")
    parser.add_argument("--until", default="HEAD", help="End revision for the git range")
    parser.add_argument(
        "--issue-pattern",
        default=DEFAULT_ISSUE_PATTERN,
        help="Regex with one capture group for issue/spec/ADR ids in commit subjects",
    )
    parser.add_argument("--context-log", type=Path, help="Optional JSON/JSONL agent context log")
    parser.add_argument("--defects", type=Path, help="Optional JSON/JSONL escaped defect log")
    parser.add_argument("--format", choices=("json", "text"), default="text")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        report = build_dashboard(
            repo=args.repo,
            since=args.since,
            until=args.until,
            issue_pattern=args.issue_pattern,
            context_log=args.context_log,
            defects=args.defects,
        )
    except RuntimeError as exc:
        print(f"complexity_dashboard: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
