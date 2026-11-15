"""BM25 keyword baseline over trial text (SPEC.md "7. Eval harness": `rank_bm25`).

    index = Bm25Index({nct: trial_text(study) for nct, study in sample.trials.items()})
    ranked = index.rank(topic.text, candidate_ncts)       # best first

The index covers every trial in the sample, so IDF comes from the whole pool; `rank` scores
only the candidates it is given (one topic's judged trials). Okapi BM25, k1=1.5, b=0.75.
rank_bm25 floors the IDF of a term found in over half the documents to a small positive value,
so near-universal words ("patients", "study") add almost nothing.
"""

import re
from typing import Any

from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

_TOKEN = re.compile(r"[a-z0-9]+")
# Function words only; clinical words ("no", "history") are left for IDF to weigh.
STOPWORDS = frozenset(
    "a an and are as at be by for from had has have he her his in is it its of on or she "
    "that the their this to was were which who with".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


def trial_text(study: dict[str, Any]) -> str:
    """The text BM25 indexes: titles, conditions, keywords, brief summary, criteria."""
    proto = study["protocolSection"]
    ident = proto.get("identificationModule", {})
    conditions = proto.get("conditionsModule", {})
    parts = [
        ident.get("briefTitle"),
        ident.get("officialTitle"),
        *conditions.get("conditions", []),
        *conditions.get("keywords", []),
        proto.get("descriptionModule", {}).get("briefSummary"),
        proto.get("eligibilityModule", {}).get("eligibilityCriteria"),
    ]
    return "\n".join(p for p in parts if p)


class Bm25Index:
    def __init__(self, docs: dict[str, str]) -> None:
        self._ncts = sorted(docs)
        self._row = {nct: i for i, nct in enumerate(self._ncts)}
        self._bm25 = BM25Okapi([tokenize(docs[nct]) for nct in self._ncts])

    def rank(self, query: str, candidates: list[str]) -> list[str]:
        """`candidates` best first; equal scores fall back to NCT ID order."""
        scores = self._bm25.get_scores(tokenize(query))
        return sorted(candidates, key=lambda nct: (-float(scores[self._row[nct]]), nct))
