# Request and Policy Contract Implementation Plan

**Goal:** Make adapter input, rule enforcement, threshold precedence, decisions, and exit codes explicit and testable without adding native IDE adapters or new rules.

**Architecture:** Add one immutable `QualityGateRequest` DTO. Generic CLI and Claude Code remain thin projections into that DTO; the scan core consumes no raw adapter payload. Rules declare `gate.enforcement`, and an effective policy resolves the YAML complexity baseline plus an optional tightening-only CLI/environment override.

**Non-targets:** Native Codex/Cursor/Qoder/Trae/Droid adapters, adapter registry, detector refactor, SARIF, CI templates, auto-install, and new quality rules.

## Frozen Contract

1. Generic CLI and Claude PostToolUse project into `quality-gate-request/v1` before scanning.
2. `--hook` and `--files` are mutually exclusive. Conflicts and malformed hook payloads produce structured errors, never traceback or misleading source metadata.
3. Relative file and baseline paths resolve from normalized `cwd`, not process launch cwd.
4. Claude event data supplies source facts and candidate paths only. It cannot set strictness or policy.
5. Every wired rule declares `gate.enforcement`: `block`, `warn`, or `observe`; enforcement is never inferred from severity, action, or lifecycle state.
6. `rules/IMP_007.yml:gate.threshold` is the complexity baseline. CLI or `VCG_COMPLEXITY_THRESHOLD` may only choose a smaller, stricter positive integer. A relaxation attempt is a configuration error.
7. Decision priority is `error/incomplete > ratchet/block finding > warn > observe > pass`. Direct CLI exits 1 and hook exits 2 only for blocking/error/incomplete decisions; warn and observe exit 0.
8. Existing top-level report status values remain compatible. `decision` and `policy` explain why execution may continue despite non-blocking findings.

## Batch A: Normalize Adapter Requests

- [ ] Add failing tests for `--hook --files`, non-object hook JSON, invalid hook `cwd`, relative baseline resolution, and source truth.
- [ ] Add immutable `QualityGateRequest` with schema version, root, candidate files, source, tool name, baseline, strict flag, and optional threshold override/source.
- [ ] Add thin Generic CLI and Claude projection functions. Keep `collect_path_values` inside the Claude projection boundary.
- [ ] Make `main` consume only the normalized request for file resolution, ratchet, scan settings, and report source.
- [ ] Preserve current direct and hook behavior for valid inputs.
- [ ] Run focused tests, full suite, Ruff, compile, rule validation, diff check, and non-author review.
- [ ] Commit Batch A independently.

## Batch B: Make Policy Executable

- [ ] Add `gate.enforcement` to the five existing rules: `IMP_004` and `IMP_007` block; `MNT_001` warns; `DSN_001` and `MNT_002` observe.
- [ ] Validate required gate objects, enforcement enum, and positive `IMP_007` threshold in `rule_loader`.
- [ ] Add failing tests for missing/invalid enforcement, invalid threshold, YAML threshold behavior, tightening overrides, and relaxation rejection.
- [ ] Hydrate issue enforcement and compute a standalone decision with enforcement counts and rule ids.
- [ ] Add report `decision` and effective `policy` fields; keep issue schema and existing status consumers compatible.
- [ ] Drive direct/hook exit codes from decision and test block/warn/observe/mixed/tool-error/incomplete/ratchet cases.
- [ ] Update adapter and hook documentation.
- [ ] Run focused tests, full suite, Ruff, compile, rule validation, diff check, real repository replay, and non-author review.
- [ ] Commit Batch B independently.

## Deferred

- Public `--request` JSON transport and a standalone request JSON Schema.
- Native adapter certification for Codex, Cursor, Qoder, Trae, and Droid.
- Profile-aware doctor probes and installable `vcg` packaging; these remain P0-3.
