# Detector Truth Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every quality-gate `pass` truthful by distinguishing detector applicability, execution failure, verified fallback, and valid zero findings.

**Architecture:** Keep the current single-process core and add one small `DetectorOutcome` value object. Existing detector runners continue to own tool invocation and parsing; `scan_files` becomes the single place that combines outcomes, fallback coverage, issues, and strict-mode errors. No plugin framework or broad module split is introduced in this slice.

**Tech Stack:** Python 3.11+, standard library `unittest`, Ruff, ESLint, lizard.

---

## Intake Boundary

- Work type: Bug Fix + Enhancement.
- Runtime context: `local_dev_harness`.
- Exposure profile: `no_network_listener`.
- Production target: IDE-neutral local quality-gate core and its JSON truth surface.
- Non-targets: package installer, native Codex/Cursor/Qoder/Trae/Droid adapters, SARIF, CI templates, detector plugin framework, full monolith refactor.
- Source snapshot: `0998d5928a0ac797a7415ce90b3168618dc78475`.
- Review level: L2 agent-separated review; three read-only reviewers independently reproduced the blocking paths.

## Frozen Semantics

1. A detector outcome is one of `succeeded`, `not_applicable`, `missing`, `failed`, or `ignored`.
2. Coverage is one of `complete`, `fallback`, or `none`.
3. `--require-tools` applies only to detectors relevant to the scanned file types. `--doctor --require-tools` remains the full-install readiness check.
4. A successful detector with zero findings is valid, including lizard exit 0 with empty output.
5. A failed or missing lizard may use the Python AST fallback. Strict mode still returns `error`; non-strict mode may use the fallback result, but the fallback is visible in the report.
6. ESLint ignored, parser, fatal, or configuration diagnostics are coverage failures. TypeScript must never pass when ESLint did not actually lint it.
7. Python source that the runtime AST cannot parse produces a structured tool error instead of silently returning zero findings.
8. Existing report schema and top-level statuses remain compatible; detector run truth is added under each `detectors.<name>.run` object.

### Task 1: Lock the Runtime Failure Contract with Tests

**Files:**
- Modify: `tests/test_post_tool_use_quality_gate.py`

- [ ] **Step 1: Add a strict zero-function lizard regression test**

Add a test using fake `ruff`, `eslint`, and `lizard` executables. Ruff returns `[]`, lizard exits 0 with empty stdout, and the target is `APP_NAME = "demo"`. Assert exit 0, `status == "pass"`, no tool errors, and lizard run status `succeeded` with `coverage == "complete"`.

- [ ] **Step 2: Add a non-strict malformed-lizard fallback test**

Use a Python function with eleven independent branches and a fake lizard that prints malformed CSV. Assert the report contains `IMP_007`, the lizard run status is `failed`, coverage is `fallback`, fallback is `python_ast`, and no false `pass` is possible.

- [ ] **Step 3: Add the corresponding strict malformed-lizard test**

Run the same fixture with `--require-tools`. Assert `status == "error"`, the lizard tool error remains visible, and the fallback `IMP_007` issue is still retained for remediation.

- [ ] **Step 4: Add a TypeScript ignored-file test**

Make fake ESLint return a JSON message with `ruleId: null` and `message: "File ignored because no matching configuration was supplied."`. Assert `status == "error"`, ESLint run status `ignored`, and the ignored diagnostic is present in `tool_errors`.

- [ ] **Step 5: Replace the Python-only strict dependency expectation**

Replace `test_require_tools_checks_all_detectors_even_for_python_only_scan` with a test that omits ESLint, supplies working Ruff and lizard, and asserts ESLint is `not_applicable` while the Python scan succeeds.

- [ ] **Step 6: Add a Python syntax preflight test**

Scan syntactically invalid Python and assert a structured `python-ast` tool error and `status == "error"`; the process must not return `pass` or traceback.

- [ ] **Step 7: Run the focused tests and confirm RED**

Run:

```bash
python3 -m unittest \
  tests.test_post_tool_use_quality_gate.PostToolUseQualityGateTests.test_require_tools_accepts_lizard_zero_function_result \
  tests.test_post_tool_use_quality_gate.PostToolUseQualityGateTests.test_non_strict_lizard_failure_uses_visible_python_fallback \
  tests.test_post_tool_use_quality_gate.PostToolUseQualityGateTests.test_strict_lizard_failure_retains_error_and_fallback_issue \
  tests.test_post_tool_use_quality_gate.PostToolUseQualityGateTests.test_eslint_ignored_typescript_is_error \
  tests.test_post_tool_use_quality_gate.PostToolUseQualityGateTests.test_require_tools_ignores_irrelevant_eslint_for_python \
  tests.test_post_tool_use_quality_gate.PostToolUseQualityGateTests.test_python_syntax_error_is_structured_error -v
```

Expected: failures caused by absent detector outcomes and current false pass/false error behavior.

### Task 2: Add the Minimal Detector Outcome Contract

**Files:**
- Modify: `hooks/post_tool_use_quality_gate.py`

- [ ] **Step 1: Add `DetectorOutcome`**

Define an immutable dataclass with these fields:

