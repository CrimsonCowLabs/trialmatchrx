"""Pre-fetch recruiting T2D/CKD trials near Sacramento into the trials cache (hits the network).

    make seed                                   # or: cd api && uv run python -m scripts.seed_trials
    uv run python -m scripts.seed_trials --radius 50

Overlapping conditions dedupe on (NCT ID, lastUpdatePostDate); re-running only adds trials that
are new or changed upstream.
"""

import argparse
import asyncio

from app.config import get_settings
from app.db import init_db
from app.sources import ctgov

CONDITIONS = [
    "type 2 diabetes",
    "diabetes mellitus",
    "chronic kidney disease",
    "diabetic kidney disease",
    "kidney disease",
    "renal insufficiency",
    "kidney failure",
]


async def main(radius_mi: float) -> ctgov.SeedStats:
    init_db()
    async with ctgov.make_client() as client:
        return await ctgov.seed_cache(CONDITIONS, client=client, radius_mi=radius_mi)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--radius",
        type=float,
        default=get_settings().ctgov_seed_radius_mi,
        help="miles around Sacramento (default: CTGOV_SEED_RADIUS_MI)",
    )
    args = parser.parse_args()
    stats = asyncio.run(main(args.radius))
    print(
        f"seed: {stats.seen} studies seen across {len(CONDITIONS)} conditions within "
        f"{args.radius:g} mi, {stats.new} new versions cached, {stats.cached_total} trials in cache"
    )
