# 编译《程序员修炼之道》（The Pragmatic Programmer）

> 选它的原因：这本书覆盖个人工程纪律、工具链、反馈回路和项目习惯。它不像 APoSD 那样集中在设计判断，也不像 TDD/Feathers 那样天然收敛成一条 hook；它的价值在于把"专业程序员的日常动作"拆成可持续执行的回合规程。
> 20th Anniversary Edition 的目录核查点：A Pragmatic Philosophy、A Pragmatic Approach、Basic Tools、Pragmatic Paranoia、Bend or Break、Concurrency、While You Are Coding、Before the Project、Pragmatic Projects。

---

## TPP_01 DRY：知识重复，不是文本重复

- **原始智慧**：DRY 针对的是 knowledge duplication，同一项知识不应散落在多个表达里；文本相似只是症状（第 2 章，DRY）。
- **编译**：L3 + L6 —— L3 用 clone detector / 共同变更分析找文本和结构重复；L6 批判者裁决"这两处是否表达同一项业务知识"。只有知识重复才触发合并或抽象，文本重复但语义独立可登记豁免。
- **验证信号**：同一逻辑变更触碰重复点的次数；重复修复缺陷数；抽象后调用方复杂度是否下降。
- **Goodhart 申报**：为消除文本重复而制造过早抽象，导致抽象参数爆炸、调用方更难懂。对策：抽象必须降低变更放大或调用方样板；否则保留重复并登记"偶然相似"。
- **状态**：T

## TPP_02 Orthogonality：改一处不该牵动无关维度

- **原始智慧**：正交系统中，局部变更不影响无关功能；非正交会放大测试矩阵和缺陷面（第 2 章，Orthogonality）。
- **编译**：L3 + L6 —— L3 采集共同变更文件对、跨模块 import、全局状态读写；L6 问："这个 diff 为什么触碰了两个看似无关的维度？它们共享的知识是什么？"
- **验证信号**：共同变更图中高耦合簇数量；一个需求平均触碰的模块数；回归缺陷跨功能传播次数。
- **Goodhart 申报**：机械拆文件降低耦合图指标，但把隐式协议藏到字符串、事件名或全局配置里。对策：事件名、配置键、协议常量进入同一知识重复扫描。
- **状态**：T

## TPP_03 Tracer Bullets：先贯通真实路径

- **原始智慧**：Tracer bullets 不是 disposable prototype；它们是穿过真实架构的最薄可用路径，用来校准方向（第 2 章，Tracer Bullets）。
- **编译**：L5 流程 —— 非平凡功能先交付一条端到端薄切片：真实入口、真实核心路径、真实持久化或外部边界的替身必须标注。薄切片通过后才允许横向铺开。
- **验证信号**：首个端到端绿灯到达时间；后续功能复用 tracer 路径的比例；被 tracer 提前发现的架构假设数。
- **Goodhart 申报**：把 mock-heavy demo 冒充 tracer bullet。对策：薄切片必须穿过至少一个真实边界；所有替身都要有替换任务和过期条件。
- **状态**：T

## TPP_04 Pragmatic Paranoia：错误要早爆、近爆、带上下文爆

- **原始智慧**：Design by Contract、Dead Programs Tell No Lies、Assertive Programming 都在说同一件事：非法状态越晚暴露，修复越贵（第 4 章）。
- **编译**：L2/L3/L4 —— 类型约束优先；无法上类型的前置条件、后置条件、不变量进入断言或 schema；测试必须覆盖契约失败路径。生产可恢复错误走显式错误通道，不可恢复契约破坏 fail fast。
- **验证信号**：契约失败测试覆盖；线上空指针/非法状态类缺陷下降；错误消息含必要上下文的比例。
- **Goodhart 申报**：到处加 assert 但错误消息无上下文，或把用户输入错误误判为程序员错误。对策：契约分层：外部输入先校验，内部不变量才 assert；错误消息必须包含违背的契约名。
- **状态**：T

## TPP_05 Broken Windows：小破坏必须有归属

- **原始智慧**：破窗会改变团队的质量预期；看到坏味道不处理也不登记，就是默许它（第 1 章，Software Entropy）。
- **编译**：L5 流程 —— 回合结束前扫描触碰范围的坏味道：能顺手修的修；不能修的必须形成 debt record，含 owner、原因、回收条件。禁止"看到但无记录"。
- **验证信号**：触碰区坏味道净变化；新增 debt record 的关闭率；同一坏味道重复出现次数。
- **Goodhart 申报**：把大量小债登记成低质量 ticket 逃避修复。对策：debt record 必须绑定可验证触发条件；重复登记同一问题合并计数，不增加信用。
- **状态**：T

## TPP_06 Ruthless Testing + Automation：手工纪律必须迁到工具

- **原始智慧**：Pragmatic Projects 强调自动化、无情测试和团队级质量习惯；靠人记得运行检查是不可靠的（第 9 章）。
- **编译**：L5/L3 —— 每个仓库维护最小验证命令清单；提交前自动运行最窄有意义检查；新增规则必须进入 harness 或 CI，而不是只写进 README。
- **验证信号**：本地/CI 检查覆盖的变更类型；漏跑检查导致的返工次数；验证命令平均耗时。
- **Goodhart 申报**：验证清单膨胀到无人愿意跑。对策：分层命令：fast gate、targeted gate、full gate；默认只阻塞 fast + touched-scope targeted。
- **状态**：T

## 来源边界

- The Pragmatic Programmer 20th Anniversary Edition 目录：<https://pragprog.com/titles/tpp20/the-pragmatic-programmer-20th-anniversary-edition/>
