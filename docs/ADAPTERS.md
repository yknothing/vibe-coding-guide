# IDE-neutral adapter contract

> 本页是质量门禁的安装部署边界。核心原则：检测逻辑只在一个 IDE-neutral
> core 中实现；Codex、Claude Code、Cursor、Qoder、Trae、Droid 等入口只做薄 adapter，
> 把各自事件转成同一份输入契约，再消费同一份 JSON report。

## 状态分级

| 状态 | 含义 |
|---|---|
| `planned` | 路线已列入矩阵，但 native adapter 尚无安装说明或 smoke。 |
| `unsupported` | 尚未定义入口，不应在 README 或发布说明中宣称可用。 |
| `documented` | 已有安装说明或 adapter contract，但尚未通过本仓库 smoke test。 |
| `smoke-tested` | 有可重放 smoke 命令，能证明入口会调用 core 并产生预期 report。 |
| `dogfooded` | 本仓库日常使用该入口，并保留失败/通过记录。 |

未达到 `smoke-tested` 的目标只能称为 planned 或 documented，不能称为 supported。

## Core 输入契约

所有 adapter 最终都应提供这些字段；拿不到的字段必须显式为 `null` 或省略后由 core
标记为 unavailable，不得编造。

当前内部规范化契约版本是 `quality-gate-request/v1`。Generic CLI 与 Claude Code
PostToolUse 都必须先投影成这一请求对象，scan core 不直接解释原始 adapter payload。

| 字段 | 必需 | 说明 |
|---|---|---|
| `cwd` | 是 | 规范化后的绝对项目根目录。文件和 baseline 的相对路径都基于它解析。 |
| `files` | 是 | 本轮要扫描的文件列表。hook 无法直接给出时，可由 adapter 从 git diff/status 推导。 |
| `event_source` | 是 | 事件来源，例如 `generic-cli`、`claude-code-post-tool-use`、`codex-cli`。 |
| `tool_name` | 否 | IDE/CLI 暴露的工具名，例如 `Edit`、`Write`、`Bash`。 |
| `baseline_path` | 否 | 棘轮 baseline JSON；没有时 report 必须是 `not_configured`。 |
| `strict` | 是 | 是否要求本次扫描文件适用的外部 detector 成功。它来自受信任 CLI 配置，原始 IDE 事件不得覆盖。 |
| `adapter_metadata` | 否 | adapter 自己的版本、配置文件路径、触发器名称等。 |

当前 core 的最小入口是：

```bash
python3 hooks/post_tool_use_quality_gate.py --files path/to/file.py --format json
python3 hooks/post_tool_use_quality_gate.py --hook --format json
```

`--hook` 与 `--files` 互斥；混用会返回结构化 `hook-input` error，不能选择其中一个后仍
宣称来自另一个入口。Claude 的宽松路径提取只存在于 Claude 投影层，不属于 core 规则。
报告 `source.request_schema_version` 记录实际使用的规范化请求版本。

`--doctor` 用来检查本机是否具备启用 strict gate 的条件：

```bash
python3 hooks/post_tool_use_quality_gate.py --doctor --format json
python3 hooks/post_tool_use_quality_gate.py --doctor --require-tools
```

`quality-gate-doctor/v1` 的 `install_plan` 是安装提示契约。adapter 或安装脚本在缺工具时应展示：

| Tool | What it is | Gate role | Recommended command |
|---|---|---|---|
| `ruff` | Fast Python linter | Python 魔法数字检测，使用 Ruff `PLR2004`。 | `python3 -m pip install --upgrade ruff` |
| `lizard` | Cyclomatic complexity analyzer | 函数圈复杂度检测，用于 `IMP_007`。 | `python3 -m pip install --upgrade lizard` |
| `eslint` | JavaScript and TypeScript linter | JS/TS 魔法数字检测，使用 `no-magic-numbers`。 | `npm install -g eslint` |

快捷安装可使用 `quick_install_commands`，当前缺三项时是：

```bash
python3 -m pip install --upgrade ruff lizard
npm install -g eslint
```

安全边界：这些命令只供人工确认后执行；adapter 和安装器不得静默执行。只使用 PyPI/npm、
组织批准的内部镜像或 pinned/approved toolchain；Do not use `curl | sh` installers；
Windows、no-global-npm 或受控环境应使用等价安装方式，并确保 detector 在 hook 的 `PATH` 中。
安装后必须重跑 `python3 hooks/post_tool_use_quality_gate.py --doctor --require-tools` 并确认
`strict_ready: true`。

## Doctor 输出契约

`quality-gate-doctor/v1` 只用于安装、部署和 adapter readiness 检查。adapter 可以展示
doctor report，但不能把 doctor-only 字段当成普通 scan report 的字段。

关键字段：

