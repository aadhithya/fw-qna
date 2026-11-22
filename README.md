# fw-qna

A terminal chat app that answers questions about [featherweight](https://github.com/aadhithya/featherweight) from its own documentation, and writes example code for it.

It is also a demonstration: the chat agent is built on featherweight itself.

**Status:** planning. See [docs/PRD.md](docs/PRD.md) for the scope and the design questions we are working through.

## Development

```
uv venv --python 3.13 && uv pip install -e . pytest ruff
.venv/bin/pytest
.venv/bin/ruff check src tests
```

Where data lives: `--data-dir`, then `FW_QNA_HOME`, then the path remembered by `fw-qna init`, then `~/.fw-qna`.

License: MIT.
