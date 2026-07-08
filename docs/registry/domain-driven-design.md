# 编译《领域驱动设计》（Domain-Driven Design, Evans）

> 选它的原因：DDD 是"统一语言、模型边界、核心域取舍"的系统化方法。Agent 编码最容易犯的不是语法错，而是把不同上下文里的词强行合并、把业务概念退化成 CRUD 数据袋。本书提供了对抗这种语义漂移的登记册。
> 章节核查点：Putting the Model to Work、Building Blocks、Refactoring Toward Deeper Insight、Strategic Design；战略设计三件套是 Bounded Context、Distillation、Large-Scale Structure。

---

## DDD_01 Ubiquitous Language：代码词汇必须来自领域语言

- **原始智慧**：团队应围绕模型形成统一语言，语言同时出现在对话、文档和代码里（Part I / Reference: Ubiquitous Language）。
- **编译**：L7 + L3 + L6 —— 维护领域术语表；L3 扫描新增公开类型/方法/事件名是否命中术语表或登记为候选；L6 裁决候选是否代表真实领域概念。
- **验证信号**：公开命名的术语表覆盖率；同义词/歧义词数量；review 中因命名导致的返工次数。
- **Goodhart 申报**：把所有技术名硬塞进术语表，稀释领域语言。对策：术语表条目必须有业务定义、反例、所属 bounded context；纯技术词进工程词表，不进领域词表。
- **状态**：T

## DDD_02 Bounded Context：模型只在边界内成立

- **原始智慧**：同一个词在不同上下文中可以有不同含义；模型必须声明适用边界（Part IV / Bounded Context）。
- **编译**：L5 + L3 —— 每个上下文有 context map；跨上下文引用必须通过 ACL/adapter/contract，不允许直接共享内部实体类型。L3 扫描跨 context import 与数据库表直接访问。
- **验证信号**：跨上下文直接依赖数；边界 adapter 覆盖率；语义冲突缺陷数。
- **Goodhart 申报**：把整个系统声明成一个巨大上下文，逃避边界成本。对策：上下文必须绑定 team/ownership、术语差异和发布边界；没有差异就合并，有差异就隔离。
- **状态**：T

## DDD_03 Aggregates：一致性边界就是写入边界

- **原始智慧**：Aggregate 保护内部不变量；外部只能通过 aggregate root 改变内部对象（Building Blocks / Aggregates）。
- **编译**：L3 + L5 —— 写路径必须经 aggregate root 或应用服务；禁止外部直接修改 aggregate 内部实体。事务边界默认不跨 aggregate，跨越时需要领域事件或 saga 说明。
- **验证信号**：绕过 root 的写入点数量；跨 aggregate 事务数量；不变量缺陷数。
- **Goodhart 申报**：把所有东西塞进一个 giant aggregate 以避免跨边界协调。对策：aggregate 大小受变更放大、锁竞争、测试构造成本共同约束；过大触发拆分评审。
- **状态**：T

## DDD_04 Distillation：核心域优先吃到人的判断

- **原始智慧**：战略设计要求 distill core domain；不是所有子域都值得同等设计投入（Part IV / Distillation）。
- **编译**：L8 + L5 —— 每个 bounded context 标注 core/supporting/generic。核心域变更必须有人审设计；generic 子域优先采购、生成或走无聊模式。
- **验证信号**：核心域 review 覆盖率；核心域缺陷/返工率；generic 子域自研比例。
- **Goodhart 申报**：所有团队都把自己的模块标成 core domain 争取资源。对策：core 标注必须连接业务差异化、收入/风险或战略叙事，并由产品/架构共同确认。
- **状态**：T

## DDD_05 Refactoring Toward Deeper Insight：模型变化要留下悔棋记录

- **原始智慧**：模型不是一次设计完成的；突破来自持续重构和把隐含概念显性化（Part III）。
- **编译**：L5 记忆流程 —— 当代码重命名领域概念、拆/合 aggregate、移动上下文边界时，必须写 model decision note：旧模型、触发证据、新模型、迁移影响。
- **验证信号**：模型变更的 ADR 覆盖率；同一概念反复改名次数；新模型减少的特殊分支/例外数。
- **Goodhart 申报**：把普通重命名都包装成"deeper insight"。对策：模型决策 note 必须引用业务对话、缺陷、需求变化或代码复杂度证据。
- **状态**：T

## 来源边界

- Domain-Driven Design Reference：<https://www.domainlanguage.com/wp-content/uploads/2016/05/DDD_Reference_2015-03.pdf>
- Google Books 概述：<https://books.google.com/books/about/Domain_driven_Design.html?id=xColAAPGubgC>
