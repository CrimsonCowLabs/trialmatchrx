"""Compile the 10 fixture trials and print the compile rate (share of criteria with a predicate).

    uv run python -m scripts.compile_fixtures              # real Sonnet (needs ANTHROPIC_API_KEY)
    uv run python -m scripts.compile_fixtures --fixtures   # saved LLM outputs, no network
    uv run python -m scripts.compile_fixtures --force NCT07271186

Real runs use the app database (so the compile cache warms up). `--fixtures` runs use a
throwaway database so hand-authored outputs never land in the real cache.
"""

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

from app import db
from app.config import get_settings
from app.pipeline.compile_criteria import (
    ModelFactory,
    anthropic_compile_model,
    compile_rate,
    compile_study,
    predicate_count,
)
from app.pipeline.fixture_model import FixtureChatModel, load_llm_fixture
from app.pipeline.study_source import fixture_nct_ids, load_fixture_study
from app.trace.runner import traced_run


def _factory(nct: str, use_fixtures: bool) -> ModelFactory:
    if not use_fixtures:
        return anthropic_compile_model
    # HACK(demo): hand-authored outputs, not recorded from a live model.
    output = load_llm_fixture(nct)
    return lambda: FixtureChatModel(output=output)


async def run(ncts: list[str], *, use_fixtures: bool, force: bool) -> None:
    total = with_predicate = 0
    print(f"{'nct':<12} {'criteria':>8} {'predicate':>9} {'rate':>6}  run_id")
    for nct in ncts:
        study = load_fixture_study(nct)
        async with traced_run("compile", {"nct": nct, "force": force}) as trace:
            criteria = await compile_study(
                study,
                trace.recorder,
                model_factory=_factory(nct, use_fixtures),
                force=force,
            )
            trace.result = {"criteria": [c.model_dump(mode="json") for c in criteria]}
        n, k, rate_or_none = len(criteria), predicate_count(criteria), compile_rate(criteria)
        total, with_predicate = total + n, with_predicate + k
        rate = f"{rate_or_none:.0%}" if rate_or_none is not None else "-"
        print(f"{nct:<12} {n:>8} {k:>9} {rate:>6}  {trace.run_id}")
    overall = with_predicate / total if total else 0.0
    print(f"{'overall':<12} {total:>8} {with_predicate:>9} {overall:>6.0%}")
    print(f"compile rate: {overall:.1%} ({with_predicate}/{total} criteria have a predicate)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ncts", nargs="*", help="NCT ids (default: all fixture trials)")
    parser.add_argument("--fixtures", action="store_true", help="use saved LLM outputs")
    parser.add_argument("--force", action="store_true", help="bypass the compile cache")
    args = parser.parse_args()

    if not args.fixtures and not get_settings().anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY is not set; pass --fixtures to use the saved LLM outputs")

    with tempfile.TemporaryDirectory() as tmp:
        if args.fixtures:
            db.set_engine(db.make_engine(f"sqlite:///{Path(tmp) / 'compile_fixtures.db'}"))
        db.init_db()
        ncts = args.ncts or fixture_nct_ids()
        asyncio.run(run(ncts, use_fixtures=args.fixtures, force=args.force))
        db.get_engine().dispose()


if __name__ == "__main__":
    main()
