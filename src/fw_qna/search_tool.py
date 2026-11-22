"""The ``search_docs`` tool the chat agent calls (a LangChain tool, as featherweight agents use).

Each result gets a reference number, ``[n]``, that is the same for the whole conversation: a chunk found twice
keeps its number. The model cites with those numbers, and the interface turns them into links. The titles and
links come from here, not from the model, so a citation cannot be made up.
"""

import json
from dataclasses import dataclass
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from .retrieval import Hit, Retriever, SearchError

DESCRIPTION = """Search the featherweight documentation. Use it for EVERY question about featherweight: how \
something works, what an API is called, how to build something, what changed in a release. Never answer such \
a question from memory.

Write `query` as a plain question or topic. Put exact code names (class, function, parameter or file names, \
like JobWorker or check_output) in `keywords`: they are matched exactly, which finds them better than a \
sentence does. If the results are thin, search again with other words.

`layer` narrows the search: book (tutorial, in order), guide (how to do X), spec (what exactly it does and \
why), example (whole runnable examples, with code), changelog (what changed in each release). Leave it empty \
to search everything. `version` is a release like v0.1.0; leave it empty for the latest indexed release, and \
use it only when the user asks about another one.

Each result has a reference number. Cite it as [n] after every claim, paragraph or code block that relies \
on it."""


class SearchArgs(BaseModel):
    query: str = Field(description="What to look for, as a plain question or topic.")
    keywords: list[str] | None = Field(
        default=None, description="Exact code names or terms to match, like ['JobWorker', 'check_output']."
    )
    layer: Literal["book", "guide", "spec", "example", "changelog"] | None = Field(
        default=None, description="Search only one layer of the docs."
    )
    version: str | None = Field(
        default=None, description="A release like v0.1.0. Empty means the latest indexed release."
    )
    top_k: int = Field(default=5, ge=1, le=10, description="How many results to return.")


@dataclass(frozen=True)
class Citation:
    """What the interface needs to show a source."""

    ref: int
    chunk_id: str
    breadcrumb: str
    layer: str
    version: str
    path: str
    url: str


class DocSearch:
    """One conversation's search: the tool, and the sources it has returned so far."""

    def __init__(self, retriever: Retriever) -> None:
        self.retriever = retriever
        self.version: str | None = None  # the release this conversation is about; None means the latest
        self.citations: dict[int, Citation] = {}  # by reference number, in the order they were found
        self._ref_of: dict[str, int] = {}  # chunk id -> its number

    def reset(self) -> None:
        """Forget the sources found so far, when the conversation starts again."""
        self.citations.clear()
        self._ref_of.clear()

    def _ref(self, hit: Hit) -> int:
        if hit.id not in self._ref_of:
            ref = len(self._ref_of) + 1
            self._ref_of[hit.id] = ref
            self.citations[ref] = Citation(ref, hit.id, hit.breadcrumb, hit.layer, hit.version, hit.path, hit.url)
        return self._ref_of[hit.id]

    async def search(
        self,
        query: str,
        keywords: list[str] | None = None,
        layer: str | None = None,
        version: str | None = None,
        top_k: int = 5,
    ) -> str:
        """The tool's result: JSON text, which the model reads and the interface parses."""
        try:
            hits = await self.retriever.asearch(
                query, keywords=keywords, layer=layer, version=version or self.version, top_k=top_k
            )
        except SearchError as error:
            return json.dumps({"error": str(error)})
        if not hits:
            return json.dumps({"results": [], "note": "Nothing matched. Try other words, other keywords, or no layer."})
        results = [
            {
                "ref": self._ref(hit),
                "title": hit.breadcrumb,
                "layer": hit.layer,
                "version": hit.version,
                "url": hit.url,
                "code_files": hit.code_paths,
                "text": hit.text,
            }
            for hit in hits
        ]
        return json.dumps({"version": hits[0].version, "results": results}, ensure_ascii=False)

    def tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            coroutine=self.search, name="search_docs", description=DESCRIPTION, args_schema=SearchArgs
        )
