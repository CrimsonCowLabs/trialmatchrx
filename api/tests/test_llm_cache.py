"""The eval's SQLite LLM response cache: a repeated call is answered from `llm_cache`."""

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.eval.llm_cache import SqliteLlmCache, with_cache
from app.pipeline.fixture_model import FixtureChatModel


class Answer(BaseModel):
    """A one-field structured answer."""

    text: str


def _model(text: str) -> FixtureChatModel:
    return FixtureChatModel(output={"text": text}, tool_name="Answer", model_name="m-1")


async def _ask(model: FixtureChatModel, question: str) -> Answer:
    result = await model.with_structured_output(Answer).ainvoke([HumanMessage(question)])
    assert isinstance(result, Answer)
    return result


async def test_a_repeated_call_is_answered_from_the_cache_across_processes() -> None:
    first = with_cache(lambda: _model("from the model"), SqliteLlmCache())()
    assert (await _ask(first, "same question")).text == "from the model"

    # A fresh cache object over the same database (a later `make eval`) and a model that would
    # answer differently: the stored answer comes back and the model is never called.
    later = with_cache(lambda: _model("a different answer"), SqliteLlmCache())()
    assert (await _ask(later, "same question")).text == "from the model"
    assert later.calls == 0


async def test_a_different_prompt_misses_the_cache() -> None:
    cache = SqliteLlmCache()
    await _ask(with_cache(lambda: _model("one"), cache)(), "question one")

    model = with_cache(lambda: _model("two"), cache)()
    assert (await _ask(model, "question two")).text == "two"
    assert model.calls == 1


async def test_a_different_model_misses_the_cache() -> None:
    cache = SqliteLlmCache()
    await _ask(with_cache(lambda: _model("one"), cache)(), "q")

    other = FixtureChatModel(output={"text": "two"}, tool_name="Answer", model_name="m-2")
    other = with_cache(lambda: other, cache)()
    assert (await _ask(other, "q")).text == "two"
