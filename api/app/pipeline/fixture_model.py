# HACK(demo): a fake chat model that replays saved compile outputs; used by pytest and by
# `scripts/compile_fixtures.py --fixtures` because no ANTHROPIC_API_KEY exists here yet.
"""FixtureChatModel: answers every call with one saved tool call (`CompiledCriteria` by
default), or with a scripted sequence of `replies` (the judge's retry tests).

It goes through the same `with_structured_output` path as ChatAnthropic (bind_tools ->
tool call -> PydanticToolsParser), so the compiler and the trace callbacks see a real-shaped
LangChain call. Token counts are estimated (~4 chars per token), not measured.
"""

import json
from pathlib import Path
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable

from app.config import API_DIR, get_settings

LLM_FIXTURES_DIR = API_DIR / "tests" / "fixtures" / "compile" / "llm"


def load_llm_fixture(nct_id: str, root: Path = LLM_FIXTURES_DIR) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((root / f"{nct_id}.json").read_text())
    return data


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class FixtureChatModel(BaseChatModel):
    output: dict[str, Any] = {}  # the tool-call args, i.e. a CompiledCriteria payload
    # Optional script, one reply per call (the last repeats): tool-call args, or None for a
    # prose answer with no tool call. Overrides `output` when set.
    replies: list[dict[str, Any] | None] = []
    tool_name: str = "CompiledCriteria"
    # Reported as the model id so the trace shows what the real call would cost.
    model_name: str = ""
    calls: int = 0

    def model_post_init(self, context: Any) -> None:
        if not self.model_name:
            self.model_name = get_settings().model_compile

    @property
    def _llm_type(self) -> str:
        return "fixture"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Runnable[LanguageModelInput, AIMessage]:
        return self

    def _result(self, messages: list[BaseMessage]) -> ChatResult:
        self.calls += 1
        args = self.replies[min(self.calls, len(self.replies)) - 1] if self.replies else self.output
        prompt = "".join(str(m.content) for m in messages)
        tokens_in = _estimate_tokens(prompt)
        tokens_out = _estimate_tokens(json.dumps(args))
        call_id = f"fixture-{self.calls}"
        message = AIMessage(
            content="" if args is not None else "I cannot answer with the tool.",
            tool_calls=(
                [] if args is None else [{"name": self.tool_name, "args": args, "id": call_id}]
            ),
            usage_metadata={
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._result(messages)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._result(messages)
