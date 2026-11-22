"""The conversation: kept in memory for the session, with the oldest turns moved to an archive when it grows.

featherweight keeps no conversation, so this is where it lives (as LangChain messages, which featherweight
reads and writes). When the context nears its limit, the oldest turns move to a temporary file. A stub at the
start of the history tells the model they are there, with the questions asked so far, and the ``search_history``
tool searches them with BM25. The file is deleted when the session ends.
"""

import atexit
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import bm25s
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

KEEP_TURNS = 4  # the newest turns that stay in view when the rest is archived
STUB_MARKER = "[Earlier in this conversation"
STUB_ACK = "Understood. I will use search_history when I need something said earlier."
MAX_STUB_QUESTIONS = 30
CHARS_PER_TOKEN = 3.5  # a rough guess, used only when the provider reported no token counts

HISTORY_DESCRIPTION = """Search the earlier part of THIS conversation, which has been moved out of view to save \
space. Use it when the user refers to something said before that you cannot see (a question, an answer, a code \
example, a source). It does not search the featherweight docs: use search_docs for that. Write `query` as the \
words that would appear in the earlier message."""


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return " ".join(part.get("text", "") for part in content if isinstance(part, dict))


def is_stub(message: BaseMessage) -> bool:
    return isinstance(message, HumanMessage) and _text(message).startswith(STUB_MARKER)


class Archive:
    """The turns that left the live history, in a temporary file, searchable with BM25."""

    def __init__(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="fw-qna-archive-"))
        self.path = self.directory / "archive.jsonl"
        self.records: list[dict[str, Any]] = []
        self._index: bm25s.BM25 | None = None
        atexit.register(self.close)

    def add(self, records: list[dict[str, Any]]) -> None:
        with self.path.open("a") as file:
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.records += records
        self._index = None  # rebuilt on the next search

    def questions(self) -> list[str]:
        return [r["text"] for r in self.records if r["role"] == "user"]

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        if not self.records:
            return []
        if self._index is None:
            tokens = bm25s.tokenize([r["text"] for r in self.records], stopwords=None, show_progress=False)
            self._index = bm25s.BM25()
            self._index.index(tokens, show_progress=False)
        wanted = bm25s.tokenize([query], stopwords=None, show_progress=False, return_ids=False)
        if not wanted[0]:
            return []
        found, scores = self._index.retrieve(wanted, k=min(max_results, len(self.records)), show_progress=False)
        return [self.records[i] for i, score in zip(found[0], scores[0], strict=True) if score > 0]

    def close(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


def records_of(messages: list[BaseMessage], first_turn: int) -> list[dict[str, Any]]:
    """What is worth searching in some messages: the questions, the answers and the sources that were read."""
    records: list[dict[str, Any]] = []
    turn = first_turn - 1
    for message in messages:
        if isinstance(message, HumanMessage):
            turn += 1
            records.append({"turn": turn, "role": "user", "text": _text(message)})
        elif isinstance(message, AIMessage):
            if _text(message).strip():
                records.append({"turn": turn, "role": "assistant", "text": _text(message)})
            for call in message.tool_calls:
                args = " ".join(str(v) for v in call["args"].values() if v)
                records.append({"turn": turn, "role": "assistant", "text": f"searched the docs for: {args}"})
        elif isinstance(message, ToolMessage):
            try:
                results = json.loads(_text(message)).get("results", [])
            except (ValueError, AttributeError):
                results = []
            for result in results:
                records.append(
                    {
                        "turn": turn,
                        "role": "source",
                        "ref": result.get("ref"),
                        "text": f"[{result.get('ref')}] {result.get('title', '')}\n{result.get('text', '')}",
                    }
                )
    return records


class Conversation:
    def __init__(self, keep_turns: int = KEEP_TURNS) -> None:
        self.keep_turns = keep_turns
        self.messages: list[BaseMessage] = []
        self.archive = Archive()
        self.archived_turns = 0

    def add_turn(self, user: HumanMessage, new_messages: list[BaseMessage]) -> None:
        self.messages += [user, *new_messages]

    def context_tokens(self) -> int:
        """The size of the context at the last model call: what it read, plus what it wrote."""
        for message in reversed(self.messages):
            usage = getattr(message, "usage_metadata", None)
            if isinstance(message, AIMessage) and usage:
                return usage["input_tokens"] + usage["output_tokens"]
        return int(sum(len(_text(m)) for m in self.messages) / CHARS_PER_TOKEN)

    def _turn_starts(self) -> list[int]:
        return [i for i, m in enumerate(self.messages) if isinstance(m, HumanMessage) and not is_stub(m)]

    def offload(self) -> int:
        """Move all but the newest turns to the archive. Return how many messages moved."""
        starts = self._turn_starts()
        if len(starts) <= self.keep_turns:
            return 0
        cut = starts[-self.keep_turns]
        moving = [m for m in self.messages[:cut] if not is_stub(m)]
        self.archive.add(records_of(moving, self.archived_turns + 1))
        self.archived_turns += sum(isinstance(m, HumanMessage) for m in moving)
        self.messages = [*self._stub(), *self.messages[cut:]]
        return len(moving)

    def _stub(self) -> list[BaseMessage]:
        questions = self.archive.questions()[-MAX_STUB_QUESTIONS:]
        listed = "\n".join(f"{i}. {q[:120]}" for i, q in enumerate(questions, 1))
        text = (
            f"{STUB_MARKER} some messages were moved out of view into an archive. Search it with the "
            f"search_history tool. The questions asked so far:\n{listed}]"
        )
        return [HumanMessage(content=text), AIMessage(content=STUB_ACK)]

    def clear(self) -> None:
        self.messages = []
        self.archive.close()
        self.archive = Archive()
        self.archived_turns = 0

    def close(self) -> None:
        self.archive.close()


class HistoryArgs(BaseModel):
    query: str = Field(description="Words from the earlier message you are looking for.")
    max_results: int = Field(default=5, ge=1, le=10, description="How many matches to return.")


def history_tool(conversation: Conversation) -> StructuredTool:
    async def search_history(query: str, max_results: int = 5) -> str:
        found = conversation.archive.search(query, max_results)
        if not found:
            return json.dumps({"results": [], "note": "Nothing in the earlier conversation matches."})
        results = [{k: v for k, v in r.items() if v is not None} | {"text": r["text"][:1500]} for r in found]
        return json.dumps({"results": results}, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=search_history, name="search_history", description=HISTORY_DESCRIPTION, args_schema=HistoryArgs
    )
