import json

import pytest
from featherweight import AgentRunner, Claude, SqliteDatabase

from fakes import FakeSettings, ScriptedChat
from fw_qna.agent import PROMPT, make_chat_agent
from fw_qna.config import Settings
from fw_qna.conversation import Conversation, history_tool
from fw_qna.index import Index
from fw_qna.ingest import build_nodes
from fw_qna.retrieval import Retriever
from fw_qna.search_tool import DocSearch
from fw_qna.session import Cancelled, ChatSession, Failed, Finished, Searched, Searching, TextDelta

URL = "https://github.com/acme/widget"
SEARCH = {"tool": ("search_docs", {"query": "job worker queue", "keywords": ["JobWorker"], "top_k": 3})}


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

    def factory(steps, *, limit=100_000, keep_turns=4, pause=0.0):
        chat = ScriptedChat(steps=steps, pause=pause)
        session = ChatSession(
            runner,
            retriever,
            Settings(context_limit=limit),
            model=FakeSettings(chat=chat),
            conversation=Conversation(keep_turns=keep_turns),
        )
        sessions.append(session)
        return session, chat

    yield factory
    for session in sessions:
        session.close()


async def collect(session, text):
    return [event async for event in session.ask(text)]


async def test_a_turn_searches_streams_and_cites(make):
    session, _ = make([SEARCH, {"text": ["Jobs run on a worker [1]", " and more [9]."]}])
    events = await collect(session, "how do jobs run?")
    kinds = [type(e) for e in events]
    assert kinds[0] is Searching and Searched in kinds and kinds[-1] is Finished
    searching = events[0]
    assert searching.tool == "search_docs" and searching.args["keywords"] == ["JobWorker"]
    assert next(e for e in events if isinstance(e, Searched)).count == 3
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Jobs run on a worker [1] and more [9]."
    done = events[-1]
    assert [c.ref for c in done.cited] == [1]
    assert done.cited[0].url.startswith(f"{URL}/blob/v0.1.0/")
    assert done.unverified == [9]  # a number no search returned
    assert {c.ref for c in done.also_searched} == {2, 3}  # found, but the answer did not cite them


async def test_small_talk_needs_no_search(make):
    session, _ = make([{"text": ["Hello! Ask me about featherweight."]}])
    done = (await collect(session, "hi"))[-1]
    assert isinstance(done, Finished) and done.cited == [] and done.also_searched == []


async def test_the_whole_conversation_goes_to_the_model_each_turn(make):
    session, chat = make([{"text": ["first answer"]}, {"text": ["second answer"]}])
    await collect(session, "first question")
    await collect(session, "second question")
    texts = [str(m.content) for m in chat.seen[-1]]
    assert any("first question" in t for t in texts) and any("first answer" in t for t in texts)
    assert texts[-1] == "second question"


async def test_the_context_size_is_reported_from_the_models_usage(make):
    session, _ = make([{"text": ["answer"], "usage": (1200, 30)}], limit=50_000)
    done = (await collect(session, "q"))[-1]
    assert (done.context_tokens, done.context_limit, done.offloaded) == (1230, 50_000, 0)


async def test_old_turns_move_to_the_archive_when_the_context_nears_its_limit(make):
    session, chat = make([{"text": [f"answer {i}"], "usage": (900, 100)} for i in range(5)], limit=1000, keep_turns=2)
    offloaded = [(await collect(session, f"question {i}"))[-1].offloaded for i in range(4)]
    assert offloaded[0] == 0 and offloaded[1] == 0  # two turns: nothing older than the newest two
    assert offloaded[2] > 0  # the third turn pushes the first out of view
    assert session.conversation.archive.search("question 0")
    await collect(session, "what did I ask first?")
    assert "search_history" in str(chat.seen[-1][0].content)  # the stub tells the model where the old turns went


async def test_the_context_limit_is_read_on_every_turn(make):
    session, _ = make([{"text": ["a"], "usage": (900, 100)}] * 4, limit=1_000_000, keep_turns=1)
    assert (await collect(session, "q1"))[-1].offloaded == 0
    session.settings.context_limit = 1000  # what the /context command does
    await collect(session, "q2")
    assert (await collect(session, "q3"))[-1].offloaded > 0


async def test_stopping_keeps_what_was_written(make):
    session, chat = make([{"text": ["one ", "two ", "three ", "four"]}, {"text": ["fine"]}], pause=0.05)
    seen = []
    async for event in session.ask("write something long"):
        seen.append(event)
        if isinstance(event, TextDelta):
            session.cancel()
    assert isinstance(seen[-1], Cancelled) and seen[-1].text.startswith("one")
    assert len(seen[-1].text) < len("one two three four")
    kept = session.conversation.messages
    assert kept[0].content == "write something long" and kept[-1].content.startswith("one")
    await collect(session, "carry on")  # the chat goes on
    assert any("one" in str(m.content) for m in chat.seen[-1])


async def test_a_failed_turn_is_reported_and_leaves_no_dangling_question(make):
    session, _ = make([{"error": "the model is down"}, {"text": ["back again"]}])
    events = await collect(session, "hello?")
    assert isinstance(events[-1], Failed) and "the model is down" in events[-1].error
    assert session.conversation.messages == []
    assert isinstance(await collect(session, "again"), list)


async def test_a_conversation_can_be_cleared(make):
    session, _ = make([SEARCH, {"text": ["answer [1]"]}])
    await collect(session, "q")
    assert session.doc_search.citations
    session.clear()
    assert session.conversation.messages == [] and session.doc_search.citations == {}


async def test_the_session_default_release_is_used_for_searches(make):
    session, _ = make([SEARCH, {"text": ["ok"]}])
    session.doc_search.version = "v0.9.9"  # not indexed, so the search must report it, not use the latest
    events = await collect(session, "q")
    assert next(e for e in events if isinstance(e, Searched)).count == 0
    tool_result = next(m for m in session.conversation.messages if m.type == "tool")
    assert "v0.9.9 is not indexed" in json.loads(tool_result.content)["error"]


def test_the_agent_has_both_tools_and_a_strict_prompt(retriever):
    conversation = Conversation()
    tools = [DocSearch(retriever).tool(), history_tool(conversation)]
    agent = make_chat_agent(tools)()
    assert [t.name for t in agent.tools] == ["search_docs", "search_history"]
    assert isinstance(agent.model, Claude) and agent.model.model == "claude-haiku-5-5"
    for rule in ("never from memory", "[2]", "Never use Mermaid", "minimal", "search_history"):
        assert rule in PROMPT
    conversation.close()
