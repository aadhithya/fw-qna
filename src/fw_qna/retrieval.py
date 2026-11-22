"""Hybrid search over the index: keywords (BM25) and meaning (vectors), merged with reciprocal rank fusion.

A search always looks at one release. When none is named it uses the latest one that is indexed.
"""

import asyncio
import re
from dataclasses import dataclass

from lancedb.rerankers import RRFReranker

from .index import Index
from .ingest.source import check_tag

LAYERS = ("book", "guide", "spec", "example", "changelog")
MAX_EXAMPLES = 2  # an example is a whole directory, 6 to 9 KB, so a search returns only a couple
WORDS = re.compile(r"\w+")


class SearchError(ValueError):
    """The search cannot run. The message says why, in words the model can act on."""


@dataclass(frozen=True)
class Hit:
    id: str
    version: str
    layer: str
    title: str
    breadcrumb: str
    path: str
    url: str
    code_paths: list[str]
    release: str
    text: str
    score: float


def keyword_query(text: str) -> str:
    """The words of a query, without the characters that the keyword search treats as syntax."""
    return " ".join(WORDS.findall(text))


class Retriever:
    def __init__(self, index: Index) -> None:
        self.index = index

    def resolve_version(self, version: str | None) -> str:
        available = [r.version for r in self.index.releases()]
        if not available:
            raise SearchError("Nothing is indexed yet. Ingest a featherweight release first.")
        if version is None:
            return available[-1]
        check_tag(version)
        if version not in available:
            raise SearchError(f"{version} is not indexed. Indexed releases: {', '.join(available)}.")
        return version

    def search(
        self,
        query: str,
        *,
        keywords: list[str] | None = None,
        layer: str | None = None,
        version: str | None = None,
        top_k: int = 5,
        vector: list[float] | None = None,
    ) -> list[Hit]:
        """The best chunks for a question. ``vector`` is the embedded query (see ``asearch``)."""
        if layer is not None and layer not in LAYERS:
            raise SearchError(f"layer must be one of {', '.join(LAYERS)}.")
        version = self.resolve_version(version)
        if vector is None:
            vector = self.index.embed_model.get_query_embedding(query)
        words = keyword_query(" ".join(keywords) if keywords else query)
        where = f"version = '{version}'" + (f" AND layer = '{layer}'" if layer else "")
        # ask for more than top_k, so that capping the examples still leaves enough to return
        wanted = max(top_k * 3, 15)
        if words:
            search = self.index.chunks.search(query_type="hybrid").vector(vector).text(words)
            rows = search.where(where, prefilter=True).rerank(RRFReranker()).limit(wanted).to_list()
        else:  # nothing but punctuation: meaning is all we have
            rows = self.index.chunks.search(vector).where(where, prefilter=True).limit(wanted).to_list()
        return self._pick(rows, top_k, cap_examples=layer is None)

    async def asearch(self, query: str, **options) -> list[Hit]:
        """``search``, without blocking: the query is embedded and the index is read off the event loop."""
        vector = await self.index.embed_model.aget_query_embedding(query)
        return await asyncio.to_thread(self.search, query, vector=vector, **options)

    @staticmethod
    def _pick(rows: list[dict], top_k: int, *, cap_examples: bool) -> list[Hit]:
        hits: list[Hit] = []
        examples = 0
        for row in rows:
            if cap_examples and row["layer"] == "example":
                if examples >= MAX_EXAMPLES:
                    continue
                examples += 1
            score = row.get("_relevance_score")
            if score is None:
                score = -row.get("_distance", 0.0)
            hits.append(
                Hit(
                    id=row["id"],
                    version=row["version"],
                    layer=row["layer"],
                    title=row["title"],
                    breadcrumb=row["breadcrumb"],
                    path=row["path"],
                    url=row["url"],
                    code_paths=list(row["code_paths"]),
                    release=row["release"],
                    text=row["text"],
                    score=float(score),
                )
            )
            if len(hits) == top_k:
                break
        return hits
