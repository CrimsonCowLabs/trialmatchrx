"""A fake ClinicalTrials.gov serving the recorded fixtures in tests/fixtures/ctgov/."""

import json
from pathlib import Path
from typing import Any

import httpx

from app.sources import ctgov

FIXTURES = Path(__file__).parent / "fixtures" / "ctgov"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return data


def nct_ids(studies: list[dict[str, Any]]) -> list[str]:
    return [ctgov.study_key(s)[0] for s in studies]


class FakeCtgov:
    """Serves the recorded fixtures and records every request it sees."""

    def __init__(
        self,
        studies: dict[str, dict[str, Any]] | None = None,
        moved: dict[str, str] | None = None,
    ) -> None:
        self.requests: list[httpx.Request] = []
        self.studies = studies or {}  # extra studies served by NCT ID, beside study.json
        self.moved = moved or {}  # NCT ID -> the record it was merged into (a 301)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/v2/studies":
            page = 2 if request.url.params.get("pageToken") else 1
            return httpx.Response(200, json=load(f"search_page{page}.json"))
        study = load("study.json")
        if path == f"/api/v2/studies/{nct_ids([study])[0]}":
            return httpx.Response(200, json=study)
        nct = path.removeprefix("/api/v2/studies/")
        if nct in self.studies:
            return httpx.Response(200, json=self.studies[nct])
        if nct in self.moved:
            return httpx.Response(301, headers={"Location": f"/api/v2/studies/{self.moved[nct]}"})
        return httpx.Response(404, json={"error": "not found"})

    def install(self) -> None:
        """Make every `ctgov.make_client()` talk to this fake."""
        ctgov.set_transport(httpx.MockTransport(self))

    def client(self) -> httpx.AsyncClient:
        self.install()
        return ctgov.make_client()
