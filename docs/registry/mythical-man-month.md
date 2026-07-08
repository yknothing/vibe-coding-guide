# 编译《人月神话 / 没有银弹》（Brooks）

> 选它的原因：Brooks 写的是软件工程的组织物理学。Agent 时代会诱发新的"加人"幻觉：把更多 agent 丢进一个问题，以为吞吐会线性增加。本书的编译重点不是复述名言，而是把协调成本、概念完整性和本质复杂度变成调度门禁。
> 章节核查点：The Mythical Man-Month、The Surgical Team、Aristocracy, Democracy, and System Design、The Second-System Effect、Plan to Throw One Away、No Silver Bullet。

---

## MMM_01 Brooks's Law：迟到项目不能靠并行 writer swarm 救

- **原始智慧**：向已延期的软件项目加人会让它更晚；核心原因是学习成本与沟通边数增长（The Mythical Man-Month）。
- **编译**：L5 调度门禁 —— 对延期任务新增 agent/开发者前，必须填写 coordination budget：共享上下文、交接工件、写入所有权、冲突处理。未拆出独立写域时，只允许增加只读研究、评审或测试 agent，不增加并行 writer。
- **验证信号**：并行写入导致的冲突率；handoff 后返工率；新增人/agent 后 lead time 是否下降。
- **Goodhart 申报**：把同一写域切成表面独立的小任务，制造"可并行"假象。对策：以写入文件/接口/概念所有权判定独立性，不以任务标题判定。
- **状态**：T

## MMM_02 概念完整性：系统必须有一个可追责的设计声音

- **原始智慧**：概念完整性优于功能堆砌；好系统需要少数头脑维护统一设计（Aristocracy, Democracy, and System Design）。
- **编译**：L8 + L5 —— 每个核心概念设 owner；跨 owner 的公共概念变更必须更新概念文档或 ADR。Agent 可生成备选和实现，但不能成为概念完整性的责任主体。
- **验证信号**：同一概念的命名分叉数；跨模块语义冲突数；owner 审核后的返工率。
- **Goodhart 申报**：owner 变成橡皮图章，或所有变更都升级 owner 导致阻塞。对策：只对核心概念、公共 API、限界上下文边界强制 owner；小局部实现由门禁处理。
- **状态**：T

## MMM_03 Plan to Throw One Away：原型必须带销毁条件

- **原始智慧**：新型系统不可避免会先做出一个需要丢弃的版本；危险在于把 pilot system 当成产品交付（Plan to Throw One Away）。
- **编译**：L5 流程 —— spike/prototype 必须在创建时声明：学习目标、禁止复用边界、销毁日期、可迁移知识。若原型代码进入生产路径，必须触发重新设计或显式 hardening checklist。
- **验证信号**：prototype 代码进入主路径的比例；过期 prototype 未清理数；从 prototype 提取出的 ADR/测试/接口数量。
- **Goodhart 申报**：把"原型"标签用作低质量借口，或把生产代码伪装成原型逃过 review。对策：原型目录不可被生产 import；破例需 ADR 和 hardening 任务。
- **状态**：T

## MMM_04 No Silver Bullet：生产力主张必须带本质/偶然拆分

- **原始智慧**：没有单一技术或管理方法能在十年内带来数量级提升；需要区分本质复杂度与偶然复杂度（No Silver Bullet）。
- **编译**：L6 + L8 —— 任何"工具/模型/流程将显著提速"的主张必须回答：它减少的是哪类偶然复杂度？本质复杂度由谁承担？验证指标是什么？不得用体感替代度量。
- **验证信号**：采纳前后 lead time、返工率、缺陷率、review 发现密度；本质复杂度是否只是转移给 reviewer/用户。
- **Goodhart 申报**：只汇报吞吐，不汇报质量和理解债。对策：速度指标必须与稳定性、返工、理解债抽查成对出现。
- **状态**：T

## MMM_05 Surgical Team：让 agent 分工围绕单一写入者

- **原始智慧**：外科团队模式把写作权集中在少数人，其余角色提供工具、测试、文档和支持（The Surgical Team）。
- **编译**：L5 调度模式 —— 多 agent 默认采用"single writer + sidecar researchers/reviewers/testers"。只有当写入边界完全不重叠，才允许多 writer 并行。
- **验证信号**：多 agent 任务中的冲突率、重复实现率、集成修复时间；single-writer 模式下的 review 缺陷密度。
- **Goodhart 申报**：单一写入者成为瓶颈，sidecar 产物无人消费。对策：sidecar 输出必须是可落盘工件（测试、对比表、引用证据、review findings），而不是聊天建议。
- **状态**：T

## 来源边界

- O'Reilly 章节页，Plan to Throw One Away：<https://www.oreilly.com/library/view/mythical-man-month-the/0201835959/ch11.xhtml>
- The Mythical Man-Month 1995 edition / No Silver Bullet 说明：<https://en.wikipedia.org/wiki/The_Mythical_Man-Month>
