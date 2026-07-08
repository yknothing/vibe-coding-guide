# vibe-coding-guide

## 把软件工程经典编译进 Agent 的工作环境

> 本仓库正在从"给 AI 读的规则库"（v1，已被实践证伪）重构为**Agent 编码质量门禁套件与编译方法论**。
> 转向的完整论证见 [docs/STRATEGY.md](./docs/STRATEGY.md)。

## 实际目录结构（与磁盘一致）

```text
docs/
  STRATEGY.md                 仓库战略评估：知识注入路线为何失败，为何改走门禁套件
  COMPILING-THE-CLASSICS.md   方法论：六条第一性原理、验证不对称性、六种编译形态
  registry/                   编译登记册（活文档）：逐书逐章把经典编译为可实现的机制
    README.md                 编译阶梯、条目 schema、Goodhart 申报制度、登记队列
    aposd.md                  《A Philosophy of Software Design》逐章编译
    effective-java.md         《Effective Java》三波编译的先例研究
    legacy-code.md            《修改代码的艺术》：遗留代码手术规程
    refactoring.md            《重构》：两顶帽子、小步绿灯、坏味道分拣
    tdd.md                    《测试驱动开发》：红灯实证、测试清单、三角化
for-ai/                       v1 遗产（执行层定位已被 STRATEGY.md 否定，schema 骨架被登记册复用）
  rules/code_review_rules.md  v1 规则集：90 条单体规则（作为反例标本保留）
  rules/issue.schema.json     v1 输出契约（后续对齐 SARIF）
  index.jsonl                 空占位文件，待重构时清理
hooks/                        首个可运行 PostToolUse 质量门禁原型
rules/                        首批拆分出的单规则 YAML（IMP_004 / MNT_001 / IMP_007）
tests/                        标准库回归测试，覆盖 hook、规则校验、fail-closed 语义
tools/                        规则加载与校验工具（无第三方依赖）
```

## 可运行门禁原型

当前第一条工程化路径是 `hooks/post_tool_use_quality_gate.py`：一个面向 Claude Code
`PostToolUse` 的质量门禁原型，覆盖 `Edit` / `Write` / `MultiEdit` 后的改动文件扫描。

它目前接线三条规则：

- `IMP_004`：魔法数字；
- `MNT_001`：硬编码 URL / host / port；
- `IMP_007`：函数复杂度阈值。

运行本地验证：

```bash
python3 -m unittest discover -s tests -v
python3 tools/validate_rules.py rules --require IMP_004 --require IMP_007 --require MNT_001
python3 hooks/post_tool_use_quality_gate.py --format json --files path/to/file.py
```

项目级 hook 配置、strict 模式依赖和手工 payload 模拟见 [hooks/README.md](./hooks/README.md)。

## 阅读顺序

1. [docs/STRATEGY.md](./docs/STRATEGY.md) — 这个仓库为什么转向；
2. [docs/COMPILING-THE-CLASSICS.md](./docs/COMPILING-THE-CLASSICS.md) — 编译方法论与理论基础；
3. [docs/registry/](./docs/registry/README.md) — 可直接领取实现的条目（各书末尾附实现优先级建议）。

## 当前状态

文档与方法论先行阶段。门禁 / hook / skill 的工程实现按登记册各书的"实现优先级建议"推进；本仓库的文档语料自身也受登记册第 5 节"反身性"条款约束（不引用不存在的工件、合并前经干净上下文对抗性评审）。
