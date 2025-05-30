# vibe-coding-guide

*Component & Code Playbook for AI-Augmented Development*

> **Purpose** — Distill the best practices in component design, coding, code-review, unit & integration testing, slice them for LLM consumption, and ship runnable examples so humans and AI can co-create high-quality code.  
> **Companion repo** — [`vibe-coding-best-practices`](https://github.com/vibe-coding/vibe-coding-best-practices) (process / quality / CI rules).  
> **Division of labor** — Guide explains the **WHY & WHAT**; Best-Practices enforces the **HOW**.

---

## 🚀 Quick Start
```bash
git clone https://github.com/vibe-coding/vibe-coding-guide.git
cd vibe-coding-guide
make dev                      # optional: launch DevContainer / Codespace
./examples/ai-review/run.sh   # run the AI code-review demo


## 目录结构

handbooks/            ─ deep-dive articles (Design / Coding / AI Review)
for-ai/               ─ machine-friendly slices + rules + prompt seeds
    chunks/           ─ *.mdx slices (≤1 k-token)
    index.jsonl       ─ chunk ↔ book/chapter mapping
    rules/            ─ Cursor / Windsurf YAML
    prompts/          ─ high-frequency prompt templates
examples/             ─ runnable demos (payment module, AI review)
