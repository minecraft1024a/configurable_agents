"""自定义 Agent 插件配置。"""

from __future__ import annotations

from typing import ClassVar

from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section

MODEL_TASK_CHOICES = [
    "utils",
    "utils_small",
    "actor",
    "sub_actor",
    "vlm",
    "voice",
    "video",
    "tool_use",
]


class ConfigurableAgentsConfig(BaseConfig):
    """定义插件开关和可由数组配置的 Agent。"""

    name: ClassVar[str] = "config"
    description: ClassVar[str] = "自定义 Agent 插件配置"

    @config_section("plugin", title="插件设置", tag="plugin")
    class PluginSection(SectionBase):
        """控制插件是否启用。"""

        enabled: bool = Field(default=True, description="是否启用自定义 Agent 插件")

    @config_section("agents", title="自定义 Agent 列表", tag="ai")
    class AgentSection(SectionBase):
        """定义单个 Agent 的名称、主模型描述、提示词补充和私有工具。"""

        enabled: bool = Field(default=True, description="是否注册这个 Agent")
        name: str = Field(
            default="general",
            min_length=1,
            max_length=48,
            pattern=r"^[a-z][a-z0-9_]*$",
            description="Agent 名称，只允许小写字母、数字和下划线，且以字母开头",
        )
        description: str = Field(
            default="通用任务助手。根据任务选择合适的工具，执行后总结结果。",
            min_length=1,
            description="Agent 描述，仅展示给 MoFox 主调用模型，用于判断何时调用该 Agent",
            input_type="textarea",
            rows=4,
        )
        prompt: str = Field(
            default="",
            description="追加到 Agent 内置默认系统提示词后的自定义提示词；留空时只使用默认提示词",
            input_type="textarea",
            rows=6,
        )
        model_task: str = Field(
            default="tool_use",
            choices=MODEL_TASK_CHOICES,
            description="选择 config/model.toml 中用于这个 Agent 的模型任务配置",
            label="模型任务配置",
            tag="ai",
            input_type="select",
        )
        usables: list[str] = Field(
            default_factory=list,
            description=(
                "Agent 私有工具签名列表。每项必须用 tool-、action- 或 agent- 前缀，"
                "后接完整签名，如 tool-other_plugin:tool:search。"
            ),
            input_type="list",
            item_type="str",
        )
        max_steps: int = Field(
            default=8,
            ge=1,
            le=256,
            description="Agent 最多执行的模型交互轮数，额外保留一轮显式结束机会；仍未结束则失败，范围 1 到 256",
        )

    plugin: PluginSection = Field(default_factory=PluginSection)
    agents: list["ConfigurableAgentsConfig.AgentSection"] = Field(
        default_factory=lambda: [ConfigurableAgentsConfig.AgentSection()],
        description="自定义 Agent 数组；每个数组项注册为一个独立 Agent",
    )


ConfigurableAgentsConfig.model_rebuild()
