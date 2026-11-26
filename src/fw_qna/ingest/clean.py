"""Remove what is noise for search, and read what is worth keeping, before a page is split."""

import re

NAV = re.compile(r"<!-- nav:(top|bottom) -->.*?<!-- /nav:\1 -->\n?", re.S)
# comments that mark a table of contents, or text the skill build leaves out; the text between them stays
MARKERS = re.compile(r"^[ \t]*<!-- /?(?:toc|skill(?::[\w-]+)?) -->[ \t]*\n?", re.M)
BADGE = re.compile(r"^\s*\[!\[docs for\]\([^\n]*\n?", re.M)
CODE_MARKER = re.compile(r"<!-- code: (\S+) -->\n?")  # the book says which code file a chapter shows
COMMIT_LINK = re.compile(r" \(\[[0-9a-f]{7}\]\([^)]*\)\)(, closes \[#\d+\]\([^)]*\))?")


def clean_page(text: str) -> str:
    """Strip the navigation blocks, the version badge and the build's comment markers."""
    return MARKERS.sub("", BADGE.sub("", NAV.sub("", text)))


def clean_changelog(text: str) -> str:
    """Drop the commit hashes and links that release-please adds to every line."""
    return re.sub(r"\n{3,}", "\n\n", COMMIT_LINK.sub("", text))


def github_anchor(heading: str) -> str:
    """The id GitHub gives a heading, for links to a section."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")
