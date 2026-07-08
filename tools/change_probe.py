#!/usr/bin/env python3
"""Score APOSD_05 change-probe blast radius from a Git diff."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "change-probe/v1"
PYTHON_SIGNATURE_RE = re.compile(r"^\s*(?P<kind>async\s+def|def|class)\s+(?P<symbol>[A-Za-z_]\w*)")
JS_TS_SIGNATURE_RE = re.compile(
    r"^\s*(?:export\s+)?(?:(?P<kind>async\s+function|function|class|interface|type)\s+"
    r"(?P<symbol>[A-Za-z_$][\w$]*))"
)


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


def changed_files(repo: Path, base: str, head: str) -> list[str]:
    output = run_git(repo, ["diff", "--name-only", "--diff-filter=ACMRT", f"{base}..{head}"])
    return sorted(path for path in output.splitlines() if path.strip())


def module_for_path(path: str) -> str:
    parts = Path(path).parts
    if len(parts) > 1:
        return parts[0]
    return "root"


def signature_for_line(path: str, line: str) -> dict[str, str] | None:
    suffix = Path(path).suffix
    regex = PYTHON_SIGNATURE_RE if suffix == ".py" else JS_TS_SIGNATURE_RE
    match = regex.match(line)
    if not match:
        return None
    kind = " ".join(match.group("kind").split())
    return {
        "file_path": path,
        "kind": kind,
        "symbol": match.group("symbol"),
    }


def interface_signature_changes(repo: Path, base: str, head: str) -> list[dict[str, str]]:
    output = run_git(repo, ["diff", "--unified=0", f"{base}..{head}"])
    current_file = ""
    changes: dict[tuple[str, str, str], dict[str, str]] = {}
    for raw_line in output.splitlines():
        if raw_line.startswith("+++ b/"):
            current_file = raw_line[len("+++ b/") :]
            continue
        if not current_file or raw_line.startswith(("+++", "---")):
            continue
        if not raw_line.startswith(("+", "-")):
            continue
        signature = signature_for_line(current_file, raw_line[1:])
        if signature is None:
            continue
        key = (signature["file_path"], signature["kind"], signature["symbol"])
        changes[key] = signature
    return [changes[key] for key in sorted(changes)]


def build_probe_report(repo: Path, base: str, head: str, scenario_id: str) -> dict[str, Any]:
    repo = repo.resolve()
    files = changed_files(repo, base, head)
    modules = sorted({module_for_path(path) for path in files})
    signatures = interface_signature_changes(repo, base, head)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "scenario_id": scenario_id,
        "git_range": {
            "repo": str(repo),
            "base": base,
            "head": head,
        },
        "blast_radius": {
            "touched_file_count": len(files),
            "touched_module_count": len(modules),
            "interface_signature_change_count": len(signatures),
            "files": files,
            "modules": modules,
            "interface_signature_changes": signatures,
        },
        "notes": [
            "This scores a completed change probe; it does not prove the probe was run by an independent context.",
            "Scenario selection, independent execution, and pool rotation must be enforced by the surrounding harness.",
        ],
    }


def render_text(report: dict[str, Any]) -> str:
    radius = report["blast_radius"]
    lines = [
        f"schema: {report['schema_version']}",
        f"scenario: {report['scenario_id']}",
        f"range: {report['git_range']['base']}..{report['git_range']['head']}",
        "",
        "blast_radius:",
        f"  touched_files: {radius['touched_file_count']}",
        f"  touched_modules: {radius['touched_module_count']}",
        f"  interface_signature_changes: {radius['interface_signature_change_count']}",
    ]
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."), help="Git repository to inspect")
    parser.add_argument("--base", required=True, help="Base revision before the probe")
    parser.add_argument("--head", default="HEAD", help="Head revision after the probe")
    parser.add_argument("--scenario-id", required=True, help="Scenario/probe id")
    parser.add_argument("--format", choices=("json", "text"), default="text")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        report = build_probe_report(args.repo, args.base, args.head, args.scenario_id)
    except RuntimeError as exc:
        print(f"change_probe: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
