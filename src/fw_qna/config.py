"""Where fw-qna keeps its data, and the settings the user can change (``config.yaml``).

The data directory holds the index and downloaded models, so the user controls it. Found, in order, from:
the ``--data-dir`` flag, the ``FW_QNA_HOME`` environment variable, the user config file written by
``fw-qna init``, and finally ``~/.fw-qna``.
"""

import json
import os
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

DEFAULT_DATA_DIR = Path.home() / ".fw-qna"
CONFIG_FILE = "config.yaml"
MIN_CONTEXT_LIMIT = 1000
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
CONTEXT_LINE = re.compile(r"^context_limit:.*$", re.M)


def default_text() -> str:
    """The defaults file that ships with the package, comments included."""
    return (resources.files("fw_qna") / "defaults.yaml").read_text()


DEFAULTS = yaml.safe_load(default_text())  # the one place the default values live
DEFAULT_CONTEXT_LIMIT = DEFAULTS["context_limit"]


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


class ConfigError(ValueError):
    """The user's config.yaml cannot be read."""


@dataclass
class Settings:
    """The settings, read from ``<data dir>/config.yaml`` on top of the defaults that ship with the package.

    A value that is missing, or is not valid, falls back to its default. Colors the user did not set keep theirs.
    """

    context_limit: int = DEFAULTS["context_limit"]
    colors: dict[str, str] = field(default_factory=lambda: dict(DEFAULTS["colors"]))

    @classmethod
    def load(cls, data_dir: Path) -> "Settings":
        path = data_dir / CONFIG_FILE
        user: dict = {}
        if path.is_file():
            try:
                loaded = yaml.safe_load(path.read_text())
            except yaml.YAMLError as error:
                raise ConfigError(f"{path} is not valid YAML: {error}") from error
            user = loaded if isinstance(loaded, dict) else {}
        limit = user.get("context_limit")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < MIN_CONTEXT_LIMIT:
            limit = DEFAULTS["context_limit"]
        wanted = user.get("colors") if isinstance(user.get("colors"), dict) else {}
        colors = {
            name: wanted.get(name) if HEX.match(str(wanted.get(name))) else fallback
            for name, fallback in DEFAULTS["colors"].items()
        }
        return cls(limit, colors)

    def save(self, data_dir: Path) -> None:
        """Write the context limit into the user's file. Only that line changes, so their comments stay."""
        path = ensure_config_file(data_dir)
        text = path.read_text()
        line = f"context_limit: {self.context_limit}"
        text = CONTEXT_LINE.sub(line, text, count=1) if CONTEXT_LINE.search(text) else f"{line}\n{text}"
        path.write_text(text)


def ensure_config_file(data_dir: Path) -> Path:
    """Make ``<data dir>/config.yaml`` from the shipped defaults if it is not there, and return its path."""
    path = data_dir / CONFIG_FILE
    if not path.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(default_text())
    return path
