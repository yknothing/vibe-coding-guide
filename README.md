# vibe-coding-guide

## Component & Code Playbook for AI-Augmented Development

> **Purpose** — Distill the best practices in component design, coding, code-review, unit & integration testing, slice them for LLM consumption, and ship runnable examples so humans and AI can co-create high-quality code.  
> **Companion repo** — [`vibe-coding-best-practices`](https://github.com/vibe-coding/vibe-coding-best-practices) (process / quality / CI rules).  
> **Division of labor** — Guide explains the **WHY & WHAT**; Best-Practices enforces the **HOW**.

---

## 🚀 Quick Start

```bash
git clone https://github.com/vibe-coding/vibe-coding-guide.git
cd vibe-coding-guide
make dev                      # optional: launch DevContainer / Codespace
./examples/ai-review/run.sh   # run the AI code-review demo
```

## Directory Structure

handbooks/            ─ Deep-dive articles (Design / Coding / AI Review)
for-ai/               ─ Machine-friendly slices, rules, and prompt seeds
    chunks/           ─ *.mdx slices (≤1 k-token)
    index.jsonl       ─ Chunk ↔ book/chapter mapping
    rules/            ─ Cursor / Windsurf YAML rules
        code_review_rules.md  ─ Structured code review rules (V1: Engineering-grade AI code review rules)
    prompts/          ─ High-frequency prompt templates
examples/             ─ Runnable demos (payment module, AI review)

## Code Review Rules

`for-ai/rules/code_review_rules.md` contains a structured set of code review rules, organized into eight major categories:

- Fundamentals (FND) – Single Responsibility, DRY, KISS, etc.
- Design Patterns & Anti-patterns (DSN) – Pattern application, anti-pattern identification
- Implementation & Readability (IMP) – Naming conventions, error handling, code formatting
- Security (SEC) – OWASP Top 10, cryptographic security, etc.
- Concurrency & Asynchrony (CNC) – Race conditions, deadlocks, concurrency issues
- Testability & Correctness (TST) – Test coverage, test design
- Performance & Efficiency (PRF) – Collection usage, string operations, etc.
- Maintainability & Evolution (MNT) – Configuration management, documentation standards

There are also language-specific rules for Java, Python, JS/TS, Go, C++, C#, Ruby, and Rust.
