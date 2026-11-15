"""A SQLite-backed LangChain LLM cache for the eval, so a warm re-run is reproducible.

    factory = with_cache(anthropic_judge_model, SqliteLlmCache())
    model = factory()            # the same model, answering repeated prompts from `llm_cache`

Temperature 0 is not enough to make two eval runs agree: the API can still answer a repeated
prompt differently. The eval therefore stores every answer under a hash of the full prompt and
the model's settings (model id, bound tools, temperature, ...) and replays it on the next run.
A changed prompt file, criterion, note or model id is a different key, so it asks the model
again. The LangChain callbacks still fire on a hit, so the trace shows the replayed call.

Only the eval installs the cache; live match runs always ask the model.
"""

import hashlib
import warnings
from collections.abc import Callable
from typing import Any

from langchain_core._api import LangChainBetaWarning
from langchain_core.caches import RETURN_VAL_TYPE, BaseCache
from langchain_core.language_models import BaseChatModel
from langchain_core.load import dumps, loads
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import delete

from app.db import LlmCacheRow, session_scope, utcnow


def _key(prompt: str, llm_string: str) -> str:
    return hashlib.sha256(f"{llm_string}\n\x00\n{prompt}".encode()).hexdigest()


class SqliteLlmCache(BaseCache):
    """LangChain `BaseCache` over the `llm_cache` table of the app database."""

    def lookup(self, prompt: str, llm_string: str) -> RETURN_VAL_TYPE | None:
        with session_scope() as s:
            row = s.get(LlmCacheRow, _key(prompt, llm_string))
            stored = list(row.generations) if row else None
        if stored is None:
            return None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LangChainBetaWarning)  # `loads` is marked beta
            return [loads(g, allowed_objects="all") for g in stored]

    def update(self, prompt: str, llm_string: str, return_val: RETURN_VAL_TYPE) -> None:
        # One atomic upsert: two identical prompts in flight at once both write, neither fails.
        values = {"key": _key(prompt, llm_string), "generations": [dumps(g) for g in return_val]}
        stmt = sqlite_insert(LlmCacheRow).values(**values, created_at=utcnow())
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"], set_={"generations": stmt.excluded.generations}
        )
        with session_scope() as s:
            s.exec(stmt)

    def clear(self, **kwargs: Any) -> None:
        with session_scope() as s:
            s.exec(delete(LlmCacheRow))


def with_cache[M: BaseChatModel](factory: Callable[[], M], cache: BaseCache) -> Callable[[], M]:
    """`factory`, with every model it builds answering through `cache`."""

    def build() -> M:
        model = factory()
        model.cache = cache
        return model

    return build
