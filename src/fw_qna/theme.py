"""The colors of the interface, as hex codes. Change any of them in ``<data dir>/settings.json``:

{"colors": {"user": "#ff8800", "assistant": "#00ccaa"}}
"""

import re
from dataclasses import dataclass

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class Theme:
    user: str = "#4cc9f0"  # the "You" header and the prompt
    assistant: str = "#80ed99"  # the "fw-qna" header and the spinner
    muted: str = "#8d99ae"  # searches, sources, the context line
    accent: str = "#f9c74f"  # source numbers and commands
    error: str = "#ef476f"  # failures and citations that cannot be verified

    @classmethod
    def from_settings(cls, colors: dict[str, str] | None) -> "Theme":
        """The default theme with the user's colors on top. A name or a code that is not valid is ignored."""
        valid = {k: v for k, v in (colors or {}).items() if k in cls.__dataclass_fields__ and HEX.match(str(v))}
        return cls(**valid)
