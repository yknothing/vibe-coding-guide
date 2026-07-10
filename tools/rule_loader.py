#!/usr/bin/env python3
"""Load the repository's constrained rule YAML files without external deps."""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any


RULE_ID_RE = re.compile(r"^[A-Z]{2,5}_\d{3}$")
REQUIRED_FIELDS = {"id", "lvl", "sev", "cat", "lang", "state", "met", "det", "act", "rat", "gate"}
ALLOWED_LVL = {"M", "S", "A"}
ALLOWED_SEV = {"B", "C", "H", "M", "L"}
ALLOWED_CAT = {"FND", "DSN", "IMP", "SEC", "CNC", "TST", "PRF", "MNT", "CSH", "RSRC"}
ALLOWED_ACT = {"RQR", "RCM", "FIX", "CNF", "EDU", "LOG", "WARN"}
ALLOWED_STATE = {"P", "T", "E", "D"}
ALLOWED_ENFORCEMENT = {"block", "warn", "observe"}
ALLOWED_DETECTOR_TOOLS = {
    "aih",
    "lzd",
    "sg",
    "spb",
    "pmd",
    "rfk",
    "esl",
    "sa",
    "git",
    "tst",
    "prf",
    "man",
    "sq",
    "pylint",
    "cppcheck",
    "clang-tidy",
    "roslyn",
    "rubocop",
    "rustc",
}
ALLOWED_AUTOFIX_TYPES = {
    "ai_patch",
    "script",
    "codemod",
    "ide_command",
    "regex_replace",
    "manual_assist",
    "tool_command",
}


class RuleValidationError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class Rule:
    id: str
    lvl: str
    sev: str
    cat: str
    lang: list[str]
    state: str
    met: dict[str, Any]
    det: list[dict[str, Any]]
    act: str
    rat: str
    autofix: dict[str, Any] | None = None
    gate: dict[str, Any] | None = None


def parse_rule_file(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.+)$", line)
        if not match:
            raise RuleValidationError(f"{path}:{line_number}: unsupported rule YAML syntax")
        key, raw_value = match.groups()
        if key in data:
            raise RuleValidationError(f"{path}:{line_number}: duplicate field `{key}`")
        data[key] = parse_value(raw_value, path, line_number)
    return data


def parse_value(raw_value: str, path: Path, line_number: int) -> Any:
    value = raw_value.strip()
    if value.startswith(('"', "[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuleValidationError(f"{path}:{line_number}: invalid JSON-compatible value: {exc}") from exc
    return value


def validate_rule_data(path: Path, data: dict[str, Any]) -> Rule:
    missing = REQUIRED_FIELDS - set(data)
    if missing:
        raise RuleValidationError(f"{path}: missing required field(s): {', '.join(sorted(missing))}")

    rule_id = expect_string(path, data, "id")
    if not RULE_ID_RE.match(rule_id):
        raise RuleValidationError(f"{path}: invalid id `{rule_id}`")
    if path.stem != rule_id:
        raise RuleValidationError(f"{path}: filename must match rule id `{rule_id}`")

    lvl = expect_enum(path, data, "lvl", ALLOWED_LVL)
    sev = expect_enum(path, data, "sev", ALLOWED_SEV)
    cat = expect_enum(path, data, "cat", ALLOWED_CAT)
    state = expect_enum(path, data, "state", ALLOWED_STATE)
    act = expect_enum(path, data, "act", ALLOWED_ACT)
    rat = expect_string(path, data, "rat")

    met = data["met"]
    if not isinstance(met, dict) or not met.get("type") or "expr" not in met:
        raise RuleValidationError(f"{path}: `met` must include `type` and `expr`")

    lang = data["lang"]
    if not isinstance(lang, list) or not lang or not all(isinstance(item, str) for item in lang):
        raise RuleValidationError(f"{path}: `lang` must be a non-empty string array")

    det = data["det"]
    if not isinstance(det, list) or not det:
        raise RuleValidationError(f"{path}: `det` must be a non-empty detector array")
    for index, detector in enumerate(det):
        if not isinstance(detector, dict) or not detector.get("tool") or not detector.get("rule"):
            raise RuleValidationError(f"{path}: det[{index}] must include `tool` and `rule`")
        if detector["tool"] not in ALLOWED_DETECTOR_TOOLS:
            raise RuleValidationError(f"{path}: det[{index}].tool `{detector['tool']}` is not registered")

    autofix = data.get("autofix")
    if autofix is not None:
        if not isinstance(autofix, dict) or autofix.get("type") not in ALLOWED_AUTOFIX_TYPES:
            raise RuleValidationError(f"{path}: `autofix.type` must match issue schema enum")

    gate = data.get("gate")
    if not isinstance(gate, dict):
        raise RuleValidationError(f"{path}: `gate` must be an object")
    if gate.get("enforcement") not in ALLOWED_ENFORCEMENT:
        raise RuleValidationError(
            f"{path}: `gate.enforcement` must be one of {', '.join(sorted(ALLOWED_ENFORCEMENT))}"
        )
    if rule_id == "IMP_007":
        threshold = gate.get("threshold")
        if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold <= 0:
            raise RuleValidationError(f"{path}: `gate.threshold` must be a positive integer")

    if " -> " not in rat or " ; #" not in rat:
        raise RuleValidationError(f"{path}: `rat` must use consequence -> impact ; #tag style")

    return Rule(
        id=rule_id,
        lvl=lvl,
        sev=sev,
        cat=cat,
        lang=lang,
        state=state,
        met=met,
        det=det,
        act=act,
        rat=rat,
        autofix=autofix,
        gate=gate,
    )


def expect_string(path: Path, data: dict[str, Any], key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value:
        raise RuleValidationError(f"{path}: `{key}` must be a non-empty string")
    return value


def expect_enum(path: Path, data: dict[str, Any], key: str, allowed: set[str]) -> str:
    value = expect_string(path, data, key)
    if value not in allowed:
        raise RuleValidationError(f"{path}: `{key}` has invalid value `{value}`")
    return value


def load_rule(path: Path) -> Rule:
    return validate_rule_data(path, parse_rule_file(path))


def load_rules(rules_dir: Path) -> dict[str, Rule]:
    if not rules_dir.is_dir():
        raise RuleValidationError(f"{rules_dir}: rules directory does not exist")

    rules: dict[str, Rule] = {}
    for path in sorted(rules_dir.glob("*.yml")):
        rule = load_rule(path)
        if rule.id in rules:
            raise RuleValidationError(f"{path}: duplicate rule id `{rule.id}`")
        rules[rule.id] = rule

    if not rules:
        raise RuleValidationError(f"{rules_dir}: no .yml rules found")
    return rules
