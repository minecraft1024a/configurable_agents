"""可按配置创建的 Agent 基类和 ReAct 执行循环。"""

from __future__ import annotations

from typing import Annotated, ClassVar

from src.app.plugin_system.base import BaseAgent
from src.app.plugin_system.api import llm_api
from src.app.plugin_system.types import TaskType
from src.kernel.llm import LLMPayload, ROLE, Text, ToolResult


DEFAULT_SYSTEM_PROMPT = """你是一个由主聊天 Agent 调用的任务代理。你需要使用自己可用的工具完成用户交给你的任务。

工作流程：
1. 理解目标；在需要时先查询信息，再采取行动。
2. 根据工具返回的信息调整计划，逐步推进任务。
3. 任务完成、无法完成或需要用户补充信息时，停止调用工具并用中文清楚说明结果。

执行规则：
- 只使用本 Agent 已提供的工具，不要声称执行了实际未执行的操作。
- 调用有副作用的 action 前，确认该操作确实服务于用户目标。
- 工具失败时根据错误信息调整策略；不要无意义地重复相同调用。
- 最终答复应简洁，说明完成情况、关键结果和未完成原因。
"""


class GeneralAgent(BaseAgent):
    """默认 general Agent 和其他配置 Agent 共用的工具调用循环。"""

    name: ClassVar[str] = "general"
    description: ClassVar[str] = "通用任务助手。"
    usables: ClassVar[list[str]] = []
    max_steps: ClassVar[int] = 8

    async def execute(
        self,
        task: Annotated[str, "需要 Agent 完成的任务描述"],
    ) -> tuple[Annotated[bool, "是否成功"], Annotated[str, "执行结果"]]:
        """运行带工具调用的任务循环并返回最终结果。

        Args:
            task: 主模型传入的任务描述。

        Returns:
            是否成功以及 Agent 的最终答复。
        """
        if not task.strip():
            return False, "任务描述不能为空。"

        model_set = llm_api.get_model_set_by_task(TaskType.TOOL_USE.value)
        request = self.create_llm_request(
            model_set=model_set,
            request_name=f"configurable_agent_{self.name}",
            with_usables=True,
        )
        request.add_payload(
            LLMPayload(
                ROLE.SYSTEM,
                Text(
                    f"{DEFAULT_SYSTEM_PROMPT}\n"
                    "当前 Agent 的自定义描述和执行指引如下；请在保留以上默认规则的基础上遵循：\n"
                    f"{self.description}"
                ),
            )
        )
        request.add_payload(LLMPayload(ROLE.USER, Text(task)))

        response = await request.send(stream=False)
        await response

        for _ in range(self.max_steps):
            calls = response.call_list or []
            if not calls:
                result = (response.message or "").strip()
                return (bool(result), result or "Agent 未返回文本结果。")

            for call in calls:
                call_name = str(call.name)
                call_args = call.args if isinstance(call.args, dict) else {}
                try:
                    success, result = await self.execute_local_usable(
                        usable_name=call_name,
                        **call_args,
                    )
                except Exception as exc:  # noqa: BLE001 - 把单个工具错误交回模型处理
                    success, result = False, f"工具执行异常：{exc}"
                if not success:
                    result = f"工具调用失败：{result}"

                response.add_payload(
                    LLMPayload(
                        ROLE.TOOL_RESULT,
                        ToolResult(
                            value=result,
                            call_id=call.id,
                            name=call_name,
                        ),
                    )
                )

            response = await response.send(stream=False)
            await response

        if not (response.call_list or []):
            result = (response.message or "").strip()
            if result:
                return True, result

        return False, f"已达到最大工具调用轮数（{self.max_steps}），任务尚未完成。"
