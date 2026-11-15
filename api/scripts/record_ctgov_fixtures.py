"""Record a few real ClinicalTrials.gov responses into tests/fixtures/ctgov/ (hits the network).

    cd api && uv run python -m scripts.record_ctgov_fixtures

Writes two pages of a small search (pageSize=3, so pagination is exercised) and one study by
NCT, each trimmed to its first few sites. Re-run only when the API's response shape changes;
tests never touch the network.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from app.sources import ctgov

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ctgov"
CONDITION = "chronic kidney disease"
MAX_LOCATIONS = 5


def _trim(study: dict[str, Any]) -> dict[str, Any]:
    """Keep the first few sites; big multi-site trials list hundreds and bloat the repo."""
    cl = study.get("protocolSection", {}).get("contactsLocationsModule", {})
    if "locations" in cl:
        cl["locations"] = cl["locations"][:MAX_LOCATIONS]
    return study


def _write(name: str, data: dict[str, Any]) -> None:
    for study in data.get("studies", [data]):
        _trim(study)
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT / name}")


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    async with ctgov.make_client() as client:
        params = ctgov.search_params(CONDITION, radius_mi=50, page_size=3)
        page1 = (await client.get("/studies", params=params)).raise_for_status().json()
        _write("search_page1.json", page1)
        page2 = (
            (await client.get("/studies", params={**params, "pageToken": page1["nextPageToken"]}))
            .raise_for_status()
            .json()
        )
        page2.pop("nextPageToken", None)  # end the fixture's pagination after two pages
        _write("search_page2.json", page2)
        nct = page1["studies"][0]["protocolSection"]["identificationModule"]["nctId"]
        study = await client.get(f"/studies/{nct}", params={"fields": ctgov.FIELDS})
        _write("study.json", study.raise_for_status().json())


if __name__ == "__main__":
    asyncio.run(main())
