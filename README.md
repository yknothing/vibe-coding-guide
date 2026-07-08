# vibe-coding-guide

## 把软件工程经典编译进 Agent 的工作环境

> 本仓库正在从"给 AI 读的规则库"（v1，已被实践证伪）重构为**Agent 编码质量门禁套件与编译方法论**。
> 转向的完整论证见 [docs/STRATEGY.md](./docs/STRATEGY.md)。

## 10 分钟跑通

本仓库当前最重要的使用路径是 **IDE-neutral quality gate core**：同一套检测逻辑先通过
Generic CLI 跑通，再由各 IDE/CLI 的薄 adapter 接入。Claude Code 已有 documented
`PostToolUse` 路径；Codex、Cursor、Qoder、Trae、Droid 目前使用 Generic CLI fallback，
native adapter 仍是 planned。adapter 能力、状态分级和输入/输出契约见
[docs/ADAPTERS.md](./docs/ADAPTERS.md)。

先检查本机能不能启用严格门禁：

```bash
python3 hooks/post_tool_use_quality_gate.py --doctor
python3 hooks/post_tool_use_quality_gate.py --doctor --require-tools
```

如果缺 detector，安装当前 strict mode 依赖：

| Tool | What it is | Gate role |
|---|---|---|
| `ruff` | Fast Python linter | Python 魔法数字检测，使用 Ruff `PLR2004` 补强内置 AST fallback。 |
| `lizard` | Cyclomatic complexity analyzer | 函数圈复杂度检测，用于 `IMP_007`。 |
| `eslint` | JavaScript and TypeScript linter | JS/TS 魔法数字检测，使用 `no-magic-numbers`。 |

```bash
python3 -m pip install --upgrade ruff lizard
npm install -g eslint
```

安全边界：这些命令只供人工确认后执行；adapter 或安装器不得静默执行。使用 PyPI/npm、
组织批准的内部镜像或 pinned/approved toolchain；不要使用 `curl | sh` 式安装脚本；如果不允许
global npm install，或目标环境不是 macOS/Linux shell，就在项目或受控工具环境中使用等价安装方式，
并确保 `eslint` 在 hook 的 `PATH` 中。
安装后必须重跑：

```bash
python3 hooks/post_tool_use_quality_gate.py --doctor --require-tools
```

再跑最小验证：

```bash
python3 -m unittest discover -s tests -v
python3 tools/validate_rules.py rules --require DSN_001 --require IMP_004 --require IMP_007 --require MNT_001 --require MNT_002
python3 hooks/post_tool_use_quality_gate.py --format json --files path/to/file.py
```

JSON report 的 `status` 可能是 `pass`、`fail`、`error` 或 `incomplete`。其中 `incomplete`
表示没有扫描到支持的文件，不能当作质量绿灯。接入具体 IDE/CLI 前，先用 Generic CLI 跑通；
再按 [hooks/README.md](./hooks/README.md) 或 [docs/ADAPTERS.md](./docs/ADAPTERS.md) 选择对应 adapter。

## 实际目录结构（与磁盘一致）

```text
docs/
  ADAPTERS.md                 IDE-neutral core contract、能力矩阵与 adapter 验收边界
  STRATEGY.md                 仓库战略评估：知识注入路线为何失败，为何改走门禁套件
  COMPILING-THE-CLASSICS.md   方法论：六条第一性原理、验证不对称性、六种编译形态
  registry/                   编译登记册（活文档）：逐书逐章把经典编译为可实现的机制
    README.md                 编译阶梯、条目 schema、Goodhart 申报制度、登记队列
    aposd.md                  《A Philosophy of Software Design》逐章编译
    effective-java.md         《Effective Java》三波编译的先例研究
    legacy-code.md            《修改代码的艺术》：遗留代码手术规程
    refactoring.md            《重构》：两顶帽子、小步绿灯、坏味道分拣
    tdd.md                    《测试驱动开发》：红灯实证、测试清单、三角化
    pragmatic-programmer.md   《程序员修炼之道》：DRY、正交性、曳光弹、破窗
    mythical-man-month.md     《人月神话 / 没有银弹》：协调成本、概念完整性、原型
    domain-driven-design.md   《领域驱动设计》：统一语言、限界上下文、核心域
    release-it.md             《Release It!》：稳定性模式、集成点、生产韧性
    accelerate.md             《Accelerate / DORA》：交付绩效指标与组织反馈闭环
    out-of-the-tar-pit.md     《Out of the Tar Pit》：状态预算、控制流预算
    unix-philosophy.md        Unix 哲学：单一职责、组合性、文本/结构化接口
for-ai/                       v1 遗产（反例标本 + schema 骨架；执行层定位已被 STRATEGY.md 否定）
  rules/code_review_rules.md  v1 规则集：90 条单体规则（作为反例标本保留）
  rules/issue.schema.json     v1 输出契约（后续对齐 SARIF）
  index.jsonl                 空占位文件，待重构时清理
hooks/                        首个可运行 PostToolUse 质量门禁原型
rules/                        首批迁移并接线的单规则 YAML（DSN_001 / IMP_004 / MNT_001 / MNT_002 / IMP_007）
tests/                        标准库回归测试，覆盖 hook、规则校验、fail-closed 语义
tools/                        规则加载、校验、APOSD_02a 仪表盘与 APOSD_05 变更压测评分工具（无第三方依赖）
```

