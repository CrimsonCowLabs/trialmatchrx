"""Prompt files load with their version and fill placeholders."""

import pytest

from app.prompts import PromptError, load_prompt


def test_compile_prompt_has_a_version_and_both_sections() -> None:
    prompt = load_prompt("compile_criteria")

    assert prompt.version == "compile-criteria-v2"
    system = prompt.render_system(vocabulary="- `labs.egfr`")
    assert "- `labs.egfr`" in system
    assert "{{" not in system
    user = prompt.render_user(nct_id="NCT1", eligibility_text="* T2DM")
    assert "NCT1" in user and "* T2DM" in user


def test_judge_prompt_has_a_version_and_fills_every_placeholder() -> None:
    prompt = load_prompt("judge")

    assert prompt.version == "judge-v2"
    assert "{{" not in prompt.render_system()
    user = prompt.render_user(
        nct_id="NCT1",
        trial_text="* T2DM",
        criterion_type="inclusion",
        criterion_id="inc-1",
        criterion_text="T2DM",
        patient_facts="age: 61",
        patient_note="61M",
    )
    assert "{{" not in user and "age: 61" in user and "61M" in user
    retry = prompt.render_retry(error="no tool call")
    assert "{{" not in retry and "no tool call" in retry


def test_retry_section_is_optional() -> None:
    with pytest.raises(PromptError, match="retry"):
        load_prompt("compile_criteria").render_retry(error="x")


def test_parse_patient_prompt_has_a_version_and_fills_the_note() -> None:
    prompt = load_prompt("parse_patient")

    assert prompt.version == "parse-patient-v3"
    assert "{{" not in prompt.render_system(units="- labs: `egfr`")
    assert "61M, T2D" in prompt.render_user(note="61M, T2D")


def test_missing_placeholder_value_is_an_error() -> None:
    with pytest.raises(PromptError, match="vocabulary"):
        load_prompt("compile_criteria").render_system()
