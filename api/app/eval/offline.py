"""`run_eval --offline`: score the matcher from the caches only, never calling a model (#60).

    misses = CacheMisses()
    parse = with_cache(offline_parse_model, CacheOnly(SqliteLlmCache(), "parse", misses))
    compile_model_factory = offline_compile_model   # criteria come from the compile cache

The parse and judge models are the real ChatAnthropic ones, built with a placeholder API key:
the key is serialized as a secret reference, not its value, so they key `llm_cache` exactly as
a live run's models do. `CacheOnly` answers from the cache and raises `NotCached` on a miss
before LangChain sends anything, so the placeholder key never reaches the API. The compile model
is only built on a compile-cache miss (`compile_study` looks the trial up first), so offline it
raises `CompileNotCached` instead, which `match_trial` reports as an uncompiled trial.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.caches import RETURN_VAL_TYPE, BaseCache
from langchain_core.language_models import BaseChatModel

from app.pipeline.compile_criteria import CompileModelUnavailable
from app.pipeline.judge import anthropic_judge_model
from app.pipeline.parse_patient import anthropic_parse_model

Step = Literal["parse", "compile", "judge"]
STEPS: tuple[Step, ...] = ("parse", "compile", "judge")

# Never sent: every offline call is answered by `CacheOnly` or fails before a request.
OFFLINE_API_KEY = "offline-no-api-calls"


class NotCached(RuntimeError):
    """--offline: this answer is not in the cache, and asking the model is not allowed."""

    def __init__(self, step: Step) -> None:
        super().__init__(f"not cached: the {step} answer is not in the cache (--offline)")
        self.step = step


class CompileNotCached(NotCached, CompileModelUnavailable):
    """A compile-cache miss offline: the trial is reported uncompiled, like a missing key."""


@dataclass
class CacheMisses:
    """The calls an offline run would have sent to the API, per step (each prompt once)."""

    keys: dict[Step, set[tuple[str, str]]] = field(
        default_factory=lambda: {s: set() for s in STEPS}
    )

    def counts(self) -> dict[Step, int]:
        return {step: len(keys) for step, keys in self.keys.items()}


class CacheOnly(BaseCache):
    """`base`, but a miss raises `NotCached` (and is counted) instead of letting the model run.
    LangChain looks the prompt up before it calls the model, so a miss never sends a request."""

    def __init__(self, base: BaseCache, step: Step, misses: CacheMisses) -> None:
        self.base = base
        self.step: Step = step
        self.misses = misses

    def lookup(self, prompt: str, llm_string: str) -> RETURN_VAL_TYPE | None:
        hit = self.base.lookup(prompt, llm_string)
        if hit is None:
            self.misses.keys[self.step].add((prompt, llm_string))
            raise NotCached(self.step)
        return hit

    def update(self, prompt: str, llm_string: str, return_val: RETURN_VAL_TYPE) -> None:
        self.base.update(prompt, llm_string, return_val)  # unreachable: a miss raised above

    def clear(self, **kwargs: Any) -> None:
        self.base.clear(**kwargs)


def offline_parse_model() -> BaseChatModel:
    """The live parse model with a placeholder key: same cache key, no API key needed."""
    return anthropic_parse_model(api_key=OFFLINE_API_KEY)


def offline_judge_model() -> BaseChatModel:
    """The live judge model with a placeholder key: same cache key, no API key needed."""
    return anthropic_judge_model(api_key=OFFLINE_API_KEY)


def offline_compile_model() -> BaseChatModel:
    """Built only on a compile-cache miss, so offline it always raises."""
    raise CompileNotCached("compile")
