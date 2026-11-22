"""The colors of the interface, as hex codes. The defaults are in ``defaults.yaml``; to change one, edit
``<data dir>/config.yaml``:

    colors:
      user: "#ff8800"
"""

from dataclasses import dataclass, field

from .config import DEFAULTS, HEX


def _default(name: str):
    return field(default_factory=lambda: DEFAULTS["colors"][name])


@dataclass(frozen=True)
class Theme:
    user: str = _default("user")  # the "You" header and the prompt
    assistant: str = _default("assistant")  # the "fw-qna" header and the spinner
    muted: str = _default("muted")  # searches, sources, the context line
    accent: str = _default("accent")  # source numbers and commands
    error: str = _default("error")  # failures and citations that cannot be verified

    @classmethod
    def from_settings(cls, colors: dict[str, str] | None) -> "Theme":
        """The default theme with the user's colors on top. A name or a code that is not valid is ignored."""
        valid = {k: v for k, v in (colors or {}).items() if k in cls.__dataclass_fields__ and HEX.match(str(v))}
        return cls(**valid)
