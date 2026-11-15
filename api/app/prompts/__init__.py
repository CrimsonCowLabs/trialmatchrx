"""Prompt files: `app/prompts/<name>.md`, each with a `version:` header.

    ---
    version: compile-criteria-v1
    ---
    ## system
    ... {{placeholder}} ...
    ## user
    ...
    ## retry          (optional: the follow-up turn after a malformed answer)
    ...

`load_prompt(name)` parses the file; `Prompt.render_system(...)` / `render_user(...)` fill the
`{{placeholders}}`. Prompts are never written inline in code.
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent

_FRONT_MATTER = re.compile(r"\A---\n(?P<header>.*?)\n---\n(?P<body>.*)\Z", re.S)
_SECTION = re.compile(r"^## (system|user|retry)\s*$", re.M)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class PromptError(ValueError):
    pass


def _render(template: str, values: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        if m.group(1) not in values:
            raise PromptError(f"no value for {{{{{m.group(1)}}}}}")
        return values[m.group(1)]

    return _PLACEHOLDER.sub(sub, template)


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system: str
    user: str
    retry: str | None = None  # optional `## retry`: the follow-up turn after a malformed answer

    def render_system(self, **values: str) -> str:
        return _render(self.system, values)

    def render_user(self, **values: str) -> str:
        return _render(self.user, values)

    def render_retry(self, **values: str) -> str:
        if self.retry is None:
            raise PromptError(f"{self.name}: no `## retry` section")
        return _render(self.retry, values)


@cache
def load_prompt(name: str) -> Prompt:
    path = PROMPTS_DIR / f"{name}.md"
    m = _FRONT_MATTER.match(path.read_text())
    if m is None:
        raise PromptError(f"{path.name}: missing `---` front matter")
    header = dict(line.split(":", 1) for line in m.group("header").splitlines() if ":" in line)
    version = header.get("version", "").strip()
    if not version:
        raise PromptError(f"{path.name}: missing `version:` header")
    parts = _SECTION.split(m.group("body"))
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    if not {"system", "user"} <= set(sections):
        raise PromptError(f"{path.name}: needs `## system` and `## user` sections")
    return Prompt(name, version, sections["system"], sections["user"], sections.get("retry"))
