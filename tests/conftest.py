import hashlib
import re
import subprocess
from pathlib import Path

import pytest
from featherweight import AgentRunner, SqliteDatabase
from llama_index.core.base.embeddings.base import BaseEmbedding

from fakes import FakeSettings, ScriptedChat
from fw_qna.config import Settings
from fw_qna.conversation import Conversation
from fw_qna.index import Index
from fw_qna.ingest import build_nodes
from fw_qna.retrieval import Retriever
from fw_qna.session import ChatSession

URL = "https://github.com/acme/widget"
SEARCH = {"tool": ("search_docs", {"query": "job worker queue", "keywords": ["JobWorker"], "top_k": 3})}

BADGE = "[![docs for](https://img.shields.io/badge/x)](https://pypi.org/)"
NAV = f"<!-- nav:top -->\n[Book](../README.md) › Page  {BADGE}\n<!-- /nav:top -->\n\n"
GUIDE = (
    NAV
    + """# Agents

An agent is a typed class.

## Defining an agent

An agent is a subclass of `AgentBase`, with Pydantic models for its input and output.

```python
class Agent(AgentBase):
    name: str = "x"

    def check_output(self, agent_input, output):
        pass
```

## Short

Tiny.
"""
)
BOOK = (
    NAV
    + """# Install and set up

Get it running.

<!-- code: code/1-1/app.py -->
```python
print("hello")
```

"""
    + "A paragraph that explains the chapter in some detail. " * 8
)
CHANGELOG = """# Changelog

## [0.2.0](https://github.com/o/r/compare/v0.1.0...v0.2.0) (2026-12-01)

### Features

* a new thing ([abcdef1](https://github.com/o/r/commit/abcdef1234567890))
* another thing ([1234567](https://github.com/o/r/commit/1234567abcdef000)), closes [#12](https://github.com/o/r/issues/12)

## 0.1.0 (2026-11-20)

### Features

* the first thing ([7654321](https://github.com/o/r/commit/7654321fedcba000))
"""


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def git(cwd: Path, *args: str) -> None:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "HOME": str(cwd),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture
def release_tree(tmp_path_factory) -> Path:
    """A tree shaped like a featherweight release."""
    root = tmp_path_factory.mktemp("tree")
    write(root, "docs/agents.md", GUIDE)
    write(root, "docs/releasing.md", "# Releasing\n\nHow to cut a release. " * 20)
    write(root, "docs/book/01-start/01-install.md", BOOK)
    write(root, "docs/book/SUMMARY.md", "# Summary\n")
    write(root, "docs/book/code/1-1/app.py", 'print("hello")\n')
    write(root, "docs/specs/runner.md", "# Spec: runner\n\n" + "The runner runs agents with retries. " * 10)
    write(root, "CHANGELOG.md", CHANGELOG)
    write(root, "examples/jobs/README.md", "# Jobs\n\nRun a job on a worker.\n")
    write(root, "examples/jobs/run.py", "print('run')\n")
    write(root, "examples/bigapp/README.md", "# Big app\n\nA whole application.\n")
    for i in range(14):
        write(root, f"examples/bigapp/mod{i}.py", "x = 1\n" * 400)
    write(root, "examples/jobs/samples/data.md", "# Sample\n\nnot an example\n")
    write(
        root,
        "skills/featherweight/SKILL.md",
        "---\nname: featherweight\n"
        "description: Build agents with featherweight. Use when writing featherweight code.\n---\n\n"
        "# Building with featherweight\n\nRead references/recipes.md for patterns.\n",
    )
    write(root, "skills/featherweight/references/recipes.md", "# Recipes\n\nA fake model for tests.\n")
    write(root, "skills/not-a-skill/notes.txt", "no SKILL.md here\n")
    return root


@pytest.fixture
def repo(release_tree) -> Path:
    """A git repository with that tree, tagged v0.1.0."""
    git(release_tree, "init", "-q", "-b", "main")
    git(release_tree, "remote", "add", "origin", "git@github.com:acme/widget.git")
    git(release_tree, "add", "-A")
    git(release_tree, "commit", "-q", "-m", "initial")
    git(release_tree, "tag", "v0.1.0")
    return release_tree


class FakeEmbedding(BaseEmbedding):
    """A stand-in for Ollama: the same text always gives the same unit vector, and nothing is called."""

    dimensions: int = 512
    model_name: str = "fake-embedding"
    calls: list = []  # every batch of texts that was embedded

    def _vector(self, text: str) -> list[float]:
        raw = (hashlib.sha256(text.encode()).digest() * 40)[: self.dimensions]
        values = [b - 127.5 for b in raw]
        norm = sum(v * v for v in values) ** 0.5
        return [v / norm for v in values]

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._vector(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._vector(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._vector(text)

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(t) for t in texts]


@pytest.fixture
def fake_embedding() -> FakeEmbedding:
    return FakeEmbedding(calls=[])


class WordsEmbedding(FakeEmbedding):
    """Texts that share words get similar vectors, so search tests have a meaning to rank by."""

    def _vector(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        for word in re.findall(r"\w+", text.lower()):
            values[int(hashlib.sha256(word.encode()).hexdigest(), 16) % self.dimensions] += 1.0
        norm = sum(v * v for v in values) ** 0.5 or 1.0
        return [v / norm for v in values]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._vector(query)


@pytest.fixture
def words_embedding() -> WordsEmbedding:
    return WordsEmbedding(calls=[])


@pytest.fixture
async def runner(tmp_path):
    async with SqliteDatabase(tmp_path / "runs.db") as db:
        yield AgentRunner(db)


@pytest.fixture
def retriever(tmp_path, release_tree, words_embedding):
    (release_tree / "docs/jobs.md").write_text(
        "# Jobs\n\nThe JobWorker takes a job from the queue and runs it on a worker. " * 6
    )
    index = Index(tmp_path / "index", words_embedding)
    index.add_release("v0.1.0", build_nodes(release_tree, "v0.1.0", URL))
    return Retriever(index)


@pytest.fixture
def make(runner, retriever):
    sessions = []

    def factory(steps, *, limit=100_000, keep_turns=4, pause=0.0, data_dir=None):
        chat = ScriptedChat(steps=steps, pause=pause)
        session = ChatSession(
            runner,
            retriever,
            Settings(context_limit=limit),
            model=FakeSettings(chat=chat),
            conversation=Conversation(keep_turns=keep_turns),
            data_dir=data_dir,
        )
        sessions.append(session)
        return session, chat

    yield factory
    for session in sessions:
        session.close()
