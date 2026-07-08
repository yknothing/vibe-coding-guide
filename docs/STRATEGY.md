# 仓库战略评估：从"给 AI 读的知识库"到"Agent 编码质量门禁套件"

> 评估日期：2026-07-08
> 评估范围：仓库全部内容（README、`for-ai/rules/code_review_rules.md`、`for-ai/rules/issue.schema.json`、`for-ai/index.jsonl`）及其在 Agent Coding 时代的定位。

---

## 0. 背景与问题

本仓库设计于 vibe coding 概念刚兴起时（2025 年 5 月）。此后行业经历了 Prompt 工程、Context 工程、Harness 工程、Loop 工程等阶段，进入 Agent Coding 时代。实践中暴露出两个顽固问题：

1. **魔法值 / 硬编码**：尽管在 rule、prompt、skill 中都有明确禁止，实际生成与 review 效果依然不理想；
2. **代码复杂度**：人工编程时代靠编码规范与团队 review 勉强维持的复杂度控制，难以在每次 AI/Agent 编写与 review 代码时妥善处理。

本文回答三个问题：

- 本仓库的思路和方向是好的吗？为什么？
- 是否应当丢弃而转入使用 Skills？为什么？
- 最推荐的迭代 / 优化 / 替代方案是什么？

---

## 1. 仓库现状（事实对齐）

截至评估时，仓库实际只有 4 个文件，内容停留在 2025 年 5 月底：

- `README.md` 描述的 `handbooks/`、`for-ai/chunks/`、`for-ai/prompts/`、`examples/` **均不存在**；`for-ai/index.jsonl` 是空的 `{}`。
- 真正的资产是两个文件：
  - `for-ai/rules/code_review_rules.md`：约 90 条结构化评审规则（FND/DSN/IMP/SEC/CNC/TST/PRF/MNT/CSH/RSRC 十类 + 8 种语言特定规则），带 rule ID、级别（M/S/A）、严重度（B/C/H/M/L）、动作（RQR/RCM/FIX/CNF/EDU/LOG/WARN）；
  - `for-ai/rules/issue.schema.json`：评审结果的机器可读输出契约。
- 关键细节：每条规则的 `det` 字段已把检测映射到 Semgrep、SpotBugs、ESLint、Ruff、Lizard 等**确定性工具**——但这些映射从未被接线，只是写在文档里供 LLM"阅读"；`met` 字段中的 `calculate_srp_violation_score` 等函数是虚构的，没有任何东西真正计算它们。

这个事实本身就是回答三个问题的钥匙：**仓库设计了门禁系统的图纸，然后把图纸当成了门禁本身。**

---

## 2. Q1：本仓库的思路和方向是好的吗？

**结论：分类学直觉是对的、甚至超前；"知识注入"这条实现路径已被近两年的实践证伪。**

### 2.1 对的部分（放在 2025 年 5 月看相当超前）

- 把评审知识**结构化**而非散文化（rule ID、severity、category、action 分类学）；
- 定义**机器可读的输出契约**（`issue.schema.json` 本质上是自制版 SARIF）；
- `det` 字段把每条规则映射到确定性工具——说明作者当时就意识到"不能全靠 LLM 判断"；
- `act` 字段（RQR/RCM/FIX/EDU/LOG/WARN）定义了"发现问题后该做什么"的**策略层**——这一点至今仍是工具生态的空白。

### 2.2 错的部分：一个根本性前提误判

仓库的立项假设是：瓶颈在"知识"——"把最佳实践蒸馏、切片、喂给 LLM 消费"（README 原文的 Purpose）。但现实是：SOLID、OWASP、"不要用魔法值"这些知识早已深深烙在模型权重里。**模型不是不知道，而是不做。瓶颈从来不在知识，而在过程与强制。**

魔法值顽疾恰好是最好的证据，其失败机制有三层：

