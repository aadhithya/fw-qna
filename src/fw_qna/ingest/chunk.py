"""Split a release into chunks (LlamaIndex nodes).

Pages are split at headings by LlamaIndex, then packed to about ``MAX_CHARS`` at paragraph boundaries.
A fenced code block is never split, even when it is longer than the limit. A section under ``MIN_CHARS``
joins its neighbour. The changelog gives one chunk per release, and each example directory one chunk.

The text that is embedded is ``title: <breadcrumb> (<layer>) | text: <content>``, the format the model was
trained on. Every other piece of metadata is kept with the node but is not embedded.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.core.schema import TextNode

from .clean import CODE_MARKER, clean_changelog, clean_page, github_anchor

MAX_CHARS = 1500
MIN_CHARS = 200
EXAMPLE_MAX_CHARS = 12000  # a bigger example directory is a whole app: its README stands for it
EXCLUDED = (  # how to maintain featherweight, or noise
    "docs/releasing.md",
    "docs/development.md",
    "docs/book/SUMMARY.md",
    "docs/book/STYLE.md",
    "docs/book/code/",  # chapters carry their code; the files are linked from the chapter's chunks
)
EMBED_TEMPLATE = "title: {metadata_str} | text: {content}"


@dataclass
class Piece:
    """A chunk before it becomes a node."""

    text: str
    path: str
    title: str
    layer: str
    headings: list[str] = field(default_factory=list)
    code_paths: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    is_directory: bool = False


def layer_of(path: str) -> str:
    if path.startswith("docs/book/"):
        return "book"
    if path.startswith("docs/specs/"):
        return "spec"
    if path.startswith("docs/"):
        return "guide"
    if path.startswith("examples/"):
        return "example"
    return "changelog"


def blocks(text: str) -> list[str]:
    """Paragraphs: split at blank lines, but never inside a fenced code block."""
    out: list[str] = []
    current: list[str] = []
    fenced = False
    for line in text.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
        if not line.strip() and not fenced:
            if current:
                out.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        out.append("\n".join(current))
    return out


def pack(text: str) -> list[str]:
    """Fill chunks with paragraphs up to MAX_CHARS. A code block stays whole, even when it is longer."""
    if len(text) <= MAX_CHARS:
        return [text]
    parts: list[str] = []
    for block in blocks(text):
        if len(block) > MAX_CHARS and not block.startswith("```"):
            parts += block.split("\n")  # a long table or list: split by rows
        else:
            parts.append(block)
    chunks: list[str] = []
    current = ""
    for part in parts:
        if current and len(current) + len(part) + 2 > MAX_CHARS:
            chunks.append(current)
            current = part
        else:
            current = f"{current}\n\n{part}" if current else part
    if current:
        chunks.append(current)
    return chunks


def merge_small(pieces: list[Piece]) -> list[Piece]:
    """Join a piece under MIN_CHARS to the next piece of the same page, or to the previous one at the end."""
    out: list[Piece] = []
    carry: Piece | None = None
    for piece in pieces:
        if carry is not None:
            if carry.path == piece.path:
                piece.text = f"{carry.text}\n\n{piece.text}"
                piece.code_paths = carry.code_paths + piece.code_paths
            else:  # the carried piece was the last of its page
                _join_to_previous(out, carry)
            carry = None
        if len(piece.text) < MIN_CHARS:
            carry = piece
        else:
            out.append(piece)
    if carry is not None:
        _join_to_previous(out, carry)
    return out


def _join_to_previous(out: list[Piece], small: Piece) -> None:
    if out and out[-1].path == small.path:
        out[-1].text += f"\n\n{small.text}"
        out[-1].code_paths += small.code_paths
    else:  # a page that is all small: keep it as it is
        out.append(small)


def page_pieces(root: Path) -> list[Piece]:
    documents = []
    for path in sorted(root.glob("docs/**/*.md")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(EXCLUDED):
            continue
        text = clean_page(path.read_text())
        title = next((m.group(1) for m in re.finditer(r"^# (.+)$", text, re.M)), path.stem)
        documents.append(Document(text=text, metadata={"path": rel, "title": title}))
    pieces: list[Piece] = []
    for node in MarkdownNodeParser().get_nodes_from_documents(documents):
        headings = [h for h in node.metadata.get("header_path", "/").strip("/").split("/") if h]
        own = re.match(r"#{1,6} (.+)", node.text.lstrip())  # the section's own heading is in its text
        if own and own.group(1) not in headings:
            headings.append(own.group(1))
        path = node.metadata["path"]
        code_paths = [f"docs/book/{m}" for m in CODE_MARKER.findall(node.text)]
        text = CODE_MARKER.sub("", node.text).strip()
        for chunk in pack(text):
            pieces.append(
                Piece(chunk, path, node.metadata["title"], layer_of(path), list(headings), code_paths)
            )
            code_paths = []  # the link belongs to the first chunk of the section
    return merge_small(pieces)


def changelog_pieces(root: Path) -> list[Piece]:
    path = root / "CHANGELOG.md"
    if not path.is_file():
        return []
    entries = re.split(r"(?m)^(?=## \d)", clean_changelog(path.read_text()))
    pieces = []
    for entry in entries:
        match = re.match(r"## (\d+\.\d+\.\d+)", entry)
        if match:
            heading = entry.splitlines()[0].removeprefix("## ")
            pieces.append(
                Piece(
                    entry.strip(),
                    "CHANGELOG.md",
                    "Changelog",
                    "changelog",
                    [heading],
                    extra={"release": match.group(1)},
                )
            )
    return pieces


def example_pieces(root: Path) -> list[Piece]:
    examples = root / "examples"
    if not examples.is_dir():
        return []
    pieces = []
    for directory in sorted(p for p in examples.iterdir() if p.is_dir()):
        readme = directory / "README.md"
        files = ([readme] if readme.is_file() else []) + sorted(
            f
            for f in directory.rglob("*")
            if f.suffix in (".py", ".md") and f != readme and "samples" not in f.relative_to(directory).parts
        )
        parts = []
        for file in files:
            body = file.read_text().strip()
            name = file.relative_to(directory).as_posix()
            if file == readme:
                parts.append(body)
            elif file.suffix == ".py":
                parts.append(f"### {name}\n\n```python\n{body}\n```")
            else:
                parts.append(f"### {name}\n\n{body}")
        text = "\n\n".join(parts)
        if len(text) > EXAMPLE_MAX_CHARS and readme.is_file():
            more = len(files) - 1
            text = f"{readme.read_text().strip()}\n\n(The source, {more} more files, is in the directory.)"
        if text:
            pieces.append(
                Piece(
                    text,
                    f"examples/{directory.name}",
                    f"Example: {directory.name}",
                    "example",
                    is_directory=True,
                )
            )
    return pieces


def to_nodes(pieces: list[Piece], tag: str, repo_url: str) -> list[TextNode]:
    nodes = []
    counts: dict[str, int] = {}
    for piece in pieces:
        index = counts[piece.path] = counts.get(piece.path, -1) + 1
        leaf = piece.headings[-1] if piece.headings else ""
        kind = "tree" if piece.is_directory else "blob"
        url = f"{repo_url}/{kind}/{tag}/{piece.path}"
        if leaf and leaf != piece.title:
            url += f"#{github_anchor(leaf)}"
        breadcrumb = " > ".join([piece.title, *[h for h in piece.headings if h != piece.title]])
        node_id = hashlib.sha1(f"{tag}|{piece.path}|{index}".encode()).hexdigest()[:16]
        metadata = {
            "version": tag,
            "layer": piece.layer,
            "title": piece.title,
            "breadcrumb": breadcrumb,
            "embed_title": f"{breadcrumb} ({piece.layer})",
            "path": piece.path,
            "url": url,
            "code_paths": piece.code_paths,
            **piece.extra,
        }
        node = TextNode(
            id_=node_id,
            text=piece.text,
            metadata=metadata,
            text_template=EMBED_TEMPLATE,
            metadata_template="{value}",
            metadata_separator=" ",
        )
        node.excluded_embed_metadata_keys = [k for k in metadata if k != "embed_title"]
        node.excluded_llm_metadata_keys = ["embed_title", "prev_id", "next_id"]
        nodes.append(node)
    for before, after in zip(nodes, nodes[1:], strict=False):  # neighbours on the same page
        if before.metadata["path"] == after.metadata["path"]:
            before.metadata["next_id"], after.metadata["prev_id"] = after.node_id, before.node_id
            before.excluded_embed_metadata_keys.append("next_id")
            after.excluded_embed_metadata_keys.append("prev_id")
    return nodes
