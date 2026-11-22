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


def ingest_release(source: str, tag: str, repo_url: str | None = None, data_dir: Path | None = None) -> list[TextNode]:
    """Export one release tag from a local clone or a git URL and chunk it.

    With ``data_dir``, the release's skills are installed there too (see ``fw_qna.skills``).
    """
    from ..skills import install_skills  # here, because skills imports from this package

    check_tag(tag)
    with tempfile.TemporaryDirectory() as work:
        exported = Path(work) / "release"
        found_url = export_release(source, tag, exported)
        url = repo_url or found_url
        if data_dir is not None:
            install_skills(exported, data_dir, tag, url)
        return build_nodes(exported, tag, url)
