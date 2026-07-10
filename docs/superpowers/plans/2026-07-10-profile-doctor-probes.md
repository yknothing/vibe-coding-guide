# Profile-aware Doctor Probe Plan

**Goal:** Make doctor readiness prove that the selected language profile can actually scan, rather than only proving detector commands exist.

**Scope:** Python runtime contract, profile selection, deterministic local smoke fixtures, structured readiness evidence, and remediation text. No package installer, silent dependency installation, native IDE adapter, or CI template.

## Contract

1. Supported doctor profiles are `python`, `javascript`, `typescript`, and `all`.
2. Python requires runtime 3.11+, Ruff, and lizard. JavaScript requires ESLint and lizard. TypeScript requires ESLint with working parser/config plus lizard.
3. `strict_ready` is true only when inventory, rules, runtime, and every selected profile smoke pass.
4. Clean and known-bad canary fixtures are removed automatically. Doctor does not install or download dependencies; detector processes and executable project config are not network-sandboxed.
5. Doctor never installs tools. It reports purpose, approved commands, verification commands, and profile-specific remediation.
6. A detector version string without a passing smoke is not readiness evidence.

## Tasks

- [x] Add RED tests for Python profile success, TypeScript ignored/parser failure, selected-profile detector scope, and Python <3.11.
- [x] Add `--profile` doctor option and structured `profiles` results.
- [x] Add local clean fixtures and invoke the existing scan core through the normalized request path.
- [x] Make `strict_ready` depend on selected profile smoke results.
- [x] Add profile-specific remediation without automatic installation.
- [x] Update README, hook docs, and adapter readiness contract.
- [x] Run full tests, Ruff, compile, rule validation, diff check, real doctor probes, complexity baseline, and non-author review.
- [x] Commit independently.
