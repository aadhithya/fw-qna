"""``fw-qna chat``: the terminal chat. It wires the index, the agent and the interface together."""

import asyncio
import os
from pathlib import Path

from featherweight import AgentRunner, SqliteDatabase
from llama_index.core.base.embeddings.base import BaseEmbedding
from rich.console import Console

from .config import Settings, ensure_config_file
from .index import Index
from .retrieval import Retriever
from .session import ChatSession
from .ui import ChatUI


def run_chat(data_dir: Path, embedder: BaseEmbedding, console: Console | None = None) -> int:
    console = console or Console()
    ensure_config_file(data_dir)  # so there is a commented file to edit, even before the first chat
    index = Index(data_dir / "index", embedder)
    if not index.releases():
        console.print("Nothing is indexed yet. Index a release first: make ingest REF=v0.1.0")
        return 1
    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("ANTHROPIC_API_KEY is not set. The chat model is Claude, and it needs your key.")
        return 1
    asyncio.run(_chat(data_dir, index, console))
    return 0


async def _chat(data_dir: Path, index: Index, console: Console) -> None:
    from prompt_toolkit import PromptSession  # only needed here
    from prompt_toolkit.history import InMemoryHistory

    settings = Settings.load(data_dir)
    async with SqliteDatabase(data_dir / "runs.db") as db:
        session = ChatSession(AgentRunner(db), Retriever(index), settings)
        ui = ChatUI(session, settings, data_dir, console)
        prompt = PromptSession(history=InMemoryHistory())  # the history lives for this session only
        message = [(f"fg:{ui.theme.user} bold", "❯ ")]

        async def read() -> str:
            return await prompt.prompt_async(message)

        try:
            await ui.run(read)
        finally:
            session.close()
