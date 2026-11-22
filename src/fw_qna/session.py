"""One chat session: asks the agent, and turns what happens into events the interface can show.

The interface (a terminal today, a browser one day) only has to render these events. Everything about the
conversation lives here: the history, the numbered sources, the context size, and what to do when it nears its limit.
"""

import json
import re
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ag_ui.core import EventType
from featherweight import AgentRunner, ChatInput, ModelSettings, RunStatus
from langchain_core.messages import HumanMessage

from .agent import make_chat_agent
from .config import Settings
from .conversation import Conversation, history_tool
from .retrieval import Retriever
from .search_tool import Citation, DocSearch
from .skills import load_skills, skill_source

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


@dataclass(frozen=True)
class SkillRead:
    """The agent read a skill, or one of its files, with ``get_skill``."""

    name: str
    resource: str  # empty means the skill's own SKILL.md
    url: str | None  # the file on GitHub, at the release tag

    @property
    def file(self) -> str:
        return self.resource or "SKILL.md"


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
    skills_read: list[SkillRead] = field(default_factory=list)  # the skill files the agent read in this turn


@dataclass
class Cancelled:
    text: str  # what was written before the stop


@dataclass
class Failed:
    error: str


Event = Searching | Searched | SkillRead | TextDelta | Finished | Cancelled | Failed


@dataclass
class ChatSession:
    runner: AgentRunner
    retriever: Retriever
    settings: Settings  # read on every turn, so /context takes effect at once
    model: ModelSettings | None = None  # None means the agent's own (Claude Haiku); tests pass a fake
    conversation: Conversation = field(default_factory=Conversation)
    data_dir: Path | None = None  # where the release's skills are installed; None means no skills

    def __post_init__(self) -> None:
        self.doc_search = DocSearch(self.retriever)
        self.skills_read: list[SkillRead] = []  # every skill file read in this conversation, once each
        self.skill_names: list[str] = []
        self._skill_source: dict[str, str] | None = None
        self.agent = self._build_agent()
        self._run: Any = None

    def answering_version(self) -> str | None:
        return self.doc_search.version or self.retriever.index.latest()

    def _build_agent(self):
        """The agent for the release this conversation answers from: its tools, and that release's skills."""
        version = self.answering_version()
        skills = load_skills(self.data_dir, version) if self.data_dir and version else []
        self.skill_names = [skill.name for skill in skills]
        self._skill_source = skill_source(self.data_dir, version) if skills and self.data_dir else None
        tools = [self.doc_search.tool(), history_tool(self.conversation)]
        return make_chat_agent(tools, self.model, skills)

    def set_version(self, version: str | None) -> None:
        """Answer from another release (None: the latest). Its skills come with it."""
        self.doc_search.version = version
        self.agent = self._build_agent()

    def _skill_read(self, args: dict[str, Any]) -> SkillRead:
        name, resource = str(args.get("name", "")), str(args.get("resource") or "")
        url = None
        if self._skill_source:
            base = f"{self._skill_source['repo_url']}/blob/{self._skill_source['tag']}/skills/{name}"
            url = f"{base}/{resource or 'SKILL.md'}"
        return SkillRead(name, resource, url)

    def cancel(self) -> None:
        """Stop the answer that is being written. What was written stays in the conversation."""
        if self._run is not None:
            self._run.cancel()

    def clear(self) -> None:
        self.conversation.clear()
        self.doc_search.reset()
        self.skills_read.clear()

    def close(self) -> None:
        self.conversation.close()

    async def ask(self, text: str) -> AsyncIterator[Event]:
        user = HumanMessage(content=text)
        run = self.runner.stream(self.agent, ChatInput.from_langchain([*self.conversation.messages, user]))
        self._run = run
        names: dict[str, str] = {}
        arguments: dict[str, str] = {}
        retrieved: list[int] = []  # the numbers search_docs returned in this turn
        skill_reads: list[SkillRead] = []  # the skill files read in this turn
        called: dict[str, dict[str, Any]] = {}  # each tool call's arguments
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
                        called[event.tool_call_id] = _parse(arguments[event.tool_call_id])
                        yield Searching(names[event.tool_call_id], called[event.tool_call_id])
                    elif kind == EventType.TOOL_CALL_RESULT:
                        tool = names.get(event.tool_call_id, "")
                        if tool == "get_skill" and not _skill_error(event.content):
                            read = self._skill_read(called.get(event.tool_call_id, {}))
                            skill_reads.append(read)
                            if read not in self.skills_read:
                                self.skills_read.append(read)
                            yield read
                            continue
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
            yield self._finished(answer, retrieved, run, skill_reads)

    def _finished(self, answer: str, retrieved: list[int], run: Any, skill_reads: list[SkillRead]) -> Finished:
        known = self.doc_search.citations
        numbers = list(dict.fromkeys(int(n) for n in CITATION.findall(answer)))
        cited = [known[n] for n in numbers if n in known]
        unverified = [n for n in numbers if n not in known]
        also = [known[n] for n in dict.fromkeys(retrieved) if n not in numbers]
        context = self.conversation.context_tokens()
        limit = self.settings.context_limit
        offloaded = self.conversation.offload() if context >= OFFLOAD_AT * limit else 0
        usage = run.usage[0] if isinstance(run.usage, list) and run.usage else run.usage
        return Finished(
            answer, cited, unverified, also, context, limit, offloaded, usage, list(dict.fromkeys(skill_reads))
        )


def _skill_error(text: str) -> bool:
    """What ``get_skill`` says when the skill or the file does not exist. It never raises."""
    unknown_skill = "is not one of your skills" in text[:150]
    unknown_file = text.startswith("The skill '") and " has no file " in text[:200]
    return unknown_skill or unknown_file


def _parse(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
