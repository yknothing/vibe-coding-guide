# 编译《Release It!》（Nygard）

> 选它的原因：前面几本书主要处理"能否正确构造软件"；Release It! 处理"软件在真实生产环境里如何失败"。Agent 会快速生成集成点和后台任务，却不会天然给它们配超时、舱壁、背压和可观测性。本书必须编译成生产边界门禁。
> 章节核查点：Stability Antipatterns、Stability Patterns；常见稳定性模式包括 Timeouts、Circuit Breaker、Bulkheads、Steady State、Fail Fast、Back Pressure、Shed Load。

---

## REL_01 Integration Point Budget：每个外部调用都要有失败语义

- **原始智慧**：集成点是生产故障的主要传播入口；远端故障会迅速变成你的故障（Stability Antipatterns / Integration Points）。
- **编译**：L3 + L5 —— 新增 HTTP/RPC/DB/queue 调用必须声明 timeout、retry、idempotency、fallback、错误分类。缺任一项阻塞，除非调用在启动期一次性执行且有明确失败策略。
- **验证信号**：外部调用中带 timeout 的比例；无界 retry 数；集成点导致的事故数。
- **Goodhart 申报**：随手填默认 timeout/retry，但不符合业务语义。对策：retry 必须说明幂等依据；timeout 必须来自 SLO 或上游预算，不接受无来源常量。
- **状态**：T

## REL_02 Circuit Breaker：连续失败要快速停止伤害

- **原始智慧**：Circuit Breaker 阻止对已失败依赖的持续调用，减少级联故障（Stability Patterns / Circuit Breaker）。
- **编译**：L3/L5 —— 高风险外部依赖必须具备熔断或等价保护；配置包含失败阈值、半开探测、恢复条件、fallback 行为。新增关键依赖无熔断需登记风险。
- **验证信号**：关键依赖熔断覆盖率；熔断打开/恢复事件；因依赖故障导致线程/连接耗尽的事故数。
- **Goodhart 申报**：熔断阈值过敏，正常抖动也切流；或 fallback 静默吞数据。对策：熔断事件必须可观测；fallback 必须区分降级、排队、拒绝和数据丢弃。
- **状态**：T

## REL_03 Bulkheads：资源池必须隔离失败域

- **原始智慧**：舱壁把失败限制在局部，不让一个依赖耗尽全局线程、连接或内存（Stability Patterns / Bulkheads）。
- **编译**：L3 + L6 —— 对外部依赖、队列消费者、后台任务使用独立资源池或并发限额；批判者检查"一个慢依赖能否拖垮整个进程"。
- **验证信号**：共享资源池中的关键依赖数；单依赖压测时其他路径的延迟变化；资源耗尽事故数。
- **Goodhart 申报**：配置太多微小池，制造碎片和饥饿。对策：舱壁按失败域和 SLO 划分，不按每个类/每个 endpoint 划分；池大小有容量依据。
- **状态**：T

## REL_04 Steady State：生产系统必须会自己打扫

- **原始智慧**：系统在无人工干预下应保持 steady state；日志、缓存、临时文件、队列积压都不能无限增长（Stability Patterns / Steady State）。
- **编译**：L3/L5 —— 新增持久化缓存、日志、队列、临时文件时，必须声明容量上限、清理策略、监控指标和告警阈值。
- **验证信号**：无上限资源清单；容量告警覆盖率；人工清理事件数。
- **Goodhart 申报**：设置清理任务但无验证，或者清理过激导致数据丢失。对策：清理策略必须有 dry-run 或指标验证；关键数据清理需要保留期和恢复路径。
- **状态**：T

## REL_05 Back Pressure / Shed Load：过载时要保护核心路径

- **原始智慧**：当系统无法处理全部流量时，正确动作是背压、排队、拒绝或降级，而不是排队到崩溃（Stability Patterns / Create Back Pressure / Shed Load）。
- **编译**：L5 + L6 —— 对高流量入口和异步消费者要求过载策略：队列上限、拒绝语义、优先级、降级路径、用户可见反馈。
- **验证信号**：队列无界点数量；负载测试中延迟曲线是否雪崩；降级路径演练结果。
- **Goodhart 申报**：把所有过载都返回通用错误，保护了系统但破坏用户关键路径。对策：按业务优先级定义 shed policy；关键路径优先保留，低价值任务先降级。
- **状态**：T

## 来源边界

- Release It! Chapter 5 stability patterns notes：<https://dekarlab.de/wp/?p=769>
- Martin Fowler on Circuit Breaker and Release It!：<https://martinfowler.com/bliki/CircuitBreaker.html>
