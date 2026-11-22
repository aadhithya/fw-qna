"""One chat session: asks the agent, and turns what happens into events the interface can show.

The interface (a terminal today, a browser one day) only has to render these events. Everything about the
conversation lives here: the history, the numbered sources, the context size, and what to do when it nears its limit.
"""

import json
import re
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

from ag_ui.core import EventType
from featherweight import AgentRunner, ChatInput, ModelSettings, RunStatus
from langchain_core.messages import HumanMessage

from .agent import make_chat_agent
from .config import Settings
from .conversation import Conversation, history_tool
from .retrieval import Retriever
from .search_tool import Citation, DocSearch

OFFLOAD_AT = 0.8  # archive the old turns when the context is this full
CITATION = re.compile(r"\[(\d+)\]")


@dataclass
class Searching:
    """The model called a tool."""

    tool: str
    args: dict[str, Any]


@dataclass
class Searched:
    """The tool answered."""

    tool: str
    count: int


@dataclass
class TextDelta:
    text: str


@dataclass
class Finished:
    """The answer is complete."""

    text: str
    cited: list[Citation]  # the sources the answer relies on, in the order they were cited
    unverified: list[int]  # numbers the answer cited that no search returned
    also_searched: list[Citation]  # found in this turn but not cited
    context_tokens: int
    context_limit: int
    offloaded: int  # messages moved to the archive after this turn
    usage: Any = None


@dataclass
class Cancelled:
    text: str  # what was written before the stop


@dataclass
class Failed:
    error: str


Event = Searching | Searched | TextDelta | Finished | Cancelled | Failed


@dataclass
class ChatSession:
    runner: AgentRunner
    retriever: Retriever
    settings: Settings  # read on every turn, so /context takes effect at once
    model: ModelSettings | None = None  # None means the agent's own (Claude Haiku); tests pass a fake
    conversation: Conversation = field(default_factory=Conversation)

    def __post_init__(self) -> None:
        self.doc_search = DocSearch(self.retriever)
        self.agent = make_chat_agent([self.doc_search.tool(), history_tool(self.conversation)], self.model)
        self._run: Any = None

    def cancel(self) -> None:
        """Stop the answer that is being written. What was written stays in the conversation."""
        if self._run is not None:
            self._run.cancel()

    def clear(self) -> None:
        self.conversation.clear()
        self.doc_search.reset()

    def close(self) -> None:
        self.conversation.close()

    async def ask(self, text: str) -> AsyncIterator[Event]:
        user = HumanMessage(content=text)
        run = self.runner.stream(self.agent, ChatInput.from_langchain([*self.conversation.messages, user]))
        self._run = run
        names: dict[str, str] = {}
        arguments: dict[str, str] = {}
        retrieved: list[int] = []  # the numbers search_docs returned in this turn
        written: list[str] = []
        error = ""
        try:
            async with aclosing(aiter(run)) as events:
                async for event in events:
                    kind = event.type
                    if kind == EventType.TOOL_CALL_START:
                        names[event.tool_call_id] = event.tool_call_name
                        arguments[event.tool_call_id] = ""
                    elif kind == EventType.TOOL_CALL_ARGS:
                        arguments[event.tool_call_id] += event.delta
                    elif kind == EventType.TOOL_CALL_END:
                        yield Searching(names[event.tool_call_id], _parse(arguments[event.tool_call_id]))
                    elif kind == EventType.TOOL_CALL_RESULT:
                        tool = names.get(event.tool_call_id, "")
                        refs = [r["ref"] for r in _parse(event.content).get("results", []) if "ref" in r]
                        if tool == "search_docs":
                            retrieved += refs
                        yield Searched(tool, len(refs))
                    elif kind == EventType.TEXT_MESSAGE_CONTENT:
                        written.append(event.delta)
                        yield TextDelta(event.delta)
                    elif kind == EventType.RUN_ERROR:
                        error = event.message
        finally:
            self._run = None
            if run.new_messages or run.status != RunStatus.FAILED:
                self.conversation.add_turn(user, run.new_messages)
        answer = "".join(written)
        if run.status == RunStatus.CANCELLED:
            yield Cancelled(answer)
        elif run.status == RunStatus.FAILED:
            yield Failed(error or str(run.error) or "the model call failed")
        else:
            yield self._finished(answer, retrieved, run)

    def _finished(self, answer: str, retrieved: list[int], run: Any) -> Finished:
        known = self.doc_search.citations
        numbers = list(dict.fromkeys(int(n) for n in CITATION.findall(answer)))
        cited = [known[n] for n in numbers if n in known]
        unverified = [n for n in numbers if n not in known]
        also = [known[n] for n in dict.fromkeys(retrieved) if n not in numbers]
        context = self.conversation.context_tokens()
        limit = self.settings.context_limit
        offloaded = self.conversation.offload() if context >= OFFLOAD_AT * limit else 0
        usage = run.usage[0] if isinstance(run.usage, list) and run.usage else run.usage
        return Finished(answer, cited, unverified, also, context, limit, offloaded, usage)


def _parse(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
