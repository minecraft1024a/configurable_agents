"""自定义 Agent 插件入口。"""

from __future__ import annotations

import re
from typing import Any, cast

from src.app.plugin_system.base import BasePlugin, register_plugin
from src.kernel.logger import get_logger

from .components.agent import FinishMissionTool, GeneralAgent
from .config import ConfigurableAgentsConfig, MODEL_TASK_CHOICES


logger = get_logger("configurable_agents")
_PROFILE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_PREFIX_TYPES = {"tool-": "tool", "action-": "action", "agent-": "agent"}


def _normalize_usables(values: list[str], agent_name: str) -> list[str]:
    """检查前缀与完整组件签名，只保留合法的私有工具引用。"""
    normalized: list[str] = []
    for raw_value in values:
        value = raw_value.strip()
        prefix = next((item for item in _PREFIX_TYPES if value.startswith(item)), None)
        if prefix is None:
            logger.warning(
                f"Agent '{agent_name}' 的 usable '{value}' 缺少 tool-/action-/agent- 前缀，已忽略"
            )
            continue

        signature = value[len(prefix) :]
        parts = signature.split(":")
        if len(parts) != 3 or not all(parts) or parts[1] != _PREFIX_TYPES[prefix]:
            logger.warning(
                f"Agent '{agent_name}' 的 usable '{value}' 不是匹配前缀的完整组件签名，已忽略"
            )
            continue
        if parts[1] == "tool" and parts[2] == "finish-mission":
            logger.warning(
                f"Agent '{agent_name}' 的 usable '{value}' 与内置 tool-finish-mission 重名，已忽略"
            )
            continue
        # 配置中保留类型前缀用于校验；BaseAgent 的注册表解析只接收纯签名。
        if signature not in normalized:
            normalized.append(signature)
    return normalized


@register_plugin
class ConfigurableAgentsPlugin(BasePlugin):
    """从配置数组创建多个独立的 Agent 组件。"""

    plugin_name = "configurable_agents"
    configs = [ConfigurableAgentsConfig]
    dependent_components: list[str] = []

    def get_components(self) -> list[type]:
        """按配置为每个有效条目生成一个 Agent 类。"""
        cached = getattr(self, "_configured_agent_classes", None)
        if cached is not None:
            return cached

        config = cast(ConfigurableAgentsConfig | None, self.config)
        if config is None or not config.plugin.enabled:
            self._configured_agent_classes = []
            return self._configured_agent_classes

        components: list[type] = []
        seen_names: set[str] = set()
        for profile in config.agents:
            if not profile.enabled:
                continue

            agent_name = profile.name.strip()
            if not _PROFILE_NAME_PATTERN.fullmatch(agent_name):
                logger.warning(f"忽略名称不符合规范的 Agent：{agent_name!r}")
                continue
            if agent_name in seen_names:
                logger.warning(f"忽略重复的 Agent 名称：{agent_name}")
                continue
            seen_names.add(agent_name)

            attributes: dict[str, Any] = {
                "name": agent_name,
                "description": profile.description.strip(),
                "prompt": profile.prompt.strip(),
                "model_task": profile.model_task,
                "usables": [
                    FinishMissionTool,
                    *_normalize_usables(profile.usables, agent_name),
                ],
                "max_steps": profile.max_steps,
                "__module__": GeneralAgent.__module__,
                "__doc__": f"由配置创建的 {agent_name} Agent。",
            }
            if profile.model_task not in MODEL_TASK_CHOICES:
                logger.warning(
                    f"忽略 Agent '{agent_name}'：未知模型任务配置 '{profile.model_task}'"
                )
                continue
            if agent_name == "general":
                GeneralAgent.description = attributes["description"]
                GeneralAgent.prompt = attributes["prompt"]
                GeneralAgent.model_task = attributes["model_task"]
                GeneralAgent.usables = attributes["usables"]
                GeneralAgent.max_steps = attributes["max_steps"]
                components.extend([GeneralAgent])
                continue

            class_name = "".join(part.capitalize() for part in agent_name.split("_"))
            components.append(
                type(f"{class_name}ConfiguredAgent", (GeneralAgent,), attributes)
            )

        self._configured_agent_classes = components
        return components
