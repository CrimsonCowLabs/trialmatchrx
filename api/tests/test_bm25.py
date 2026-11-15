"""BM25 keyword baseline: ranks a topic's judged trials by their text."""

from app.eval.bm25 import Bm25Index, tokenize, trial_text


def test_tokenize_lowercases_splits_on_punctuation_and_drops_stopwords() -> None:
    assert tokenize("The patient has Type-2 DIABETES, eGFR 48.") == [
        "patient",
        "type",
        "2",
        "diabetes",
        "egfr",
        "48",
    ]


def test_trial_with_the_query_terms_ranks_first() -> None:
    index = Bm25Index(
        {
            "NCT1": "breast cancer chemotherapy",
            "NCT2": "type 2 diabetes metformin",
            "NCT3": "asthma inhaler children",
        }
    )

    assert index.rank("woman with type 2 diabetes on metformin", ["NCT1", "NCT2", "NCT3"])[0] == (
        "NCT2"
    )


def test_a_rare_term_outweighs_a_common_one() -> None:
    index = Bm25Index(
        {
            "NCT1": "diabetes diabetes kidney",
            "NCT2": "diabetes semaglutide",
            "NCT3": "diabetes insulin",
            "NCT4": "diabetes diet",
            "NCT5": "diabetes exercise",
            "NCT6": "asthma",
        }
    )

    ranked = index.rank("diabetes semaglutide", ["NCT1", "NCT2"])

    assert ranked == ["NCT2", "NCT1"]


def test_rank_returns_only_the_candidates_with_ties_in_nct_order() -> None:
    index = Bm25Index(
        {"NCT3": "asthma", "NCT1": "asthma", "NCT2": "copd", "NCT8": "gout", "NCT9": "acne"}
    )

    assert index.rank("asthma", ["NCT3", "NCT2", "NCT1"]) == ["NCT1", "NCT3", "NCT2"]


def test_trial_text_joins_titles_conditions_summary_and_criteria() -> None:
    study = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT1",
                "briefTitle": "Brief",
                "officialTitle": "Official",
            },
            "conditionsModule": {"conditions": ["CKD"], "keywords": ["eGFR"]},
            "descriptionModule": {"briefSummary": "Summary."},
            "eligibilityModule": {"eligibilityCriteria": "Inclusion: adults"},
        }
    }

    assert trial_text(study) == "Brief\nOfficial\nCKD\neGFR\nSummary.\nInclusion: adults"
