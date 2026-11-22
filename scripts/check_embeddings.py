"""Ask the real model for a few vectors and check that they are sane. Run it with: make check-embeddings"""

import math
import os
import sys

from fw_qna.embedder import OllamaGemmaEmbedding

model = OllamaGemmaEmbedding(base_url=os.environ.get("FW_QNA_OLLAMA_URL", "http://localhost:11434"))

query = model.get_query_embedding("How do I define an agent?")
related = model.get_text_embedding(
    "title: Agents > Defining an agent (guide) | text: An agent is a subclass of AgentBase with typed input."
)
unrelated = model.get_text_embedding(
    "title: Releasing (guide) | text: Run the release workflow to open a release pull request."
)


def norm(v):
    return math.sqrt(sum(x * x for x in v))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


print(f"dimensions: {len(query)} (expected {model.dimensions})")
print(f"unit length: {norm(query):.4f}, {norm(related):.4f}, {norm(unrelated):.4f}")
print(f"query vs related doc:   {dot(query, related):.3f}")
print(f"query vs unrelated doc: {dot(query, unrelated):.3f}")

ok = (
    len(query) == model.dimensions
    and all(abs(norm(v) - 1) < 1e-4 for v in (query, related, unrelated))
    and dot(query, related) > dot(query, unrelated)
)
print("OK" if ok else "NOT OK: the related document should be closer than the unrelated one")
sys.exit(0 if ok else 1)