```python
@dataclasses.dataclass(frozen=True)
class DetectorOutcome:
    status: str
    coverage: str
    files: tuple[str, ...]
    fallback: str | None = None
    message: str | None = None

    def to_schema(self) -> dict[str, Any]:
        return dataclasses.asdict(self)
```

- [ ] **Step 2: Return outcomes from each external runner**

Change `run_ruff`, `run_eslint`, and `run_lizard` to return `(issues, errors, outcome)` instead of the availability boolean. Use `not_applicable` when the runner has no relevant files, `missing` when no executable exists, `failed` for timeout/nonzero/malformed output, `ignored` for ESLint coverage diagnostics, and `succeeded` for a parsed result including zero findings.

- [ ] **Step 3: Treat lizard exit 0 with empty output as success**

When `returncode == 0` and stdout is empty, return no issues, no errors, and `DetectorOutcome(status="succeeded", coverage="complete", ...)`. Keep malformed non-empty output as `failed`.

- [ ] **Step 4: Reject ESLint meta diagnostics**

Add a helper that extracts any ESLint message that is fatal or has no `ruleId`. An ignored-file message maps to outcome status `ignored`; parser/configuration diagnostics map to `failed`. Do not silently discard these messages in `parse_eslint_payload`.

- [ ] **Step 5: Run focused parser tests**

Run the tests added in Task 1 that target lizard and ESLint. Expected: detector runner tests move toward GREEN; orchestration/report assertions may remain RED.

### Task 3: Make Scan Orchestration Fail Truthfully

**Files:**
- Modify: `hooks/post_tool_use_quality_gate.py`
- Modify: `tests/test_post_tool_use_quality_gate.py`

- [ ] **Step 1: Add Python AST preflight**

Before Python AST-based rules execute, parse every Python file once for validation. Convert `SyntaxError`, `UnicodeDecodeError`, and read failures into a `ToolError("python-ast", ...)` so invalid or unreadable Python cannot pass silently.

- [ ] **Step 2: Apply fallback rules in `scan_files`**

If lizard is `missing` or `failed`, run Python AST complexity for Python files. Set lizard coverage to `fallback` and fallback to `python_ast`. If non-Python files also depended on lizard, preserve the lizard error because coverage remains incomplete.

The built-in literal scanner remains the non-strict fallback for Ruff and JavaScript ESLint. TypeScript ignored/failed coverage remains an error because the regex scanner is not an equivalent TypeScript parser.

- [ ] **Step 3: Scope strict errors to applicable detectors**

Remove the unconditional scan-time `required_detector_errors(detectors)` call from `main`. Detector runners now emit missing-tool errors only for applicable files. Keep `required_detector_errors` for doctor readiness.

- [ ] **Step 4: Merge run outcomes into the JSON report**

Keep `available/path/version` and add a `run` object to each detector. `not_applicable` must be explicit. Ensure the report can explain a fallback even when top-level status is `fail` because the fallback found an issue.

- [ ] **Step 5: Run the focused suite and confirm GREEN**

Run the six focused tests from Task 1. Expected: all pass.

- [ ] **Step 6: Run the complete unit suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass with the new regression cases included.

### Task 4: Align Documentation and Replay Real Tools

**Files:**
- Modify: `README.md`
- Modify: `docs/ADAPTERS.md`
- Modify: `hooks/README.md`

- [ ] **Step 1: Document profile-scoped strict semantics**

State that `--require-tools` requires only detectors applicable to the scanned files, while doctor strict mode checks the complete installation inventory.

- [ ] **Step 2: Document detector run outcomes**

Add `detectors.<name>.run.status/coverage/fallback` to the report contract. State that TypeScript ignored/parser diagnostics are errors until a verified parser/config is present.

- [ ] **Step 3: Replay installed tools**

Run a strict clean Python constant-only scan, strict bad Python scan, strict JavaScript scan, and strict TypeScript scan with the installed Ruff, ESLint, and lizard. Expected: clean Python passes; bad Python/JavaScript fail with issues; TypeScript either executes verified linting or returns error, never pass when ignored.

- [ ] **Step 4: Run all repository gates**

Run:

```bash
python3 -m unittest discover -s tests -v
python3 tools/validate_rules.py rules --require DSN_001 --require IMP_004 --require IMP_007 --require MNT_001 --require MNT_002
ruff check .
python3 -m py_compile hooks/post_tool_use_quality_gate.py tools/*.py tests/*.py
git diff --check
```

Expected: all commands exit 0. The full repository quality scan may still report known baseline debt; it must have zero tool errors and no false pass.

- [ ] **Step 5: Obtain non-author review**

Give the final diff and replay commands to a fresh reviewer. Blocking findings must be resolved before commit.

- [ ] **Step 6: Commit the verified slice**

Stage only the plan, hook, tests, and aligned docs. Commit with an accurate message such as:

```bash
git commit -m "Make detector coverage failures explicit"
```

## Deferred Work

- `quality-gate-request/v1` normalization and adapter projection.
- YAML-driven `gate.enforcement`, threshold precedence, and decision output.
- Python runtime minimum and profile-aware `doctor --probe`.
- Installable `vcg` CLI, pinned detector toolchain, init/uninstall flow.
- Real Claude Code and Codex runtime certification.

