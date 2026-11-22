"""A fake chat model for the agent tests. No real model is ever called."""

import asyncio
import json
from typing import Any, ClassVar

from featherweight import ModelSettings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field


class ScriptedChat(BaseChatModel):
    """Plays one step per model call, in order.

    A step is ``{"tool": (name, args)}``, ``{"text": [pieces]}`` or ``{"error": "message"}``, with an optional
    ``"usage": (input_tokens, output_tokens)``. ``seen`` keeps the messages each call was given.
    """

    steps: list[dict[str, Any]]
    seen: list[Any] = Field(default_factory=list)
    index: int = 0
    pause: float = 0.0  # seconds between the pieces of a text step

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError("the scripted chat only streams")

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        step = self.steps[min(self.index, len(self.steps) - 1)]
        self.index += 1
        self.seen.append(list(messages))
        if "error" in step:
            raise RuntimeError(step["error"])
        tokens, written = step.get("usage", (100, 10))
        usage = {"input_tokens": tokens, "output_tokens": written, "total_tokens": tokens + written}
        if "tool" in step:
            name, args = step["tool"]
            call = {"name": name, "args": json.dumps(args), "id": f"call-{self.index}", "index": 0}
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[call]))
        else:
            for piece in step["text"]:
                if self.pause:
                    await asyncio.sleep(self.pause)
                yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
        yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=usage))


class FakeSettings(ModelSettings):
    """Model settings that build the fake chat model they hold, the way featherweight's own tests do."""

    provider: ClassVar[str] = "fake"
    model: str = "fake-model"
    chat: Any = Field(default=None, exclude=True)

    def build(self):
        return self.chat
