"""Email templates: `app/emails/<name>.md`, each with a `version:` header (SPEC.md "Admin").

    ---
    version: invite-v1
    ---
    ## subject
    ... {{placeholder}} ...
    ## text
    ...
    ## html
    ...

The same shape as `app/prompts/*.md`, loaded on its own because these aren't LLM prompts.
`render(name, **values)` returns `(subject, text, html)`. Every value is treated as
user-supplied: in the HTML body it is escaped and its line breaks become `<br>`; in the
subject its whitespace collapses to single spaces. An empty value (an invite without a note)
leaves no run of blank lines, and no empty `<p></p>`, behind.

The sender is `app.emails.sender`.
"""

import html
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

EMAILS_DIR = Path(__file__).resolve().parent

_FRONT_MATTER = re.compile(r"\A---\n(?P<header>.*?)\n---\n(?P<body>.*)\Z", re.S)
_SECTION = re.compile(r"^## (subject|text|html)\s*$", re.M)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_BLANK_RUN = re.compile(r"\n{3,}")
_EMPTY_PARAGRAPH = re.compile(r"^<p>\s*</p>\n?", re.M)


class EmailTemplateError(ValueError):
    pass


@dataclass(frozen=True)
class EmailTemplate:
    name: str
    version: str
    subject: str
    text: str
    html: str

    def placeholders(self) -> set[str]:
        return {
            m.group(1)
            for part in (self.subject, self.text, self.html)
            for m in _PLACEHOLDER.finditer(part)
        }


def _fill(template: str, values: dict[str, str], name: str) -> str:
    def sub(m: re.Match[str]) -> str:
        if m.group(1) not in values:
            raise EmailTemplateError(f"{name}: no value for {{{{{m.group(1)}}}}}")
        return values[m.group(1)]

    return _BLANK_RUN.sub("\n\n", _PLACEHOLDER.sub(sub, template)).strip()


@cache
def load_template(name: str) -> EmailTemplate:
    path = EMAILS_DIR / f"{name}.md"
    m = _FRONT_MATTER.match(path.read_text())
    if m is None:
        raise EmailTemplateError(f"{path.name}: missing `---` front matter")
    header = dict(line.split(":", 1) for line in m.group("header").splitlines() if ":" in line)
    version = header.get("version", "").strip()
    if not version:
        raise EmailTemplateError(f"{path.name}: missing `version:` header")
    parts = _SECTION.split(m.group("body"))
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    if set(sections) != {"subject", "text", "html"}:
        raise EmailTemplateError(f"{path.name}: needs `## subject`, `## text` and `## html`")
    return EmailTemplate(name, version, sections["subject"], sections["text"], sections["html"])


def render(name: str, /, **values: object) -> tuple[str, str, str]:
    """Fill template `name`, returning `(subject, text, html)`. `None` renders as empty; a
    placeholder with no value raises `EmailTemplateError`."""
    t = load_template(name)
    plain = {k: "" if v is None else str(v) for k, v in values.items()}
    subject = _fill(t.subject, {k: " ".join(v.split()) for k, v in plain.items()}, name)
    text = _fill(t.text, plain, name)
    escaped = {k: html.escape(v).replace("\n", "<br>\n") for k, v in plain.items()}
    body = _EMPTY_PARAGRAPH.sub("", _fill(t.html, escaped, name))
    return subject, text, body