1. **注意力稀释**。90 条规则塞进上下文，每条分到的注意力权重微乎其微，且随任务上下文增长持续衰减。声明式规则之间是互相竞争的：规则越多，单条越不起作用。
2. **规则描述的是结果属性，不是过程步骤**。"不要硬编码"是对输出性质的要求；模型逐 token 生成时被局部上下文主导，几乎不会为一条远处的性质约束回头修改。相反，"写完后 grep 数字字面量并提取为常量"这类**程序性指令**的执行率高得多。
3. **无强制回路 + 同源盲区**。写在 rule/prompt/skill 里的要求是"建议"，linter 报错才是"门禁"。且用同一模型（或同家族模型）review 自己生成的代码，共享同样的训练偏好与盲区——生成时不觉得魔法值扎眼，review 时同样不觉得。确定性工具没有这个偏置。

复杂度问题同理，且更讽刺：圈复杂度和认知复杂度是**所有代码质量问题中最容易机器度量的**（lizard 跨语言 CCN、`sonarjs/cognitive-complexity`、Ruff `C901`）。让 LLM 靠"阅读感觉"判断复杂度，是把最不该外包给概率模型的任务外包了出去。

---

## 3. Q2：是否应当丢弃而转入 Skills？

**结论：不应该——这是个假的二选一。Skills 解决的是"知识何时进入上下文"（渐进披露、按需加载），不解决"要求是否被执行"。**

把这份 90 条规则的目录原样搬进 `SKILL.md`，会得到一模一样的失败，只是失败得更省 token：skill 被触发时加载 → 注意力稀释 → 生成时被局部上下文压制 → 无回路兜底。实践已经证明了这一点：魔法值要求"在 rule、prompt、skill 中都有明确要求"却依然无效——**三种载体都试过都无效，说明问题不在载体，在层次分配。**

正确的问题不是"rules 还是 skills"，而是"每一类问题该放在栈的哪一层"：

| 问题性质 | 应放的层 | 载体 |
|---|---|---|
| 机械可检测（魔法值、复杂度、格式、资源泄露模式） | 确定性工具 | linter / Semgrep / lizard 配置 |
| 强制执行（检测到之后必须处理） | Harness | hooks + CI 门禁 |
| 需要判断（常量命名是否达意、拆分是否合理、误报豁免） | 模型 | 一个瘦的 review skill |
| 项目特有约定（阈值、例外、领域术语） | 记忆 | 精简的 CLAUDE.md / 规则源文件 |

### 3.1 对现有资产的处置：丢弃形式，保留骨架

**丢弃**：

- 单体大文档格式（一次性全量进入上下文的消费方式）；
- 伪指标（`srp_violation_score > 0.7` 这类看似精确、实则无物计算的表达式——虚假精确性，纯粹消耗 token）；
- 对模型已知通用知识的复述（SOLID 讲解、Effective Java 常识等）；
- README 中从未兑现的目录蓝图。

**保留**：

- rule ID 体系（做抑制注释与追踪的稳定锚点）；
- severity → action 策略分类学（仓库最独特的资产）；
- `det` 工具映射表（这是重构的施工图）;
- issue schema 的思路（但放弃自制格式，对齐 SARIF，让任何 harness 和 IDE 都能消费）。

---

## 4. Q3：最推荐的迭代方案

**把仓库从"给 AI 读的知识库"重新定位为"可分发的 Agent 编码质量门禁套件"（quality-gate kit）**：规则作为单一事实来源，向下编译出四种产物。

### 4.1 目标架构

```text
rules/            # 单一来源：每条规则一个 YAML（沿用现有 rule ID 体系）
compiled/         # 生成物：eslint / ruff / semgrep / lizard 配置包
hooks/            # Claude Code hooks：编辑后自动检测，把违规喂回当前回合
skills/           # 一个瘦的判断层 review skill（消费工具输出，而非自己找问题）
ci/               # GitHub Actions 模板，最终兜底
schema/           # 输出对齐 SARIF
```

### 4.2 两个顽固问题的具体机制

**魔法值**：

- 检测：ESLint `no-magic-numbers` + Ruff `PLR2004` + Semgrep 自定义规则（覆盖字符串 / URL / 端口类硬编码）；
- 强制：接到 `PostToolUse` hook——Agent 每次 Edit/Write 后立即扫描改动文件，违规以报错形式回注**当前回合**；
- 效果：把"可以忽略的第 47 条规则"变成"不解决就无法结束回合的报错"。这是 Loop 工程的本质——让修复发生在生成时刻（此时最便宜），而不是 review 时刻。

**复杂度**：

