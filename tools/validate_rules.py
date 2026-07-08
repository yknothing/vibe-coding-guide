#!/usr/bin/env python3
"""Validate the constrained rule YAML files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.rule_loader import RuleValidationError, load_rules


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate rule YAML files.")
    parser.add_argument("rules_dir", nargs="?", default="rules")
    parser.add_argument("--require", action="append", default=[], help="Rule id that must exist.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        rules = load_rules(Path(args.rules_dir))
        missing = sorted(set(args.require) - set(rules))
        if missing:
            raise RuleValidationError(f"{args.rules_dir}: missing required rule(s): {', '.join(missing)}")
    except RuleValidationError as exc:
        print(f"rule validation failed: {exc}", file=sys.stderr)
        return 1

    print(f"validated {len(rules)} rule(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
