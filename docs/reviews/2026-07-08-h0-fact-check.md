# H0 外部事实核查记录（2026-07-08）

> 对应 [2026-07-08 对抗性评审](./2026-07-08-adversarial-review.md) 的 H0。目标不是证明本文所有判断成立，而是把可核查外部事实、解释性概括、待降级表述分开，防止方法论建立在错误归因或伪精确上。

## 核查结论

| 事实项 | 结论 | 处置 |
|---|---|---|
| Effective Java 3rd edition 条目编号 | 已核实。Pearson 样章目录列出 Item 9、10、11、12、17、34-40、42-44、55、57-64 等编号。 | 保留编号；把 Java `sealed` 表述为现代 Java 对受限类型集的补充机制，不再写成 Item 34-38 的直接吸收。 |
| Java records | 已核实。JEP 395 delivered in Java 16；records 自动提供 accessor、canonical constructor、`equals`、`hashCode`、`toString`，并以 final fields 表达数据载体。 | 保留 records 对 Item 10/11/12 的语言吸收判断；避免说 records 吸收了所有不可变性建议。 |
| Error Prone `MissingOverride` | 已核实。检查存在，默认 severity 是 `WARNING`，依据 Google Java Style，而不是 Effective Java 专属条目。 | 将“编译期报错”降级为“构建可配置为失败的静态检查”。 |
| Error Prone `EqualsHashCode` | 已核实。检查存在，severity 是 `ERROR`；官方说明引用 Effective Java 3rd Edition Item 11。 | 保留；明确它覆盖的是 equals/hashCode 成对契约，不代表 Item 10/11/12 全体。 |
| Error Prone `Immutable` | 已核实。检查存在，severity 是 `ERROR`；它验证带 `com.google.errorprone.annotations.Immutable` 的类型及相关继承/字段深不可变性，官方说明引用 Effective Java 3rd Edition Item 17。 | 降级为“可验证标注为 `@Immutable` 的深不可变类型”，不写成自动覆盖 Item 17 全部建议。 |
| APoSD 章节号与版次 | 已核实。Ousterhout 官方页说明 Second Edition 于 2021-07 发布，新增 Chapter 21，重写/扩展 Chapter 6。 | `aposd.md` 明确章节号按 Second Edition；修正重复的“第 12-15、14、18 章”。 |
| APoSD 复杂度三症状 | 已核实。Chapter 2 讨论 change amplification、cognitive load、unknown unknowns。 | 保留事实；删除“都可以从现有数据直接计算”的整体断言，该断言属于 H2 机制问题。 |
| Feathers 章节号 | 已核实。Pearson TOC：Chapter 4 seam model，Chapter 6 Sprout/Wrap，Chapter 13 characterization tests，Chapter 16 scratch refactoring，Chapter 25 dependency-breaking techniques。 | 保留。 |
| Feathers “24 种解依赖技术” | 已核实。Pearson TOC 在 Chapter 25 下列出 24 项，从 `Adapt Parameter` 到 `Text Redefinition`。 | 保留；后续若实现 FTH_03，应把 24 项转成按需加载的手术手册，而非常驻规则。 |
| Kent Beck 90% / 10% 引言 | 已核实原始来源，但当前中文直引过强。“一夜之间归零”不是原文；原意是技能经济价值变化。 | 改为意译并标注来源含义：90% 技能的经济价值降为 0，剩余 10% 的杠杆提高 1000x；不再使用中文直引号。 |
| METR 2025 19% / 20% | 已核实。METR 官方博客和 arXiv 摘要描述 16 名有经验 OSS 开发者、246 个任务；允许 AI 时完成时间增加 19%，研究后开发者仍估计 AI 让自己快 20%。 | 保留数字，但限定实验上下文；不得外推为所有开发任务的普遍结论。 |
| GitHub Spec Kit / Kiro | 已核实。Spec Kit 文档和 GitHub 博客把 specification 描述为 source of truth / executable artifact；Kiro docs 描述 requirements、design、tasks 三文件规格结构。 | 保留规格驱动方向；“代码是牲畜、规格是宠物”标为本文概括，不当作官方原文。 |
| Ralph loop | 已核实为一线 field report。Huntley 自述 Ralph 纯形态是 Bash loop；RepoMirror 报告 overnight 产出，但也属于轶事实践，不是受控实验。 | 降级为“field report / 轶事实践”，不再称为“极端实证”。 |
| Cognition `Don't Build Multi-Agents` | 已核实。2025 原文核心原则是 share context 和 actions carry implicit decisions；2026 follow-up 收窄为多 agent 可用于读/评审/智能贡献，但写入最好 single-threaded。 | 避免写成无条件反多 agent 结论；改为“parallel writer swarms 风险”与“写入保持单线程”的上下文工程经验。 |

## 主要来源

- Effective Java 3rd Edition Pearson sample pages: <https://ptgmedia.pearsoncmg.com/images/9780134685991/samplepages/9780134685991_CH05.pdf>
- JEP 395 Records: <https://openjdk.org/jeps/395>
- Error Prone `MissingOverride`: <https://errorprone.info/bugpattern/MissingOverride>
- Error Prone `EqualsHashCode`: <https://errorprone.info/bugpattern/EqualsHashCode>
- Error Prone `Immutable`: <https://errorprone.info/bugpattern/Immutable>
- John Ousterhout APOSD official page: <https://web.stanford.edu/~ouster/cgi-bin/aposd.php>
- Working Effectively with Legacy Code Pearson TOC: <https://www.pearson.de/media/muster/toc/toc_9780132931748.pdf>
- Working Effectively with Legacy Code Chapter 25 at O'Reilly: <https://www.oreilly.com/library/view/working-effectively-with/0131177052/ch25.html>
- METR 2025 study: <https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/>
- METR arXiv paper: <https://arxiv.org/abs/2507.09089>
- GitHub Spec Kit repository: <https://github.com/github/spec-kit>
- GitHub Spec Kit blog post: <https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/>
- Kiro specs documentation: <https://kiro.dev/docs/specs/>
- Geoffrey Huntley on Ralph: <https://ghuntley.com/ralph/>
- Cognition `Don't Build Multi-Agents`: <https://cognition.com/blog/dont-build-multi-agents>
- Cognition `Multi-Agents: What's Actually Working`: <https://cognition.ai/blog/multi-agents-working>
- Kent Beck, `90% of My Skills Are Now Worth $0`: <https://newsletter.kentbeck.com/p/90-of-my-skills-are-now-worth-0>
- Kent Beck, `More What, Less How`: <https://tidyfirst.substack.com/p/more-what-less-how>

## 后续约束

- 外部事实不得用“显然”“已经发生”等词替代来源。
- 工具覆盖只能写到官方文档实际声明的检查范围；不能把单个 bug pattern 扩张成整本书的实现。
- Field report 可以作为方法论启发，但不能写成受控实验证据。
- 版本、实验样本、适用范围必须和数字一起出现。
