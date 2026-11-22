"""The ``fw-qna`` command line."""

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import resolve_data_dir, write_user_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fw-qna", description="Ask questions about the featherweight docs.")
    parser.add_argument("--version", action="version", version=f"fw-qna {__version__}")
    parser.add_argument("--data-dir", help="where the index and models live (overrides FW_QNA_HOME)")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="choose and create the data directory")
    init.add_argument("path", nargs="?", help="the data directory (default: the current setting)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        data_dir = Path(args.path).expanduser() if args.path else resolve_data_dir(args.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        config = write_user_config(data_dir)
        print(f"Data directory: {data_dir}\nRemembered in:  {config}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
