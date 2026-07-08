# PostToolUse Quality Gate Prototype

This is the first runnable slice from `docs/STRATEGY.md`: a repo-local Claude Code
`PostToolUse` hook that scans files changed by `Edit`, `Write`, or `MultiEdit`
and immediately feeds quality violations back into the current agent turn.

The prototype maps findings back to the existing rule anchors:

- `DSN_001` for Python functions or methods that only pass parameters through
- `IMP_004` for magic numeric literals
- `MNT_001` for hardcoded URLs, hosts, and ports
- `MNT_002` for Python names explicitly exported via `__all__` without docstrings
- `IMP_007` for function complexity above the configured threshold

## Claude Code Setup

Install the detector tools first:

```bash
python3 -m pip install ruff lizard
npm install -g eslint
```

Then add this project-scoped hook to `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/hooks/post_tool_use_quality_gate.py --hook --require-tools",
            "args": []
          }
        ]
      }
    ]
  }
}
```

`--require-tools` is intentional: in gate mode, missing Ruff, ESLint, or lizard
is treated as a setup failure instead of a green pass. The script still has
built-in fallback detectors so the repository can run deterministic tests
without installing those tools.

## Manual Checks

Scan a file directly:

```bash
python3 hooks/post_tool_use_quality_gate.py --files path/to/file.py
```

Simulate a Claude Code hook payload:

```bash
printf '%s\n' '{"hook_event_name":"PostToolUse","tool_name":"Edit","cwd":"'"$PWD"'","tool_input":{"file_path":"path/to/file.py"}}' \
  | python3 hooks/post_tool_use_quality_gate.py --hook
```

Use JSON output for downstream tooling:

```bash
python3 hooks/post_tool_use_quality_gate.py --format json --files path/to/file.py
```

JSON output is a stable wrapper with `schema_version`, `status`, `timestamp`,
`scanned_files`, `skipped_files`, `rules_loaded`, `metrics`, `ratchet`,
`issues`, `tool_errors`, and `summary`. Individual `issues` keep the required fields from
`for-ai/rules/issue.schema.json`.

## Quality Ratchet

Use a previous JSON report as the baseline for touched-file metrics:

```bash
python3 hooks/post_tool_use_quality_gate.py --format json \
  --ratchet-baseline previous-report.json \
  --files path/to/file.py
```

The ratchet compares only files present in both the baseline and the current
scan. New files do not fail for missing history. The current metrics cover
magic numeric literals, hardcoded endpoints, and maximum Python function complexity.
This is the APOSD_03 "must not regress" slice; it does not claim that every
green turn must produce a refactoring diff.

Validate the split rule sources:

```bash
python3 tools/validate_rules.py rules --require DSN_001 --require IMP_004 --require IMP_007 --require MNT_001 --require MNT_002
```

## Suppression

Only intentional magic literals can be suppressed, and only with this token on
the same line or within the two preceding lines:

```text
ALLOW_MAGIC_NUMBER: reason, ticket
```

Complexity and hardcoded endpoint findings should be fixed or moved behind
configuration; this prototype does not provide a broad suppression escape hatch.
