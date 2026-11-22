# fw-qna

A terminal chat app that answers questions about [featherweight](https://github.com/aadhithya/featherweight) from its own documentation, and writes example code for it.

It is also a demonstration: the chat agent is built on featherweight itself.

**Status:** planning. See [docs/PRD.md](docs/PRD.md) for the scope and the design questions we are working through.

## Development

Everything that runs code runs in Docker, so nothing is installed on your machine. You need Docker, `make` and [pre-commit](https://pre-commit.com). There is no CI: the checks run locally, before each commit.

```
make hooks   # once per clone: installs the pre-commit hooks (needs the pre-commit tool)
make check   # lint, format check and tests
make fmt     # fix formatting
```

Commits are [conventional commits](https://www.conventionalcommits.org). Work happens on a branch per issue, in a git worktree (`.worktrees/`).

Where data lives: `--data-dir`, then `FW_QNA_HOME`, then the path remembered by `fw-qna init`, then `~/.fw-qna`.

License: MIT.
