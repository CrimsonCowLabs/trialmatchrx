"""The `make eval-offline` / `make eval-smoke` shortcuts expand to `run_eval` with their flags
and pass extra ARGS through (issue #62). `make -n` only prints the recipe, so nothing runs."""

import subprocess

import pytest

from app.config import REPO_DIR


def _dry_run(*args: str) -> str:
    out = subprocess.run(
        ["make", "-n", "-C", str(REPO_DIR), *args], capture_output=True, text=True, check=True
    )
    return out.stdout


@pytest.mark.parametrize(
    ("target", "flags"),
    [("eval-offline", "--offline"), ("eval-smoke", "--topics 1 --fail-fast")],
)
def test_eval_shortcut_runs_run_eval_with_its_flags_and_passes_args_through(
    target: str, flags: str
) -> None:
    command = f"uv run python -m scripts.run_eval {flags}"
    assert command in _dry_run(target)
    assert f"{command} --rebuild" in _dry_run(target, "ARGS=--rebuild")
