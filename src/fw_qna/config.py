"""Where fw-qna keeps its data, and the settings the user can change.

The data directory holds the index and downloaded models, so the user controls it. Found, in order, from:
the ``--data-dir`` flag, the ``FW_QNA_HOME`` environment variable, the user config file written by
``fw-qna init``, and finally ``~/.fw-qna``.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / ".fw-qna"
DEFAULT_CONTEXT_LIMIT = 100_000  # tokens; change it live with the /context command
SETTINGS_FILE = "settings.json"


def user_config_path(env: dict[str, str] | None = None) -> Path:
    """The small file, outside the data directory, that remembers where the data directory is."""
    env = os.environ if env is None else env
    base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else Path.home() / ".config"
    return base / "fw-qna" / "config.json"


def resolve_data_dir(
    cli_value: str | Path | None = None,
    env: dict[str, str] | None = None,
    config_path: Path | None = None,
) -> Path:
    env = os.environ if env is None else env
    if cli_value:
        return Path(cli_value).expanduser()
    if env.get("FW_QNA_HOME"):
        return Path(env["FW_QNA_HOME"]).expanduser()
    path = config_path or user_config_path(env)
    if path.is_file():
        data_dir = json.loads(path.read_text()).get("data_dir")
        if data_dir:
            return Path(data_dir).expanduser()
    return DEFAULT_DATA_DIR


def write_user_config(data_dir: Path, config_path: Path | None = None) -> Path:
    path = config_path or user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"data_dir": str(data_dir)}, indent=2) + "\n")
    return path


@dataclass
class Settings:
    """Settings kept in ``<data dir>/settings.json``, so they survive between sessions."""

    context_limit: int = DEFAULT_CONTEXT_LIMIT
    colors: dict[str, str] = field(default_factory=dict)  # hex codes that replace the theme's, by name

    @classmethod
    def load(cls, data_dir: Path) -> "Settings":
        path = data_dir / SETTINGS_FILE
        if not path.is_file():
            return cls()
        known = {k: v for k, v in json.loads(path.read_text()).items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / SETTINGS_FILE).write_text(json.dumps(asdict(self), indent=2) + "\n")
