"""ScriptedChatModel: a fake tool-calling chat model for agent tests. It answers call N with
`replies[N]` (the last one repeats), giving every tool call a fresh id, so a LangGraph agent
loops over it exactly as it would over Sonnet. No network."""

from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable


def reply(text: str = "", *calls: tuple[str, dict[str, Any]]) -> AIMessage:
    """One scripted turn: some text (the agent's thought) and zero or more tool calls."""
    return AIMessage(content=text, tool_calls=[{"name": n, "args": a, "id": n} for n, a in calls])


class ScriptedChatModel(BaseChatModel):
    replies: list[AIMessage]
    model_name: str = "claude-sonnet-4-5"
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Runnable[LanguageModelInput, AIMessage]:
        return self

    def _result(self) -> ChatResult:
        self.calls += 1
        script = self.replies[min(self.calls, len(self.replies)) - 1]
        message = AIMessage(
            content=script.content,
            tool_calls=[{**c, "id": f"{c['id']}-{self.calls}"} for c in script.tool_calls],
            usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._result()

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._result()
