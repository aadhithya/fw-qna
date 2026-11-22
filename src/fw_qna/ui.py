"""The terminal interface: it renders what a ``ChatSession`` reports, and runs the slash commands.

Everything it prints goes through one Rich console, and the input is a function that is passed in, so the
whole interface can be driven by a test with no terminal.
"""

import asyncio
import base64
import re
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from rich.box import ROUNDED
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from .config import Settings
from .retrieval import SearchError
from .session import Cancelled, ChatSession, Failed, Finished, Searched, Searching, TextDelta
from .theme import Theme

CODE_BLOCK = re.compile(r"```(\w*)[^\n]*\n(.*?)```", re.S)
EXTENSIONS = {"python": "py", "py": "py", "bash": "sh", "sh": "sh", "yaml": "yaml", "json": "json", "toml": "toml"}
HELP = [
    ("/help", "show this list"),
    ("/sources", "every source cited so far in this conversation"),
    ("/version [tag|latest]", "show the indexed releases, or answer from another one"),
    ("/context [tokens]", "show how full the context is, or set its limit"),
    ("/save [name]", "save the last code block from the last answer"),
    ("/copy", "copy the last code block (needs a terminal that supports OSC 52)"),
    ("/clear", "start the conversation again"),
    ("/exit", "leave (Ctrl-D works too)"),
]


