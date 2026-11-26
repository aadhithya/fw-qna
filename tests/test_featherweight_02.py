"""What featherweight 0.2 changed that would not show up as an error. No real model is called."""

import base64
from importlib.metadata import version

import pytest
from ag_ui.core import DocumentInputContent, InputContentDataSource, TextInputContent, UserMessage
from featherweight import AttachmentLimitError, ChatInput, Skill

from fw_qna.agent import DocsChat
from fw_qna.session import Finished, SkillRead


def test_the_tests_run_on_featherweight_0_2():
    assert version("featherweight").startswith("0.2.")


def test_the_chat_agent_builds_and_takes_no_files():
    agent = DocsChat()  # building it checks the model and its settings, and calls nothing
    assert DocsChat.max_attachments == 0 and "max_attachments" not in DocsChat.model_fields  # what the limit reads
    assert agent.version == "2"


async def test_a_conversation_with_a_file_is_refused_before_the_model_is_called(make):
    session, chat = make([{"text": ["should never be written"]}])
    data = base64.b64encode(b"%PDF-1.4 not a real file").decode()
    pdf = DocumentInputContent(source=InputContentDataSource(value=data, mime_type="application/pdf"))
    message = UserMessage(id="1", content=[TextInputContent(text="read this"), pdf])
    with pytest.raises(AttachmentLimitError):
        session.runner.stream(session.agent, ChatInput(messages=[message]))
    assert chat.index == 0


class UnreadableSkill(Skill):
    """A skill whose store is down: 0.2 reads skills with ``aread``, and answers the model instead of raising."""

    async def aread(self, resource: str = "") -> str:
        raise ConnectionError("the store is down")


@pytest.mark.parametrize(
    "call, reply",
    [
        ({"name": "featherweight"}, "could not be read"),
        ({"name": "featherweight", "resource": "../../outside.md"}, "has no file"),
        ({"name": "featherweight", "resource": "/etc/passwd"}, "has no file"),
    ],
)
async def test_a_skill_read_that_gives_nothing_is_not_listed_as_a_source(make, tmp_path, monkeypatch, call, reply):
    skill = UnreadableSkill(name="featherweight", description="Build with featherweight.")
    monkeypatch.setattr("fw_qna.session.load_skills", lambda data_dir, tag: [skill])
    session, chat = make([{"tool": ("get_skill", call)}, {"text": ["ok"]}], data_dir=tmp_path)
    events = [event async for event in session.ask("write a worker")]
    told = str(chat.seen[1][-1].content)  # featherweight's own wording, which the session has to recognise
    assert reply in told
    assert not any(isinstance(event, SkillRead) for event in events)
    assert isinstance(events[-1], Finished) and events[-1].skills_read == [] and session.skills_read == []
