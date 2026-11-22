"""Ingestion: a release tag in, chunks out."""

import tempfile
from pathlib import Path

from llama_index.core.schema import TextNode

from .chunk import changelog_pieces, example_pieces, page_pieces, to_nodes
from .source import SourceError, check_tag, export_release

__all__ = ["SourceError", "build_nodes", "ingest_release"]


def build_nodes(root: Path, tag: str, repo_url: str) -> list[TextNode]:
    """The chunks of an exported release, in reading order."""
    pieces = [*page_pieces(root), *changelog_pieces(root), *example_pieces(root)]
    return to_nodes(pieces, tag, repo_url)


def ingest_release(source: str, tag: str, repo_url: str | None = None) -> list[TextNode]:
    """Export one release tag from a local clone or a git URL and chunk it."""
    check_tag(tag)
    with tempfile.TemporaryDirectory() as work:
        exported = Path(work) / "release"
        found_url = export_release(source, tag, exported)
        return build_nodes(exported, tag, repo_url or found_url)
