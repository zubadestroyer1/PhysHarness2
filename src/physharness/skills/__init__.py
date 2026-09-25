"""Curated technique notes that agents may load: optional guidance, not a method.

Each packaged `<name>.md` note starts with a `---` front matter block holding exactly
`name:`, `summary:` and `applies_when:` lines, followed by a body of at most 80 lines.
"""

from __future__ import annotations

from functools import cache
from importlib import resources

from ..errors import HarnessError

FRONT_MATTER = ("name", "summary", "applies_when")
MAX_BODY_LINES = 80
MAX_SKILL_CHARS = 6_000


def _parse(filename: str, text: str) -> dict[str, str]:
    lines = text.splitlines()
    if len(lines) < 5 or lines[0] != "---" or lines[4] != "---":
        raise ValueError(f"skill {filename} has malformed front matter")
    meta = {}
    for key, line in zip(FRONT_MATTER, lines[1:4], strict=True):
        prefix = key + ":"
        if not line.startswith(prefix) or not line[len(prefix) :].strip():
            raise ValueError(f"skill {filename} lacks {key}")
        meta[key] = line[len(prefix) :].strip()
    body = "\n".join(lines[5:]).strip("\n")
    if (
        meta["name"] + ".md" != filename
        or len(body.splitlines()) > MAX_BODY_LINES
        or len(text) > MAX_SKILL_CHARS
    ):
        raise ValueError(f"skill {filename} exceeds its bounds")
    return {**meta, "text": text.strip("\n")}


@cache
def _catalog() -> dict[str, dict[str, str]]:
    notes = {}
    for item in resources.files(__name__).iterdir():
        if item.name.endswith(".md"):
            note = _parse(item.name, item.read_text(encoding="utf-8"))
            notes[note["name"]] = note
    return dict(sorted(notes.items()))


def list_skills() -> list[dict]:
    """Name, summary and applicability of every packaged note, sorted by name."""
    return [{key: note[key] for key in FRONT_MATTER} for note in _catalog().values()]


def load_skill(name: str) -> dict:
    """Return one note's full text; only packaged names resolve, never paths."""
    note = _catalog().get(name) if isinstance(name, str) else None
    if note is None:
        raise HarnessError(
            "SKILL_NOT_FOUND",
            "No technique note has that name.",
            status=404,
            remediation="Use one of the skill names listed in the constitution.",
        )
    return {"name": note["name"], "text": note["text"]}
