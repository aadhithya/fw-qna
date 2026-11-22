# fw-qna

A terminal chat app that answers questions about [featherweight](https://github.com/aadhithya/featherweight) from its own documentation, and writes example code for it.

It is also a demonstration: the chat agent is built on featherweight itself.

**Status:** under construction. See [docs/PRD.md](docs/PRD.md) for the scope and the decisions behind it.

## Run it

Everything runs in Docker Compose, driven by `make`. You need Docker and `make`.

```
make up                                  # start Ollama and pull the embedding model (once)
make ingest REF=v0.1.0                   # index a release; SOURCE=<clone path or git URL>, default ../featherweight
make versions                            # what is indexed
make drop REF=v0.1.0                     # remove a release
make search Q="how do I define an agent"  # try the search, with no chat model (ARGS="--keywords JobWorker")
make chat                                # the chat; needs ANTHROPIC_API_KEY in your shell or in a .env file
make check-embeddings                    # check the real model gives sane vectors
```

Only release tags (`vX.Y.Z`) are indexed. The index and the Ollama models live in `./data`, or in the directory set by
`FW_QNA_DATA`, so you control where they are. Ingesting the whole `v0.1.0` takes about two minutes on a laptop CPU, and
running it again with nothing changed takes a few seconds.

Copy `.env.example` to `.env` and put your Anthropic key in it, or export `ANTHROPIC_API_KEY`. The chat model is Claude Haiku 5.5.

In the chat: `/help` lists the commands (`/sources`, `/version`, `/context`, `/save`, `/copy`, `/clear`, `/exit`), and Ctrl-C
stops an answer. Saved code goes to `saved/` in your data directory. The colors are hex codes you can change in
`settings.json` in the data directory: `{"colors": {"user": "#ff8800", "assistant": "#00ccaa"}}`; the names are `user`,
`assistant`, `muted`, `accent` and `error`.

If `make up` says the model needs a newer Ollama, run `docker compose pull ollama`; `make up` does this for you.

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
