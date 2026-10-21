"""Checks on the written deliverables that are easy to break without noticing."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
NOTE = ROOT / "docs" / "technical-note.md"
WORD_LIMIT = 500


def test_the_technical_note_stays_within_the_word_limit() -> None:
    text = NOTE.read_text(encoding="utf-8")
    prose = re.sub(r"[#*`|>_-]+", " ", text)
    words = [w for w in prose.split() if any(c.isalnum() for c in w)]
    assert len(words) <= WORD_LIMIT, f"{len(words)} words"


def test_relative_links_in_the_docs_point_at_files_that_exist() -> None:
    for page in [
        ROOT / "README.md",
        *(ROOT / "docs").rglob("*.md"),
        ROOT / "datasets" / "README.md",
    ]:
        for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", page.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("mailto:"):
                continue
            assert (page.parent / target).exists(), f"{page.name} links to missing {target}"
