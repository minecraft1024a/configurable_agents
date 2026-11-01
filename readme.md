# 自定义 Agent

Neo-MoFox 插件，通过 TOML 数组定义多个 Agent。每个条目会成为独立的 Agent 组件，可单独设置主模型可见的描述、追加到默认系统提示词中的执行指引，以及 Agent 私有可用的工具。

> 这是 AI 编程作品，不建议参考。

## 配置

配置文件由 Neo-MoFox 首次加载插件时自动生成：

```text
config/plugins/configurable_agents/config.toml
```

每个 `[[agents]]` 表定义一个 Agent：

```toml
[plugin]
enabled = true

[[agents]]
enabled = true
name = "general"
description = "通用任务助手。根据任务选择合适的工具，执行后总结结果。"
usables = []
max_steps = 8

[[agents]]
enabled = true
name = "researcher"
description = "你是资料研究助手。先检索可靠信息，交叉核对后用中文归纳并注明不确定之处。"
usables = ["tool-mofox_docs:tool:docs_query"]
max_steps = 8
```

字段说明：

- `enabled`：是否注册这个 Agent。
- `name`：Agent 名称，只能使用以小写字母开头的小写字母、数字和下划线；所有启用项名称必须唯一。
- `description`：既用于主模型选择 Agent，也会追加到内置默认系统提示词中。默认提示词中的工具使用、安全和结果总结规则始终保留。
- `usables`：私有可用组件的完整签名列表。必须按组件类型添加前缀：`tool-<插件>:tool:<名称>`、`action-<插件>:action:<名称>` 或 `agent-<插件>:agent:<名称>`。例如 `tool-mofox_docs:tool:docs_query`。
- `max_steps`：工具调用轮数上限，范围为 1 到 32。

可用组件签名可在 Neo-MoFox 插件市场/组件列表中查看。引用的组件应在 Agent 被调用时已注册；未找到的组件会被跳过。请避免在同一个 Agent 中配置组件名相同的 Tool、Action 或 Agent，因为模型工具调用名会冲突。

## 行为

Agent 使用 `TOOL_USE` 模型任务执行 ReAct 工具调用循环。每轮会把工具结果交回模型继续处理，直到模型返回最终文本或达到 `max_steps`。每个 Agent 只能使用 `usables` 列出的私有组件。

新添加的配置 Agent 会在插件重载或 Neo-MoFox 重启后注册。插件 manifest 中预置了默认的 `general` Agent；分发带有其他 Agent 条目的版本时，应将其名称同步加入 `manifest.json` 的 `include` 列表。

## 开发

在插件根目录运行：

```bash
mpdt plugin check .
mpdt plugin build . --with-docs
```
