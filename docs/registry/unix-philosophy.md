# 编译 Unix 哲学（McIlroy / Raymond）

> 选它的原因：Unix 哲学是小工具、组合性、文本接口和透明性的工程极简主义。Agent 容易生成全能脚本、隐藏状态和不可组合 CLI；Unix 哲学适合编译成接口形状与可观测性门禁。
> 核查点：McIlroy 的三句总结是"do one thing well / work together / handle text streams"；《The Art of Unix Programming》第 1 章整理了 modularity、composition、separation、simplicity、parsimony、transparency 等规则。

---

## UNIX_01 Do One Thing Well：工具必须有单一动词

- **原始智慧**：程序应做好一件事；复杂任务靠组合完成（McIlroy / TAOUP Rule of Modularity, Parsimony）。
- **编译**：L3/L6 —— CLI、script、agent tool 新增时检查命令名和 help：是否包含多个并列动词、多个不相关模式、过多 flags。L6 裁决哪些模式应拆成可组合子命令。
- **验证信号**：命令 flag 数、互斥 mode 数、help 长度；调用方是否只用其中一小部分能力。
- **Goodhart 申报**：机械拆成大量微工具，反而增加编排负担。对策：拆分以稳定数据边界和复用场景为准，不以函数数量为准。
- **状态**：T

## UNIX_02 Composition：默认接口要可管道化

- **原始智慧**：程序要能协作；文本流是通用接口（McIlroy summary / Rule of Composition）。
- **编译**：L3/L5 —— CLI 默认支持 stdin/stdout 或结构化 JSONL；错误走 stderr；批处理支持文件列表；输出稳定可被下游解析。人类漂亮输出需显式 `--pretty`。
- **验证信号**：命令能否参与 pipeline；输出 schema 破坏次数；下游解析失败数。
- **Goodhart 申报**：所有输出都变成松散文本，机器解析脆弱。对策：优先 JSON/JSONL/TSV 等明确格式；文本是可读层，不是唯一契约。
- **状态**：T

## UNIX_03 Separation：机制和策略分离

- **原始智慧**：机制与策略、接口与引擎应分离（TAOUP Rule of Separation）。
- **编译**：L6 + L3 —— 新增模块时问："这段代码是在执行机制，还是把某个产品策略硬编码进机制？" L3 扫描硬编码阈值、环境名、租户名、策略分支。
- **验证信号**：策略常量硬编码数；机制模块因产品策略变化被触碰次数；配置项是否有 owner 和范围。
- **Goodhart 申报**：把所有东西都外置配置，制造配置语言和运行时不确定性。对策：只有易变策略外置；稳定不变量留在代码和类型里。
- **状态**：T

## UNIX_04 Transparency：状态和控制流要可检查

- **原始智慧**：透明性和可检查性让系统更容易调试和组合（TAOUP Rule of Transparency）。
- **编译**：L5/L3 —— 工具必须有 dry-run、explain、verbose 或 trace 入口之一；关键决策输出可审计原因；长任务可报告进度与中间状态。
- **验证信号**：不可解释失败数；dry-run 覆盖率；生产问题中需要临时加日志的次数。
- **Goodhart 申报**：verbose 日志淹没有用信号。对策：trace 分层；默认安静，debug 可打开，机器事件结构化。
- **状态**：T

## UNIX_05 Repair：失败要靠近原因并给下游可处理信号

- **原始智慧**：Unix 工具倾向让错误显性并可组合处理；TAOUP 的 Rule of Repair 强调尽早、响亮地失败。
- **编译**：L3/L5 —— CLI/工具错误必须有非零 exit code、稳定错误码、stderr 诊断；部分失败要能机器判读，不允许只打印"failed"。
- **验证信号**：错误码覆盖率；调用方依赖字符串匹配错误的次数；失败定位时间。
- **Goodhart 申报**：错误码过细，调用方无法稳定处理。对策：少数稳定错误类别 + 结构化 detail；detail 不作为兼容契约。
- **状态**：T

## UNIX_06 Generation：重复样板应由机器生成，但生成物要有边界

- **原始智慧**：Unix 传统重视让机器做机械工作；TAOUP Rule of Generation 鼓励避免手写可生成样板。
- **编译**：L5 —— 若同类样板第三次出现，必须考虑生成器、模板或 schema-first；生成物目录、来源、禁止手改规则要显式。
- **验证信号**：重复样板数量；生成物手工修改次数；schema 与生成物漂移次数。
- **Goodhart 申报**：为少量重复引入复杂生成器，或生成器成为没人懂的新核心。对策：生成器要比被替代样板短且可测试；没有第二个消费者前不引入。
- **状态**：T

## 来源边界

- McIlroy 三句 Unix philosophy：<https://cscie2x.dce.harvard.edu/hw/ch01s06.html>
- The Art of Unix Programming HTML：<https://www.catb.org/esr/writings/taoup/html/>
