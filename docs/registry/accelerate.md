# 编译《Accelerate / DORA》

> 选它的原因：前面的登记册多是微观工程机制；Accelerate/DORA 给出宏观反馈闭环。Agent 时代最危险的管理幻觉是"代码生成变快 = 组织交付变快"。DORA 指标把速度与稳定性绑定，能防止只优化吞吐。
> 核查点：四个核心软件交付绩效指标是 deployment frequency、lead time for changes、change failure rate、failed deployment recovery time / MTTR；近期 DORA 指南还把 reliability 作为补充能力维度。

---

## ACC_01 Four Key Metrics：速度指标必须配稳定性指标

- **原始智慧**：软件交付绩效不能靠 LOC、工时或 story point 衡量；四个指标同时看吞吐与稳定性（Accelerate / DORA metrics）。
- **编译**：L5/L4 仪表盘 —— release harness 记录 deployment frequency、change lead time、change failure rate、failed deployment recovery time。任何"提速"主张必须同时展示稳定性没有恶化。
- **验证信号**：四指标趋势；按服务/团队分层后的瓶颈；事故恢复时间分布。
- **Goodhart 申报**：拆小部署刷 deployment frequency，或把失败改名为"已知问题"降低 change failure rate。对策：部署按用户可见变更和回滚/补丁事件归因；失败来源固定，unknown 计入。
- **状态**：T

## ACC_02 Lead Time Decomposition：只量总耗时不够，要定位等待

- **原始智慧**：lead time for changes 衡量从 commit 到生产的流动；高绩效来自减少等待和批量，而不是催人加速。
- **编译**：L5 —— pipeline 记录 commit→review→merge→deploy→verify 各段时间。超过阈值时生成 bottleneck report，不直接责备个人。
- **验证信号**：各段等待时间 P50/P95；review 队列长度；部署批大小。
- **Goodhart 申报**：跳过 review 或合并未验证代码来缩短 lead time。对策：lead time 必须与 change failure rate 和 review finding density 一起看。
- **状态**：T

## ACC_03 Deployment Independence：架构质量要看能否独立交付

- **原始智慧**：Accelerate 研究把架构能力与交付绩效连接：团队能否独立测试、部署、发布其服务，是架构健康信号。
- **编译**：L6 + L5 —— 架构评审必答："这个团队能否在不协调其他团队的情况下测试和部署本变更？不能的话，阻塞点是什么？" 阻塞点进入架构债。
- **验证信号**：跨团队协调部署次数；被共享数据库/共享库阻塞的发布数；独立回滚能力。
- **Goodhart 申报**：为独立部署而复制数据和逻辑，造成一致性债。对策：独立性与数据所有权、同步协议、重复知识扫描一起评估。
- **状态**：T

## ACC_04 Continuous Delivery：可发布性必须常态化

- **原始智慧**：持续交付实践通过自动化测试、版本控制、trunk-based development、deployment automation 降低发布风险。
- **编译**：L5/L3 —— 主干必须持续可发布：短生命周期分支、自动测试、可重复部署、回滚或前滚路径。长分支和手工发布步骤进入 risk register。
- **验证信号**：分支存活时间；部署自动化覆盖率；手工发布步骤数；回滚演练成功率。
- **Goodhart 申报**：把未完成行为藏在 feature flag 后长期滞留。对策：flag 必须有 owner、过期日期和清理任务；长期 flag 计入复杂度预算。
- **状态**：T

## ACC_05 Learning Culture：指标是学习工具，不是排名工具

- **原始智慧**：DORA/Accelerate 强调文化、精益管理和持续改进；指标若用于惩罚，会被团队游戏化。
- **编译**：L8 治理规则 —— DORA 指标只能用于系统瓶颈改进，不用于个人排名。每次指标异常必须配 retro：系统原因、实验、预期验证。
- **验证信号**：指标异常后的改进行动关闭率；重复瓶颈数；团队是否开始隐藏失败。
- **Goodhart 申报**：管理层把团队指标变成排行榜，导致失败瞒报。对策：change failure 与 incident 数据来源独立采集；retro 关注流程改进，不追个人归因。
- **状态**：T

## 来源边界

- DORA metrics guide：<https://dora.dev/guides/dora-metrics/>
- Google Cloud Four Keys overview：<https://cloud.google.com/blog/products/devops-sre/using-the-four-keys-to-measure-your-devops-performance>
