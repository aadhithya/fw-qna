import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from fw_qna.conversation import STUB_ACK, STUB_MARKER, Conversation, history_tool, is_stub


def turn(conversation, question, answer, *, search=None, tokens=None):
    """Add one turn: a question, optionally a search with its result, and an answer."""
    messages = []
    if search:
        call = {"name": "search_docs", "args": {"query": search["query"]}, "id": f"id-{question}"}
        messages.append(AIMessage(content="", tool_calls=[call]))
        messages.append(ToolMessage(content=json.dumps({"results": search["results"]}), tool_call_id=f"id-{question}"))
    usage = {"input_tokens": tokens, "output_tokens": 10, "total_tokens": tokens + 10} if tokens else None
    messages.append(AIMessage(content=answer, usage_metadata=usage))
    conversation.add_turn(HumanMessage(content=question), messages)


@pytest.fixture
def conversation():
    c = Conversation(keep_turns=2)
    yield c
    c.close()


def six_turns(conversation):
    for i in range(6):
        turn(
            conversation,
            f"question {i} about topic{i}",
            f"answer {i}",
            search={
                "query": f"topic{i}",
                "results": [{"ref": i + 1, "title": f"Page {i}", "text": f"text about topic{i} and JobWorker{i}"}],
            },
        )


def test_the_context_size_is_the_last_calls_input_and_output(conversation):
    turn(conversation, "a", "b", tokens=1000)
    turn(conversation, "c", "d", tokens=5000)
    assert conversation.context_tokens() == 5010


def test_without_token_counts_the_size_is_estimated(conversation):
    turn(conversation, "x" * 350, "y" * 350)
    assert conversation.context_tokens() == 200


def test_nothing_moves_while_the_conversation_is_short(conversation):
    turn(conversation, "a", "b")
    turn(conversation, "c", "d")
    assert conversation.offload() == 0
    assert len(conversation.messages) == 4


def test_the_newest_turns_stay_and_the_rest_move_to_the_archive(conversation):
    six_turns(conversation)
    moved = conversation.offload()
    assert moved == 4 * 4  # four turns, each a question, a search call, its result and an answer
    live = [m.content for m in conversation.messages if isinstance(m, HumanMessage)]
    assert live[1:] == ["question 4 about topic4", "question 5 about topic5"]
    assert is_stub(conversation.messages[0]) and conversation.messages[1].content == STUB_ACK


def test_a_tool_result_is_never_left_without_its_call(conversation):
    six_turns(conversation)
    conversation.offload()
    seen_calls = set()
    for message in conversation.messages:
        if isinstance(message, AIMessage):
            seen_calls |= {c["id"] for c in message.tool_calls}
        if isinstance(message, ToolMessage):
            assert message.tool_call_id in seen_calls


def test_the_stub_lists_the_questions_that_moved(conversation):
    six_turns(conversation)
    conversation.offload()
    stub = conversation.messages[0].content
    assert stub.startswith(STUB_MARKER) and "search_history" in stub
    assert "1. question 0 about topic0" in stub and "4. question 3 about topic3" in stub
    assert "question 4" not in stub  # still in view


def test_moving_again_adds_to_the_archive_and_never_archives_the_stub(conversation):
    six_turns(conversation)
    conversation.offload()
    turn(conversation, "question 6 about topic6", "answer 6")
    turn(conversation, "question 7 about topic7", "answer 7")
    conversation.offload()
    questions = conversation.archive.questions()
    assert len(questions) == 6 and all(not q.startswith(STUB_MARKER) for q in questions)
    assert sum(is_stub(m) for m in conversation.messages) == 1


def test_the_archive_finds_questions_answers_and_sources(conversation):
    six_turns(conversation)
    conversation.offload()
    found = conversation.archive.search("JobWorker2")
    assert found and found[0]["role"] == "source" and found[0]["ref"] == 3 and found[0]["turn"] == 3
    assert any(r["role"] == "user" for r in conversation.archive.search("question 1"))


def test_the_archive_returns_nothing_for_unrelated_words(conversation):
    six_turns(conversation)
    conversation.offload()
    assert conversation.archive.search("zebra") == []
    assert conversation.archive.search("???") == []


def test_an_empty_archive_finds_nothing(conversation):
    assert conversation.archive.search("anything") == []


def test_the_archive_file_is_deleted_when_the_session_ends(conversation):
    six_turns(conversation)
    conversation.offload()
    path = conversation.archive.path
    assert path.is_file() and len(path.read_text().splitlines()) == len(conversation.archive.records)
    conversation.close()
    assert not Path(path).parent.exists()


def test_clear_starts_again_with_a_new_archive(conversation):
    six_turns(conversation)
    conversation.offload()
    old = conversation.archive.directory
    conversation.clear()
    assert conversation.messages == [] and conversation.archive.records == [] and not old.exists()


async def test_the_search_history_tool_returns_json(conversation):
    six_turns(conversation)
    conversation.offload()
    tool = history_tool(conversation)
    result = json.loads(await tool.ainvoke({"query": "topic1 JobWorker1", "max_results": 3}))
    assert result["results"] and "JobWorker1" in result["results"][0]["text"]
    assert "note" in json.loads(await tool.ainvoke({"query": "zebra"}))
