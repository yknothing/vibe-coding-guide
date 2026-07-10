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

## Doctor

Check local readiness before enabling strict hook mode:

```bash
python3 hooks/post_tool_use_quality_gate.py --doctor
python3 hooks/post_tool_use_quality_gate.py --doctor --require-tools
python3 hooks/post_tool_use_quality_gate.py --doctor --format json
```

`--doctor` emits `quality-gate-doctor/v1`. Non-strict mode returns `warn` when
external detectors are missing because fallback detectors can still run. Strict
mode treats a missing applicable `ruff`, `eslint`, or `lizard` as `fail`; do not enable
`--require-tools` in an adapter until doctor reports `strict_ready: true`.
Doctor checks the complete installation inventory. A file scan is profile-scoped:
strict mode requires only detectors applicable to the scanned file types, so a
Python-only scan does not require ESLint.

## Claude Code Setup

Install the detector tools first. `--doctor` reports the same information in
`install_plan` so adapters can show it before enabling strict mode.

| Tool | What it is | Gate role |
|---|---|---|
| `ruff` | Fast Python linter | Detects Python magic numeric literals through Ruff `PLR2004`. |
| `lizard` | Cyclomatic complexity analyzer | Measures function complexity for `IMP_007`. |
| `eslint` | JavaScript and TypeScript linter | Detects JavaScript magic numeric literals; TypeScript also needs a working parser/config. |

```bash
python3 -m pip install --upgrade ruff lizard
npm install -g eslint
```

These commands are for manual confirmation only; adapters and installers must
not run them without explicit user approval. Use PyPI/npm, approved internal
mirrors, or a pinned/approved toolchain. Do not use `curl | sh` installers.
If global npm installs are blocked, or the target environment is not a
macOS/Linux shell, install ESLint in the project or approved tool environment
with an equivalent command and make sure the hook process can find `eslint` on
`PATH`.
Verify the setup before enabling the hook:

```bash
python3 hooks/post_tool_use_quality_gate.py --doctor --require-tools
```

Then add this project-scoped hook to `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|Bash",
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

`--require-tools` is intentional: an applicable detector that is missing or fails
is treated as a setup failure instead of a green pass. The script still has
built-in fallback detectors so the repository can run deterministic tests
without installing those tools. TypeScript ignored, parser, and configuration
diagnostics remain errors because the literal fallback is not a TypeScript parser.

`Bash` is included because shell commands can create or modify files without
going through `Edit` / `Write` / `MultiEdit`. When a `Bash` payload does not
include a path, the hook falls back to `git status --porcelain` and scans changed
supported files.

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
`run_id`, `duration_ms`, `source`, `detectors`, `scanned_files`, `skipped_files`,
`rules_loaded`, `metrics`, `ratchet`, `issues`, `tool_errors`, and `summary`.
Individual `issues` keep the required fields from `for-ai/rules/issue.schema.json`.
Generic CLI and Claude PostToolUse inputs are normalized through
`quality-gate-request/v1`; the report records that version in
`source.request_schema_version`. `--hook` and `--files` are mutually exclusive,
and relative baseline paths resolve from the normalized project root.
Each detector records the current run under `detectors.<name>.run`, including
`status` (`succeeded`, `not_applicable`, `missing`, `failed`, or `ignored`),
`coverage` (`complete`, `fallback`, or `none`), files, the fallback name, and
`uncovered_files`. A non-empty `uncovered_files` list means the fallback did not
cover every requested file and the run cannot pass.
For zero-function files, an empty lizard CSV is accepted only after lizard's XML
File measure explicitly confirms that the requested file was processed.

Rule enforcement is explicit: `block`, `warn`, or `observe`. Reports include
`decision`, per-enforcement counts, issue-level `enforcement`, and the effective
`policy`. Warn and observe findings exit 0 but remain visible. The IMP_007 YAML
threshold is authoritative; CLI/environment overrides may tighten it, never relax it.

`status: incomplete` means the gate did not scan any supported files, usually
because every input path was unsupported, outside the project, duplicated, or
missing. Treat it as "no quality claim," not as a pass.

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
