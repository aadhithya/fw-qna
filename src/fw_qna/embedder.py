"""EmbeddingGemma 2 through Ollama, as a LlamaIndex embedding model.

Ollama does not add the model's task prefixes, so we do. Queries get the search prefix here. Documents get
``title: ... | text: ...`` when ingestion builds a node's embed text, so the text that arrives here is
already formatted.

The model gives 768 numbers. Its Matryoshka training lets us keep the first ``dimensions`` of them
(512 by default) if we normalise to unit length afterwards. Queries and documents must use the same dimension.
"""

import math
from typing import Any

import httpx
from llama_index.core.base.embeddings.base import BaseEmbedding

QUERY_PREFIX = "task: search result | query: "
NATIVE_DIMENSIONS = 768
MATRYOSHKA_DIMENSIONS = (128, 256, 512, 768)  # the sizes the model was trained for


class EmbeddingError(RuntimeError):
    """Ollama is unreachable, or it returned a vector we cannot trust."""


def shrink(vector: list[float], dimensions: int) -> list[float]:
    """Keep the first ``dimensions`` numbers and scale the result to unit length."""
    if len(vector) < dimensions:
        raise EmbeddingError(f"expected at least {dimensions} numbers, got {len(vector)}")
    if any(math.isnan(x) or math.isinf(x) for x in vector):
        # The model gives NaN, not an error, when it runs in float16.
        raise EmbeddingError("the vector has NaN or infinite values")
    kept = vector[:dimensions]
    norm = math.sqrt(sum(x * x for x in kept))
    if norm == 0:
        raise EmbeddingError("the vector is all zeros")
    return [x / norm for x in kept]


class OllamaGemmaEmbedding(BaseEmbedding):
    base_url: str = "http://localhost:11434"
    model_name: str = "embeddinggemma-2:270m"
    dimensions: int = 512
    timeout: float = 120.0
    transport: Any = None  # an httpx transport, so tests can fake Ollama

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if self.dimensions not in MATRYOSHKA_DIMENSIONS:
            raise ValueError(f"dimensions must be one of {MATRYOSHKA_DIMENSIONS}, not {self.dimensions}")

    @classmethod
    def class_name(cls) -> str:
        return "OllamaGemmaEmbedding"

    def _parse(self, response: httpx.Response, expected: int) -> list[list[float]]:
        if response.status_code != 200:
            raise EmbeddingError(f"Ollama answered {response.status_code}: {response.text[:200]}")
        vectors = response.json().get("embeddings", [])
        if len(vectors) != expected:
            raise EmbeddingError(f"asked for {expected} embeddings, got {len(vectors)}")
        return [shrink(v, self.dimensions) for v in vectors]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout, transport=self.transport) as client:
                response = client.post("/api/embed", json={"model": self.model_name, "input": texts})
        except httpx.HTTPError as error:
            raise EmbeddingError(f"cannot reach Ollama at {self.base_url}: {error}") from error
        return self._parse(response, len(texts))

    async def _aembed(self, texts: list[str]) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout, transport=self.transport
            ) as client:
                response = await client.post("/api/embed", json={"model": self.model_name, "input": texts})
        except httpx.HTTPError as error:
            raise EmbeddingError(f"cannot reach Ollama at {self.base_url}: {error}") from error
        return self._parse(response, len(texts))

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed([QUERY_PREFIX + query])[0]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return (await self._aembed([QUERY_PREFIX + query]))[0]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed([text])[0]

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return (await self._aembed([text]))[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return await self._aembed(texts)