| 字段 | 说明 |
|---|---|
| `schema_version` | 当前为 `quality-gate-doctor/v1`。 |
| `status` | `pass`、`warn` 或 `fail`。 |
| `strict_ready` | 是否满足启用 strict gate 的前置条件。 |
| `detectors` | `ruff`、`eslint`、`lizard` 的可用性、路径、版本和安装元数据。 |
| `tool_catalog` | strict mode 依赖工具的用途、安装命令、验证命令和安全提示。 |
| `install_plan` | 当前缺失工具的安装计划；安装器应直接展示，不应静默安装。 |
| `quick_install_commands` | 针对当前缺失工具折叠后的快捷命令，只能在用户确认后执行。 |
| `checks` | runtime、项目根、规则加载、detector readiness 等检查项。 |
| `next_steps` | 当前状态下的下一步动作。 |

## Core 输出契约

adapter 必须把 JSON report 原样保留或转发给上层 UI，不应只截取人类文本。

关键字段：

| 字段 | 说明 |
|---|---|
| `schema_version` | 当前为 `quality-gate-report/v1`。 |
| `run_id` | 单次运行 ID，用于跨日志关联。 |
| `status` | `pass`、`fail`、`error` 或 `incomplete`。 |
| `source` | core 看到的入口模式与 adapter 名称。 |
| `decision` | `pass`、`observe`、`warn`、`block`、`error` 或 `incomplete`，以及各 enforcement 计数和 rule ids。 |
| `policy` | 本次 effective complexity threshold、YAML baseline 和最终来源。 |
| `detectors` | `ruff`、`eslint`、`lizard` 的可用性、路径、版本，以及 `detectors.<name>.run` 本次执行状态。 |
| `scanned_files` | 实际扫描的文件。 |
| `skipped_files` | 未扫描文件及原因。skipped-only 不能视为 pass。 |
| `metrics` | 当前可计算质量指标。 |
| `ratchet` | 棘轮状态；未传 baseline 时必须显示 `not_configured`。 |
| `issues` | 规则命中，使用稳定 `rule_id`。 |
| `tool_errors` | detector、输入、规则加载或 baseline 读取错误。 |
| `summary` | 计数摘要。 |

`detectors.<name>.run.status` 是 `succeeded`、`not_applicable`、`missing`、
`failed` 或 `ignored`；`coverage` 是 `complete`、`fallback` 或 `none`。
`uncovered_files` 列出 fallback 无法等价覆盖的请求文件；非空时必须进入 `tool_errors`。
`not_applicable` 表示当前 profile 不需要该工具，不等于缺失。TypeScript ignored、parser、
fatal 或 configuration diagnostic 必须进入 `tool_errors`，不得降级成 `pass`。
lizard 的空 CSV 本身不构成覆盖证明；core 会要求 XML File measure 显式包含零函数文件。

规则必须显式声明 `gate.enforcement`，不得从 severity、action 或 state 推断。当前策略是：
`IMP_004/IMP_007=block`、`MNT_001=warn`、`DSN_001/MNT_002=observe`。
`rules/IMP_007.yml` 的 threshold 是基线；CLI 或 `VCG_COMPLEXITY_THRESHOLD` 只能用更小的
正整数收紧，尝试放宽会成为 `rule-config` error。`warn` 和 `observe` 保留 issues 并退出 0；
adapter 必须读取 `decision`，不能仅凭 top-level `status: pass` 丢弃非阻断发现。

## 能力矩阵

| Target | Native 状态 | 当前可用入口 | 最小验收 |
|---|---|---|---|
| Generic CLI | `smoke-tested` | `--files` | 对 clean/bad Python 文件分别返回 `pass`/`fail`，并输出 JSON report。 |
| Claude Code | `documented` | `PostToolUse` 调用 `--hook` | 项目 hook 配置触发 `Edit`、`Write`、`MultiEdit`、`Bash` 后，bad file exit 2，clean file exit 0。 |
| Codex | `planned` | Generic CLI fallback | 在 Codex 任务中用 `--files` 或 git diff 文件列表调用 core；native adapter 待验证。 |
| Cursor | `planned` | Generic CLI fallback | 在 Cursor 任务后能调用 core 并保留 JSON report；native adapter 待验证。 |
| Qoder | `planned` | Generic CLI fallback | 在 Qoder 任务后能调用 core 并保留 JSON report；native adapter 待验证。 |
| Trae | `planned` | Generic CLI fallback | 在 Trae 任务后能调用 core 并保留 JSON report；native adapter 待验证。 |
| Droid | `planned` | Generic CLI fallback | 在 Droid 任务后能调用 core 并保留 JSON report；native adapter 待验证。 |

## 不可宣称的内容

- 未通过 smoke test 的目标不得称为已支持。
- 缺 `baseline_path` 不代表 ratchet 已保护当前改动。
- `skipped_files` 不为空时，不得把零扫描解读成质量良好。
- 缺 context/defect 数据时，不得从 dashboard 推断无成本、无缺陷或无逃逸。
- adapter 不能把适用 detector 的缺失或失败降级成 pass；strict scan 必须 fail closed。
