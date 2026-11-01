"""可按配置创建的 Agent 基类和 ReAct 执行循环。"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar

from src.app.plugin_system.base import BaseAgent, BaseTool
from src.app.plugin_system.api import llm_api
from src.kernel.llm import LLMPayload, ROLE, Text, ToolResult


DEFAULT_SYSTEM_PROMPT = """你是一个由主聊天 Agent 调用的任务代理。你需要使用自己可用的工具完成用户交给你的任务。

工作流程：
1. 理解目标；在需要时先查询信息，再采取行动。
2. 根据工具返回的信息调整计划，逐步推进任务。
3. 任务完成、无法完成或需要用户补充信息时，调用 tool-finish-mission 并用中文清楚说明结果。

执行规则：
- 只使用本 Agent 已提供的工具，不要声称执行了实际未执行的操作。
- 调用有副作用的 action 前，确认该操作确实服务于用户目标。
- 工具失败时根据错误信息调整策略；不要无意义地重复相同调用。
- 最终答复应简洁，说明完成情况、关键结果和未完成原因。
- 只有调用内置工具 tool-finish-mission 才能结束任务；调用时在 result 中填写最终结论，任务未成功时将 success 设为 false。
- 不得通过普通文本回复、停止调用工具或声称完成来结束任务；尚未调用 tool-finish-mission 时必须继续，直到达到最大交互轮数。
"""


class FinishMissionTool(BaseTool):
    """由 Agent 显式调用以结束当前任务。"""

    name: ClassVar[str] = "finish-mission"
    description: ClassVar[str] = (
        "显式结束当前 Agent 任务。仅当任务已经完成或确认无法继续时调用；"
        "必须在 result 中提供最终结论，未成功完成时将 success 设为 false。"
    )

    async def execute(
        self,
        result: Annotated[str, "提供给调用方的最终结论和任务结果"],
        success: Annotated[bool, "任务是否成功完成；无法完成时设为 false"] = True,
    ) -> tuple[Annotated[bool, "任务执行是否成功"], Annotated[str, "最终结论"]]:
        """校验显式结束请求并返回最终结论。"""
        conclusion = result.strip()
        if not conclusion:
            return False, "结束任务时必须提供非空的 result。"
        return success, conclusion


class GeneralAgent(BaseAgent):
    """默认 general Agent 和其他配置 Agent 共用的工具调用循环。"""

    name: ClassVar[str] = "general"
    description: ClassVar[str] = "通用任务助手。"
    associated_types: ClassVar[list[str]] = ["text"]
    model_task: ClassVar[str] = "tool_use"
    prompt: ClassVar[str] = ""
    usables: ClassVar[list[Any]] = []
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

        model_set = llm_api.get_model_set_by_task(self.model_task)
        request = self.create_llm_request(
            model_set=model_set,
            request_name=f"configurable_agent_{self.name}",
            with_usables=True,
        )
        system_prompt = DEFAULT_SYSTEM_PROMPT
        if self.prompt.strip():
            system_prompt += (
                "\n当前 Agent 的自定义提示词如下；请在保留以上默认规则的基础上遵循：\n"
                f"{self.prompt.strip()}"
            )
        request.add_payload(
            LLMPayload(
                ROLE.SYSTEM,
                Text(system_prompt),
            )
        )
        request.add_payload(LLMPayload(ROLE.USER, Text(task)))

        response = await request.send(stream=False)
        await response

        # 预留一轮用于在最后一轮普通工具操作后调用 finish-mission。
        for step_index in range(self.max_steps + 1):
            calls = response.call_list or []
            if not calls:
                if step_index >= self.max_steps:
                    last_message = (response.message or "").strip()
                    suffix = f"最后回复：{last_message}" if last_message else ""
                    return (
                        False,
                        f"Agent 已达到最大交互轮数（{self.max_steps}），"
                        f"但未调用 tool-finish-mission。{suffix}",
                    )
                # 普通文本不代表任务完成；继续请求直到显式结束或达到轮数上限。
                response = await response.send(stream=False)
                await response
                continue

            finish_call = next(
                (
                    call
                    for call in calls
                    if str(call.name) in {"tool-finish-mission", "finish-mission"}
                ),
                None,
            )
            if finish_call is not None:
                finish_args = (
                    finish_call.args if isinstance(finish_call.args, dict) else {}
                )
                conclusion = str(finish_args.get("result", "")).strip()
                if conclusion:
                    finish_success, finish_result = await FinishMissionTool(
                        plugin=self.plugin
                    ).execute(
                        result=conclusion,
                        success=bool(finish_args.get("success", True)),
                    )
                    return finish_success, str(finish_result)
                response.add_payload(
                    LLMPayload(
                        ROLE.TOOL_RESULT,
                        ToolResult(
                            value="结束任务时必须提供非空的 result。",
                            call_id=finish_call.id,
                            name=str(finish_call.name),
                        ),
                    )
                )
                calls = [call for call in calls if call is not finish_call]

            for call in calls:
                call_name = str(call.name)
                call_args = call.args if isinstance(call.args, dict) else {}
                if step_index >= self.max_steps:
                    return (
                        False,
                        f"Agent 已达到最大工具交互轮数（{self.max_steps}），"
                        "但未调用 tool-finish-mission。",
                    )

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

        return False, f"Agent 已达到最大交互轮数（{self.max_steps}），但未调用 tool-finish-mission。"