@dataclass
class ChatUI:
    session: ChatSession
    settings: Settings
    data_dir: Path
    console: Console
    model_name: str = "claude-haiku-5-5"

    def __post_init__(self) -> None:
        self.theme = Theme.from_settings(self.settings.colors)
        self.last_answer = ""

    # --- the screen -------------------------------------------------------------------------------------

    def banner(self) -> None:
        t = self.theme
        releases = [r.version for r in self.session.retriever.index.releases()]
        current = self.session.doc_search.version or (releases[-1] if releases else "none")
        body = Text()
        body.append("fw-qna", style=f"bold {t.assistant}")
        body.append("  ·  questions and example code for featherweight\n", style=t.muted)
        body.append(f"docs {current}", style=t.accent)
        body.append(f"  ·  {self.model_name}  ·  context limit {self.settings.context_limit:,} tokens\n", style=t.muted)
        body.append("Ask anything about featherweight. ", style="")
        body.append("/help", style=t.accent)
        body.append(" lists the commands, ", style="")
        body.append("Ctrl-C", style=t.accent)
        body.append(" stops an answer.", style="")
        self.console.print(Panel(body, box=ROUNDED, border_style=t.assistant, padding=(0, 2)))

    def user_header(self) -> None:
        self.console.print()
        self.console.print(Rule(Text("You", style=f"bold {self.theme.user}"), align="left", style=self.theme.user))

    def assistant_header(self) -> None:
        t = self.theme
        self.console.print(Rule(Text("fw-qna", style=f"bold {t.assistant}"), align="left", style=t.assistant))

    # --- the loop ---------------------------------------------------------------------------------------

    async def run(self, read: Callable[[], Awaitable[str]]) -> None:
        self.banner()
        while True:
            self.user_header()
            try:
                line = (await read()).strip()
            except EOFError:
                break
            except KeyboardInterrupt:  # Ctrl-C at the prompt only clears the line
                continue
            if not line:
                continue
            if line.startswith("/"):
                if not self.command(line):
                    break
                continue
            await self.turn(line)
        self.console.print(Text("bye", style=self.theme.muted))

    async def turn(self, text: str) -> None:
        t = self.theme
        self.assistant_header()
        status = self.console.status(Text("thinking…", style=t.muted), spinner="dots", spinner_style=t.assistant)
        status_on = False
        live: Live | None = None
        segment = ""
        last_search: Searching | None = None
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, self.session.cancel)  # Ctrl-C stops the answer, not the app
        except (NotImplementedError, RuntimeError, ValueError):
            pass

        def start_status(label: str) -> None:
            nonlocal status_on
            status.update(Text(label, style=t.muted))
            if not status_on:
                status.start()
                status_on = True

        def stop_all() -> None:
            nonlocal status_on, live, segment
            if status_on:
                status.stop()
                status_on = False
            if live is not None:
                live.stop()
                live = None
            segment = ""

        start_status("thinking…")
        try:
            async for event in self.session.ask(text):
                if isinstance(event, Searching):
                    stop_all()
                    last_search = event
                    start_status(self._searching_label(event))
                elif isinstance(event, Searched):
                    if status_on:
                        status.stop()
                        status_on = False
                    self.console.print(Text(f"  {self._searched_line(last_search, event)}", style=t.muted))
                    start_status("thinking…")
                elif isinstance(event, TextDelta):
                    if status_on:
                        status.stop()
                        status_on = False
                    if live is None:
                        live = Live(console=self.console, refresh_per_second=10, vertical_overflow="visible")
                        live.start()
                    segment += event.text
                    live.update(Markdown(segment))
                elif isinstance(event, Finished):
                    stop_all()
                    self.last_answer = event.text
                    self.finished(event)
                elif isinstance(event, Cancelled):
                    stop_all()
                    self.last_answer = event.text
                    self.console.print(Text("\n  stopped. You can correct me, or ask something else.", style=t.muted))
                elif isinstance(event, Failed):
                    stop_all()
                    self.console.print(Text(f"\n  something went wrong: {event.error}", style=t.error))
        finally:
            stop_all()
            try:
                loop.remove_signal_handler(signal.SIGINT)
            except (NotImplementedError, RuntimeError, ValueError):
                pass

    @staticmethod
    def _searching_label(event: Searching) -> str:
        query = event.args.get("query", "")
        where = "the conversation" if event.tool == "search_history" else "the docs"
        keywords = event.args.get("keywords")
        extra = f"  ({', '.join(keywords)})" if keywords else ""
        return f'searching {where}: "{query}"{extra}'

    @staticmethod
    def _searched_line(search: Searching | None, done: Searched) -> str:
        what = "docs" if done.tool != "search_history" else "history"
        query = search.args.get("query", "") if search else ""
        keywords = search.args.get("keywords") if search else None
        extra = f" ({', '.join(keywords)})" if keywords else ""
        noun = "result" if done.count == 1 else "results"
        return f'searched {what}: "{query}"{extra} → {done.count} {noun}'

    def finished(self, done: Finished) -> None:
        t = self.theme
        self.console.print()
        if done.cited:
            self.console.print(Text("Sources", style=f"bold {t.muted}"))
            for citation in done.cited:
                self._print_source(citation)
        if done.unverified:
            numbers = ", ".join(f"[{n}]" for n in done.unverified)
            self.console.print(Text(f"  {numbers} cited, but no search returned it: unverified", style=t.error))
        if done.also_searched:
            numbers = ", ".join(f"[{c.ref}] {c.breadcrumb}" for c in done.also_searched)
            self.console.print(Text(f"  also searched, not cited: {numbers}", style=f"dim {t.muted}"))
        percent = round(100 * done.context_tokens / done.context_limit) if done.context_limit else 0
        line = f"context {done.context_tokens:,} / {done.context_limit:,} tokens ({percent}%)"
        if done.offloaded:
            line += f"  ·  moved {done.offloaded} earlier messages to the archive (the model can search them)"
        self.console.print(Text(line, style=f"dim {t.muted}"))

    def _print_source(self, citation) -> None:
        t = self.theme
        line = Text("  ")
        line.append(f"[{citation.ref}]", style=f"bold {t.accent}")
        line.append(f" {citation.breadcrumb}", style="")
        line.append(f"  ·  {citation.layer} {citation.version}", style=t.muted)
        self.console.print(line)
        self.console.print(Text(f"      ↗ {citation.url}", style=f"dim {t.muted}"))

    # --- the slash commands -----------------------------------------------------------------------------

    def command(self, line: str) -> bool:
        """Run a slash command. Return False when the user asked to leave."""
        name, _, argument = line.partition(" ")
        argument = argument.strip()
        handlers = {
            "/help": self._help,
            "/sources": self._sources,
            "/version": self._version,
            "/context": self._context,
            "/save": self._save,
            "/copy": self._copy,
            "/clear": self._clear,
        }
        if name in ("/exit", "/quit"):
            return False
        handler = handlers.get(name)
        if handler is None:
            self._say(f"unknown command {name}. /help lists them.", self.theme.error)
        else:
            handler(argument)
        return True

    def _say(self, message: str, color: str | None = None) -> None:
        self.console.print(Text(f"  {message}", style=color or self.theme.muted))

    def _help(self, _: str) -> None:
        for name, what in HELP:
            line = Text("  ")
            line.append(f"{name:<24}", style=self.theme.accent)
            line.append(what, style=self.theme.muted)
            self.console.print(line)
        self._say(f"colors can be changed in {self.data_dir / 'settings.json'}")

    def _sources(self, _: str) -> None:
        citations = self.session.doc_search.citations
        if not citations:
            return self._say("no sources yet: nothing has been searched.")
        for citation in citations.values():
            self._print_source(citation)

    def _version(self, argument: str) -> None:
        releases = [r.version for r in self.session.retriever.index.releases()]
        if not argument:
            current = self.session.doc_search.version or f"{releases[-1]} (the latest)"
            return self._say(f"answering from {current}. indexed: {', '.join(releases)}")
        if argument == "latest":
            self.session.doc_search.version = None
            return self._say(f"answering from {releases[-1]}, the latest")
        try:
            version = self.session.retriever.resolve_version(argument)
        except (SearchError, ValueError) as error:
            return self._say(str(error), self.theme.error)
        self.session.doc_search.version = version
        self._say(f"answering from {version}")

    def _context(self, argument: str) -> None:
        if argument:
            try:
                limit = int(argument.replace(",", "").replace("_", ""))
                if limit < 1000:
                    raise ValueError
            except ValueError:
                return self._say("give a number of tokens, at least 1000: /context 20000", self.theme.error)
            self.settings.context_limit = limit
            self.settings.save(self.data_dir)
            self._say(f"context limit set to {limit:,} tokens. Older turns move to the archive at 80%.")
        used = self.session.conversation.context_tokens()
        limit = self.settings.context_limit
        self._say(f"context {used:,} / {limit:,} tokens ({round(100 * used / limit)}%)")

    def _last_block(self) -> tuple[str, str] | None:
        blocks = CODE_BLOCK.findall(self.last_answer)
        return (blocks[-1][0], blocks[-1][1]) if blocks else None

    def _save(self, argument: str) -> None:
        block = self._last_block()
        if block is None:
            return self._say("the last answer has no code block to save.")
        language, code = block
        name = Path(argument).name if argument else f"example.{EXTENSIONS.get(language.lower(), 'txt')}"
        folder = self.data_dir / "saved"
        folder.mkdir(parents=True, exist_ok=True)
        target, number = folder / name, 1
        while target.exists():
            number += 1
            target = folder / f"{Path(name).stem}-{number}{Path(name).suffix}"
        target.write_text(code)
        self._say(f"saved to {target}")

    def _copy(self, _: str) -> None:
        block = self._last_block()
        if block is None:
            return self._say("the last answer has no code block to copy.")
        payload = base64.b64encode(block[1].encode()).decode()
        self.console.file.write(f"\x1b]52;c;{payload}\x07")  # OSC 52: the terminal puts it on the clipboard
        self.console.file.flush()
        self._say("copied, if your terminal supports it (iTerm2, kitty, WezTerm, tmux, VS Code). /save always works.")

    def _clear(self, _: str) -> None:
        self.session.clear()
        self.last_answer = ""
        self.console.clear()
        self.banner()
