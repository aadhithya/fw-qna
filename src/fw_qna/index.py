"""The index: LanceDB on disk. One table holds the chunks of every release, a small one says what is in it.

Each chunk has a vector and a full-text field, so a search can combine both. Every row carries its release,
so a search filters on it, and ``drop`` removes one release without touching the others.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import lancedb
import pyarrow as pa
from lancedb.index import FTS
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.schema import MetadataMode, TextNode

from .ingest.source import check_tag

CHUNKS = "chunks"
RELEASES = "releases"
BATCH = 32


class IndexError_(RuntimeError):  # noqa: N818
    """The index on disk does not fit what we were asked to do."""


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    chunks: int
    ingested_at: str
    model: str
    dimensions: int


def version_key(version: str) -> tuple[int, ...]:
    """Sort v0.10.0 after v0.9.0."""
    return tuple(int(n) for n in re.findall(r"\d+", version))


def chunk_schema(dimensions: int) -> pa.Schema:
    return pa.schema(
        [
            ("id", pa.string()),
            ("version", pa.string()),
            ("layer", pa.string()),
            ("title", pa.string()),
            ("breadcrumb", pa.string()),
            ("path", pa.string()),
            ("url", pa.string()),
            ("code_paths", pa.list_(pa.string())),
            ("release", pa.string()),  # for the changelog: the release an entry describes
            ("prev_id", pa.string()),
            ("next_id", pa.string()),
            ("text", pa.string()),
            ("search_text", pa.string()),  # what the keyword search reads: the breadcrumb and the text
            ("vector", pa.list_(pa.float32(), dimensions)),
        ]
    )


RELEASE_SCHEMA = pa.schema(
    [
        ("version", pa.string()),
        ("content_hash", pa.string()),
        ("chunks", pa.int32()),
        ("ingested_at", pa.string()),
        ("model", pa.string()),
        ("dimensions", pa.int32()),
    ]
)


def content_hash(nodes: list[TextNode], model: str, dimensions: int) -> str:
    """Changes when the text, the ids, the embedding model or its size change."""
    digest = hashlib.sha256(f"{model}|{dimensions}".encode())
    for node in sorted(nodes, key=lambda n: n.node_id):
        digest.update(f"{node.node_id}|{node.get_content(MetadataMode.EMBED)}".encode())
    return digest.hexdigest()


class Index:
    def __init__(self, path: Path, embed_model: BaseEmbedding) -> None:
        self.embed_model = embed_model
        self.dimensions: int = embed_model.dimensions  # type: ignore[attr-defined]
        self.model: str = embed_model.model_name
        path.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(path))
        self.chunks = self._open(CHUNKS, chunk_schema(self.dimensions))
        self.releases_table = self._open(RELEASES, RELEASE_SCHEMA)

    def _open(self, name: str, schema: pa.Schema):
        if name in self.db.list_tables().tables:
            table = self.db.open_table(name)
            if table.schema != schema:
                raise IndexError_(
                    f"The index was built with a different vector size or layout ({name}). "
                    "Drop its releases and ingest them again, or use another data directory."
                )
            return table
        return self.db.create_table(name, schema=schema)

    def releases(self) -> list[ReleaseInfo]:
        rows = self.releases_table.to_arrow().to_pylist()
        fields = ("version", "chunks", "ingested_at", "model", "dimensions")
        infos = [ReleaseInfo(*(r[f] for f in fields)) for r in rows]
        return sorted(infos, key=lambda i: version_key(i.version))

    def latest(self) -> str | None:
        releases = self.releases()
        return releases[-1].version if releases else None

    def _stored_hash(self, version: str) -> str | None:
        check_tag(version)  # the version goes into a filter expression, so it must be a plain tag
        rows = self.releases_table.search().where(f"version = '{version}'").limit(1).to_list()
        return rows[0]["content_hash"] if rows else None

    def add_release(self, version: str, nodes: list[TextNode], *, force: bool = False) -> str:
        """Embed and store a release, replacing it if it is there. Return ``added`` or ``unchanged``."""
        new_hash = content_hash(nodes, self.model, self.dimensions)
        if not force and self._stored_hash(version) == new_hash:
            return "unchanged"
        texts = [node.get_content(MetadataMode.EMBED) for node in nodes]
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            vectors += self.embed_model.get_text_embedding_batch(texts[start : start + BATCH])
        rows = [self._row(node, vector) for node, vector in zip(nodes, vectors, strict=True)]
        self._remove(version)
        self.chunks.add(rows)
        self.chunks.create_index("search_text", config=FTS(), replace=True)
        self.releases_table.add(
            [
                {
                    "version": version,
                    "content_hash": new_hash,
                    "chunks": len(nodes),
                    "ingested_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "model": self.model,
                    "dimensions": self.dimensions,
                }
            ]
        )
        return "added"

    def drop(self, version: str) -> bool:
        """Remove one release. Return whether it was there."""
        was_there = self._stored_hash(version) is not None
        self._remove(version)
        return was_there

    def _remove(self, version: str) -> None:
        check_tag(version)
        self.chunks.delete(f"version = '{version}'")
        self.releases_table.delete(f"version = '{version}'")

    @staticmethod
    def _row(node: TextNode, vector: list[float]) -> dict:
        meta = node.metadata
        return {
            "id": node.node_id,
            "version": meta["version"],
            "layer": meta["layer"],
            "title": meta["title"],
            "breadcrumb": meta["breadcrumb"],
            "path": meta["path"],
            "url": meta["url"],
            "code_paths": list(meta.get("code_paths", [])),
            "release": meta.get("release", ""),
            "prev_id": meta.get("prev_id", ""),
            "next_id": meta.get("next_id", ""),
            "text": node.text,
            "search_text": f"{meta['breadcrumb']}\n{node.text}",
            "vector": vector,
        }
