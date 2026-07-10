# Profile-aware Doctor Probe Plan

**Goal:** Make doctor readiness prove that the selected language profile can actually scan, rather than only proving detector commands exist.

**Scope:** Python runtime contract, profile selection, deterministic local smoke fixtures, structured readiness evidence, and remediation text. No package installer, silent dependency installation, native IDE adapter, or CI template.

## Contract

1. Supported doctor profiles are `python`, `javascript`, `typescript`, and `all`.
2. Python requires runtime 3.11+, Ruff, and lizard. JavaScript requires ESLint and lizard. TypeScript requires ESLint with working parser/config plus lizard.
3. `strict_ready` is true only when inventory, rules, runtime, and every selected profile smoke pass.
4. Smoke fixtures run in a temporary directory, make no network requests, and are removed automatically.
5. Doctor never installs tools. It reports purpose, approved commands, verification commands, and profile-specific remediation.
6. A detector version string without a passing smoke is not readiness evidence.

## Tasks

- [ ] Add RED tests for Python profile success, TypeScript ignored/parser failure, selected-profile detector scope, and Python <3.11.
- [ ] Add `--profile` doctor option and structured `profiles` results.
- [ ] Add local clean fixtures and invoke the existing scan core through the normalized request path.
- [ ] Make `strict_ready` depend on selected profile smoke results.
- [ ] Add profile-specific remediation without automatic installation.
- [ ] Update README, hook docs, and adapter readiness contract.
- [ ] Run full tests, Ruff, compile, rule validation, diff check, real doctor probes, complexity baseline, and non-author review.
- [ ] Commit independently.