- 检测：lizard / `C901` / cognitive-complexity 设**硬阈值**；
- 强制：**棘轮机制（ratchet）**——对存量代码记录 baseline，新改动只允许复杂度持平或下降，不允许上升。棘轮很关键：Agent 经常要动遗留代码，绝对阈值会把一切堵死，棘轮则保证"每次触碰只会更好"；
- 意义：它把复杂度治理从口号改成回合级棘轮；完整定义见 [APOSD_03](./registry/aposd.md#aposd_03-战略编程-vs-战术编程)。

**判断层 skill 的真正职责**（这是 LLM 应该待的位置）：不做检测，只消费工具的结构化输出，处理工具管不了的部分——常量命名是否达意、复杂度拆分是真拆还是搬运、误报豁免与 `act` 策略裁决（阻塞还是记债）。

### 4.3 容易被忽略但同样重要的点

1. **Goodhart 定律会立刻找上门**。一旦立了门禁，Agent 会优化"通过门禁"而非"代码质量"——`TIMEOUT_5000 = 5000` 这种应付式提取必然出现。所以判断层不可省略：门禁 + 判断是一对，缺一个都会退化。
2. **自我 review 偏置**。review 应在干净上下文中进行（subagent 或新会话），不带生成时的上下文；机制细节见 [COMPILING-THE-CLASSICS.md 第 6.3 节](./COMPILING-THE-CLASSICS.md#63-验证回路)。
3. **预防优于审查**。Agent 是强局部模仿者，范例与词汇的机制解释见 [COMPILING-THE-CLASSICS.md 第 3.3 节](./COMPILING-THE-CLASSICS.md#33-第二条通道agent-是叠加态环境是采样器)。仓库里已有干净的 `constants.ts`、清晰的模块拆分模式时，Agent 的输出会自动向它看齐。
4. **上下文经济学**。常驻规则按每回合持续付 token 税并加剧 context rot；hook 在无违规时零上下文成本。这是把内容从 prompt 层迁到 harness 层的另一个硬理由。
5. **经济学变化了**。生成已经便宜，"在约束下重新生成"优于"补丁—review—再补丁"。例如 Stop hook 在存在违规时拒绝整个回合、触发重新生成，往往比追加修补收敛更快。

### 4.4 差异化定位

单纯的规则集（awesome-cursorrules 之类）和单纯的检测工具（SonarQube / Semgrep）都已是红海。本仓库真正独特、且已有雏形的资产是：

- **severity → action 策略层**："发现问题之后，harness 应该阻塞、要求确认、还是记录技术债"——这层策略在现有工具生态中是空白；
- **为 Agent 循环预先接好线的集成包**：检测（工具）—强制（hooks/CI）—判断（skill）三层开箱即用。

做成跨 harness（Claude Code / Cursor / CI）的可安装门禁套件，是目前生态里还没人做好的位置。

---

## 5. 三问最短回答

1. **方向好吗？** 分类学直觉是好的（结构化规则、输出 schema、工具映射、action 策略），但"知识注入"路线已死：模型不缺知识，缺过程与强制。
2. **转 Skills 吗？** 不要平移——换载体不换层次会以同样方式失败。Skills 只是四层架构中"判断层"的载体之一。
3. **怎么迭代？** 重构为"规则编译成工具配置 + hooks 强制 + 瘦 skill 判断"的门禁套件；保留 rule ID / 分类学 / schema 骨架（schema 对齐 SARIF），丢弃单体文档与伪指标。

## 6. 建议的落地顺序

1. **原型**（最小可验证）：一个 `PostToolUse` hook，接 ESLint `no-magic-numbers` / Ruff `PLR2004` + lizard 复杂度阈值，对改动文件即时反馈；
2. **规则拆分**：把 `code_review_rules.md` 拆为 `rules/` 下的单规则 YAML，删除伪指标，保留 ID / severity / act / det；
3. **编译管道**：从 `rules/` 生成 linter / Semgrep 配置与 CI 工作流；
4. **判断层 skill**：编写消费 SARIF 输出的 review skill（命名质量、拆分合理性、豁免裁决）;
5. **棘轮**：复杂度 baseline + 只降不升的门禁；
6. **范例落地**：补上 `examples/`——干净的常量组织与模块拆分范式，作为 Agent 的局部模仿源。
