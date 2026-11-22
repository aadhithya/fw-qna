import asyncio
import base64
import io
import os
import signal

import pytest
from rich.console import Console

from conftest import SEARCH
from fw_qna.chat import run_chat
from fw_qna.config import Settings
from fw_qna.theme import Theme
from fw_qna.ui import ChatUI, Tail

CODE_ANSWER = "Use a worker [1].\n\n```python\nprint('worker')\n```\n\nThat is all [9]."


@pytest.fixture
def start(make, tmp_path):
    def build(steps, **options):
        session, chat = make(steps, **options)
        console = Console(file=io.StringIO(), width=110, force_terminal=False, color_system=None)
        return ChatUI(session, session.settings, tmp_path / "data", console), console, chat

    return build


def shown(console):
    return console.file.getvalue()


async def drive(ui, *lines):
    """Type the lines one by one, then press Ctrl-D."""
    remaining = list(lines)

    async def read():
        if not remaining:
            raise EOFError
        line = remaining.pop(0)
        if isinstance(line, BaseException):
            raise line
        return line

    await ui.run(read)


async def test_the_banner_says_what_is_being_asked_about(start):
    ui, console, _ = start([{"text": ["x"]}], limit=100_000)
    await drive(ui)
    text = shown(console)
    assert "fw-qna" in text and "docs v0.1.0" in text and "claude-haiku-5-5" in text and "100,000 tokens" in text
    assert "/help" in text and "Ctrl-C" in text and text.rstrip().endswith("bye")


async def test_a_turn_shows_who_speaks_the_search_the_answer_and_the_sources(start):
    ui, console, _ = start([SEARCH, {"text": [CODE_ANSWER]}])
    await drive(ui, "how do jobs run?")
    text = shown(console)
    assert text.index("You") < text.index("fw-qna", text.index("You") + 3)
    assert 'searched docs: "job worker queue" (JobWorker) → 3 results' in text
    assert "Use a worker [1]." in text and "print('worker')" in text
    assert "Sources" in text and "[1]" in text and "https://github.com/acme/widget/blob/v0.1.0/" in text
    assert "[9] cited, but no search returned it: unverified" in text
    assert "also searched, not cited: [2]" in text
    assert "context 110 / 100,000 tokens (0%)" in text


async def test_small_talk_shows_no_sources(start):
    ui, console, _ = start([{"text": ["Hello! Ask me about featherweight."]}])
    await drive(ui, "hi")
    assert "Hello!" in shown(console) and "Sources" not in shown(console)


async def test_ctrl_c_stops_the_answer_and_the_chat_goes_on(start):
    ui, console, _ = start([{"text": ["one ", "two ", "three ", "four ", "five"]}, {"text": ["fine"]}], pause=0.1)
    asyncio.get_running_loop().call_later(0.25, os.kill, os.getpid(), signal.SIGINT)
    await drive(ui, "write something long", "and now?")
    text = shown(console)
    assert "stopped. You can correct me" in text and "five" not in text.split("stopped")[0]
    assert "fine" in text  # the next question was answered


async def test_a_failure_is_shown_in_words(start):
    ui, console, _ = start([{"error": "the model is down"}])
    await drive(ui, "hello?")
    text = shown(console)
    assert "something went wrong:" in text and "the model is down" in text


async def test_blank_lines_and_ctrl_c_at_the_prompt_do_nothing(start):
    ui, console, chat = start([{"text": ["x"]}])
    await drive(ui, "", "   ", KeyboardInterrupt())
    assert chat.index == 0 and shown(console).count("fw-qna") >= 1


async def test_help_lists_every_command(start):
    ui, console, _ = start([{"text": ["x"]}])
    await drive(ui, "/help")
    for command in ("/help", "/sources", "/version", "/context", "/save", "/copy", "/clear", "/exit"):
        assert command in shown(console)
    assert "settings.json" in shown(console)


async def test_exit_and_quit_leave(start):
    for word in ("/exit", "/quit"):
        ui, console, _ = start([{"text": ["x"]}])
        await drive(ui, word, "never reached")
        assert "never reached" not in shown(console) and shown(console).rstrip().endswith("bye")


async def test_an_unknown_command_is_explained(start):
    ui, console, _ = start([{"text": ["x"]}])
    await drive(ui, "/wat")
    assert "unknown command /wat" in shown(console)


async def test_context_shows_and_sets_the_limit_and_keeps_it(start, tmp_path):
    ui, console, _ = start([{"text": ["x"]}])
    await drive(ui, "/context", "/context 20,000", "/context 5", "/context lots")
    text = shown(console)
    assert "/ 100,000 tokens" in text and "context limit set to 20,000 tokens" in text
    assert text.count("give a number of tokens, at least 1000") == 2
    assert Settings.load(tmp_path / "data").context_limit == 20_000  # kept for the next session