## 可运行门禁原型

当前第一条工程化路径是 `hooks/post_tool_use_quality_gate.py`：一个 IDE-neutral
质量门禁 core。它可以直接通过 `--files` 扫描文件，也可以由 Claude Code `PostToolUse`
或其他 IDE/CLI adapter 转入同一份输入契约。

它目前接线五条规则：

- `DSN_001`：Python 纯透传函数 / 方法；
- `IMP_004`：魔法数字；
- `MNT_001`：硬编码 URL / host / port；
- `MNT_002`：显式导出的 Python 公开 API 缺 docstring；
- `IMP_007`：函数复杂度阈值。

运行本地验证：

```bash
python3 hooks/post_tool_use_quality_gate.py --doctor --format json
python3 -m unittest discover -s tests -v
python3 tools/validate_rules.py rules --require DSN_001 --require IMP_004 --require IMP_007 --require MNT_001 --require MNT_002
python3 hooks/post_tool_use_quality_gate.py --format json --files path/to/file.py
python3 hooks/post_tool_use_quality_gate.py --format json --ratchet-baseline previous-report.json --files path/to/file.py
```

JSON 输出包含 `metrics` 与 `ratchet` 字段，可作为 `APOSD_03` 的最小回合级棘轮：
传入上一轮 baseline 后，触碰文件的魔法值、硬编码端点和最大 Python 函数复杂度不得劣化。
项目级 hook 配置、strict 模式依赖、棘轮 baseline 和手工 payload 模拟见 [hooks/README.md](./hooks/README.md)。

## 复杂度仪表盘原型

`tools/complexity_dashboard.py` 是 `APOSD_02a` 的最小可运行采集原型。它从本地 Git 历史、
可选 agent context JSON/JSONL、可选 defect JSON/JSONL 中生成三类信号：

- 变更放大系数：按 issue / spec / ADR id 聚合 commit，而不是按单 commit 计分；
- 上下文足迹：记录读取文件数、字节/token 量和来源分布，不单独作为质量分；
- 缺陷逃逸相关性：记录缺陷来源分布、unknown 来源和近期改动文件重叠。

运行示例：

```bash
python3 tools/complexity_dashboard.py --since HEAD~10 --format json
python3 tools/complexity_dashboard.py --since HEAD~10 --context-log context.jsonl --defects defects.jsonl
```

该工具输出的是周期校准信号，不是单次回合的阻塞门禁；单回合门禁仍应使用复杂度、坏味道、
覆盖率和测试结果等即时可计算量。

## 变更压测评分原型

`tools/change_probe.py` 是 `APOSD_05` 的最小爆炸半径评分底座：对一次已经完成的 probe diff
统计触碰文件、触碰模块和接口签名变更。

```bash
python3 tools/change_probe.py --base HEAD~1 --head HEAD --scenario-id APOSD05-001 --format json
```

它不负责证明 probe 由独立上下文执行，也不负责场景池抽样；这些必须由后续 harness 接线。

## 阅读顺序

1. [docs/STRATEGY.md](./docs/STRATEGY.md) — 这个仓库为什么转向；
2. [docs/COMPILING-THE-CLASSICS.md](./docs/COMPILING-THE-CLASSICS.md) — 编译方法论与理论基础；
3. [docs/registry/](./docs/registry/README.md) — 可直接领取实现的条目（各书末尾附实现优先级建议）。

## 当前状态

文档与方法论先行阶段。`for-ai/rules/` 保留为 v1 反例标本与 schema 来源，真实可执行规则迁移到顶层 `rules/` 后才算接线。门禁 / hook / skill 的工程实现按登记册各书的"实现优先级建议"推进；本仓库的文档语料自身也受登记册第 5 节"反身性"条款约束（不引用不存在的工件、合并前经干净上下文对抗性评审）。
