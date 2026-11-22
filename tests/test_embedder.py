import json
import math

import httpx
import pytest

from fw_qna.embedder import QUERY_PREFIX, EmbeddingError, OllamaGemmaEmbedding, shrink


def fake_ollama(calls, vector=None, status=200):
    """An httpx transport that stands in for Ollama and records what it was sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        vectors = [vector or [float(i + 1) for i in range(768)] for _ in body["input"]]
        return httpx.Response(status, json={"embeddings": vectors})

    return httpx.MockTransport(handler)


def norm(v):
    return math.sqrt(sum(x * x for x in v))


def test_shrink_keeps_the_first_numbers_and_normalises():
    out = shrink([3.0, 4.0, 99.0], 2)
    assert out == pytest.approx([0.6, 0.8])


@pytest.mark.parametrize("bad", [[float("nan")] * 4, [0.0] * 4, [float("inf")] * 4])
def test_shrink_rejects_vectors_we_cannot_trust(bad):
    with pytest.raises(EmbeddingError):
        shrink(bad, 4)


def test_shrink_rejects_a_short_vector():
    with pytest.raises(EmbeddingError):
        shrink([1.0, 2.0], 4)


def test_a_query_gets_the_search_prefix_and_a_512_unit_vector():
    calls = []
    model = OllamaGemmaEmbedding(transport=fake_ollama(calls))
    vector = model.get_query_embedding("how do I define an agent?")
    sent = {"model": "embeddinggemma-2:270m", "input": [QUERY_PREFIX + "how do I define an agent?"]}
    assert calls == [("/api/embed", sent)]
    assert len(vector) == 512
    assert norm(vector) == pytest.approx(1.0)


def test_documents_are_sent_as_they_are_in_one_batch():
    calls = []
    model = OllamaGemmaEmbedding(transport=fake_ollama(calls), dimensions=256)
    vectors = model.get_text_embedding_batch(["title: A | text: one", "title: B | text: two"])
    assert [c[1]["input"] for c in calls] == [["title: A | text: one", "title: B | text: two"]]
    assert len(vectors) == 2 and len(vectors[0]) == 256


async def test_the_async_path_matches_the_sync_path():
    calls = []
    model = OllamaGemmaEmbedding(transport=fake_ollama(calls))
    assert await model.aget_query_embedding("q") == model.get_query_embedding("q")


def test_an_unsupported_dimension_is_refused():
    with pytest.raises(ValueError, match="dimensions"):
        OllamaGemmaEmbedding(dimensions=300)


def test_ollama_errors_are_reported():
    model = OllamaGemmaEmbedding(transport=fake_ollama([], status=500))
    with pytest.raises(EmbeddingError, match="500"):
        model.get_query_embedding("q")


def test_an_unreachable_ollama_is_reported():
    def refuse(request):
        raise httpx.ConnectError("refused")

    model = OllamaGemmaEmbedding(transport=httpx.MockTransport(refuse))
    with pytest.raises(EmbeddingError, match="cannot reach Ollama"):
        model.get_query_embedding("q")


def test_a_nan_vector_from_ollama_is_rejected():
    body = b'{"embeddings": [[' + b",".join([b"NaN"] * 768) + b"]]}"  # JSON encoders refuse to write NaN
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    model = OllamaGemmaEmbedding(transport=transport)
    with pytest.raises(EmbeddingError):
        model.get_query_embedding("q")