async def test_a_new_limit_applies_at_once(start):
    ui, console, _ = start([{"text": ["a"], "usage": (900, 100)}] * 3, keep_turns=1)
    await drive(ui, "/context 1000", "q1", "q2")
    assert "moved" in shown(console) and "earlier messages to the archive" in shown(console)


async def test_version_shows_switches_and_resets(start):
    ui, console, _ = start([{"text": ["x"]}])
    await drive(ui, "/version", "/version v0.9.9", "/version v0.1.0", "/version latest")
    text = shown(console)
    assert "answering from v0.1.0 (the latest). indexed: v0.1.0" in text
    assert "v0.9.9 is not indexed" in text and "answering from v0.1.0\n" in text
    assert ui.session.doc_search.version is None


async def test_sources_lists_what_was_cited_so_far(start):
    ui, console, _ = start([SEARCH, {"text": ["an answer [1]"]}])
    await drive(ui, "/sources", "a question", "/sources")
    text = shown(console)
    assert "no sources yet" in text
    assert text.rsplit("Sources", 1)[1].count("↗") >= 3  # every result of the search has a number and a link


async def test_save_writes_the_last_code_block_into_the_data_directory(start, tmp_path):
    ui, console, _ = start([{"text": [CODE_ANSWER]}])
    await drive(ui, "/save", "show me", "/save", "/save ../../evil.py", "/save")
    saved = tmp_path / "data" / "saved"
    assert "no code block to save" in shown(console)
    assert (saved / "example.py").read_text() == "print('worker')\n"
    assert (saved / "evil.py").exists() and not (tmp_path / "evil.py").exists()  # only the file name counts
    assert (saved / "example-2.py").exists()  # nothing is overwritten


async def test_copy_sends_the_code_to_the_terminal_clipboard(start):
    ui, console, _ = start([{"text": [CODE_ANSWER]}])
    await drive(ui, "/copy", "show me", "/copy")
    text = shown(console)
    assert "no code block to copy" in text
    payload = base64.b64encode(b"print('worker')\n").decode()
    assert f"\x1b]52;c;{payload}\x07" in text


async def test_clear_starts_the_conversation_again(start):
    ui, console, _ = start([SEARCH, {"text": ["an answer [1]"]}])
    await drive(ui, "a question", "/clear", "/sources")
    assert ui.session.conversation.messages == [] and ui.last_answer == ""
    assert "no sources yet" in shown(console)


def test_theme_colors_can_be_changed_with_hex_codes():
    theme = Theme.from_settings({"user": "#ff8800", "assistant": "green", "nonsense": "#123456", "muted": "#12345"})
    default = Theme()
    assert theme.user == "#ff8800"
    assert theme.assistant == default.assistant and theme.muted == default.muted  # not hex codes: ignored


async def test_the_users_colors_reach_the_interface(start, tmp_path):
    ui, console, _ = start([{"text": ["x"]}])
    ui.settings.colors = {"user": "#ff8800"}
    assert ChatUI(ui.session, ui.settings, tmp_path, console).theme.user == "#ff8800"


def test_the_chat_needs_an_indexed_release(tmp_path, words_embedding):
    console = Console(file=io.StringIO(), force_terminal=False)
    assert run_chat(tmp_path, words_embedding, console) == 1
    assert "Nothing is indexed" in shown(console)


def test_the_chat_needs_the_api_key(tmp_path, retriever, words_embedding, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    console = Console(file=io.StringIO(), force_terminal=False)
    assert run_chat(tmp_path, words_embedding, console) == 1  # the retriever fixture indexed tmp_path/index
    assert "ANTHROPIC_API_KEY is not set" in shown(console)


def test_the_live_view_shows_only_the_last_screenful():
    console = Console(file=io.StringIO(), width=60, height=12, force_terminal=False, color_system=None)
    console.print(Tail("\n\n".join(f"Paragraph {i} " + "word " * 5 for i in range(1, 41))))
    shown_lines = console.file.getvalue().splitlines()
    assert len(shown_lines) <= 9  # the screen is 12 lines high, and the live view must leave room
    assert any("Paragraph 40" in line for line in shown_lines)
    assert not any("Paragraph 1 " in line for line in shown_lines)


async def test_a_long_answer_is_printed_in_full_exactly_once(start):
    pieces = [f"Paragraph {i} says something about featherweight.\n\n" for i in range(1, 41)]
    ui, console, _ = start([{"text": pieces}])
    await drive(ui, "tell me a lot")
    text = shown(console)
    for number in (1, 20, 40):
        assert text.count(f"Paragraph {number} says") == 1  # a repainting live view would repeat them


async def test_text_before_a_search_is_kept_once_and_the_answer_after_it_too(start):
    ui, console, _ = start([{"text": ["Let me look that up.\n\n"]}, {"text": ["Second part."]}])
    await drive(ui, "go")
    assert shown(console).count("Let me look that up.") == 1
