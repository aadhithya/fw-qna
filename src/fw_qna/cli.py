"""The ``fw-qna`` command line."""

import argparse
import os
import sys
from pathlib import Path

from llama_index.core.base.embeddings.base import BaseEmbedding

from . import __version__
from .config import ConfigError, resolve_data_dir, write_user_config
from .embedder import EmbeddingError, OllamaGemmaEmbedding
from .index import Index
from .ingest import SourceError, ingest_release
from .retrieval import LAYERS, Retriever, SearchError

DEFAULT_OLLAMA_URL = "http://localhost:11434"


def make_embedder() -> BaseEmbedding:
    """The embedding model. Ollama's address comes from FW_QNA_OLLAMA_URL (in Docker, the ollama service)."""
    return OllamaGemmaEmbedding(base_url=os.environ.get("FW_QNA_OLLAMA_URL", DEFAULT_OLLAMA_URL))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fw-qna", description="Ask questions about the featherweight docs.")
    parser.add_argument("--version", action="version", version=f"fw-qna {__version__}")
    parser.add_argument("--data-dir", help="where the index and models live (overrides FW_QNA_HOME)")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="choose and create the data directory")
    init.add_argument("path", nargs="?", help="the data directory (default: the current setting)")
    ingest = commands.add_parser("ingest", help="index one release of the featherweight docs")
    ingest.add_argument("--source", required=True, help="a local clone or a git URL of featherweight")
    ingest.add_argument("--ref", required=True, help="a release tag, like v0.1.0 (branches are refused)")
    ingest.add_argument("--repo-url", help="the https address for citation links")
    ingest.add_argument("--force", action="store_true", help="embed again even if nothing changed")
    commands.add_parser("versions", help="list the indexed releases")
    commands.add_parser("chat", help="chat about the featherweight docs in the terminal")
    search = commands.add_parser("search", help="search the docs and print what comes back (no model)")
    search.add_argument("query")
    search.add_argument("--keywords", nargs="*", help="exact code names to match")
    search.add_argument("--layer", choices=LAYERS)
    search.add_argument("--version", help="a release tag; the default is the latest indexed one")
    search.add_argument("--top-k", type=int, default=5)
    drop = commands.add_parser("drop", help="remove one release from the index")
    drop.add_argument("ref", help="the release tag, like v0.1.0")
    return parser


def index_path(data_dir: Path) -> Path:
    return data_dir / "index"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = resolve_data_dir(args.data_dir)
    try:
        return run(args, data_dir)
    except (SourceError, EmbeddingError, SearchError, ConfigError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def run(args: argparse.Namespace, data_dir: Path) -> int:
    if args.command == "ingest":
        nodes = ingest_release(args.source, args.ref, args.repo_url)
        print(f"{args.ref}: {len(nodes)} chunks")
        outcome = Index(index_path(data_dir), make_embedder()).add_release(args.ref, nodes, force=args.force)
        print("already indexed, nothing changed" if outcome == "unchanged" else "indexed")
    elif args.command == "versions":
        index = Index(index_path(data_dir), make_embedder())
        if not index.releases():
            print("Nothing is indexed yet. Run: fw-qna ingest --source <featherweight> --ref v0.1.0")
        for info in index.releases():
            print(f"{info.version} {info.chunks} chunks  {info.model} {info.dimensions}d {info.ingested_at}")
    elif args.command == "chat":
        from .chat import run_chat  # imported here: the other commands do not need the interface

        return run_chat(data_dir, make_embedder())
    elif args.command == "search":
        retriever = Retriever(Index(index_path(data_dir), make_embedder()))
        hits = retriever.search(
            args.query, keywords=args.keywords, layer=args.layer, version=args.version, top_k=args.top_k
        )
        for number, hit in enumerate(hits, 1):
            print(f"{number}. [{hit.layer}] {hit.breadcrumb}  ({hit.score:.3f})\n   {hit.url}")
            print("   " + hit.text[:160].replace("\n", " "))
        if not hits:
            print("no results")
    elif args.command == "drop":
        removed = Index(index_path(data_dir), make_embedder()).drop(args.ref)
        print(f"removed {args.ref}" if removed else f"{args.ref} is not indexed")
        return 0 if removed else 1
    elif args.command == "init":
        data_dir = Path(args.path).expanduser() if args.path else data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        config = write_user_config(data_dir)
        print(f"Data directory: {data_dir}\nRemembered in:  {config}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
