import subprocess
from pathlib import Path

import pytest

BADGE = "[![docs for](https://img.shields.io/badge/x)](https://pypi.org/)"
NAV = f"<!-- nav:top -->\n[Book](../README.md) › Page  {BADGE}\n<!-- /nav:top -->\n\n"
GUIDE = (
    NAV
    + """# Agents

An agent is a typed class.

## Defining an agent

An agent is a subclass of `AgentBase`, with Pydantic models for its input and output.

```python
class Agent(AgentBase):
    name: str = "x"

    def check_output(self, agent_input, output):
        pass
```

## Short

Tiny.
"""
)
BOOK = (
    NAV
    + """# Install and set up

Get it running.

<!-- code: code/1-1/app.py -->
```python
print("hello")
```

"""
    + "A paragraph that explains the chapter in some detail. " * 8
)
CHANGELOG = """# Changelog

## 0.2.0 (2026-12-01)

### Features

* a new thing ([abcdef1](https://github.com/o/r/commit/abcdef1234567890))
* another thing ([1234567](https://github.com/o/r/commit/1234567abcdef000)), closes [#12](https://github.com/o/r/issues/12)

## 0.1.0 (2026-11-20)

### Features

* the first thing ([7654321](https://github.com/o/r/commit/7654321fedcba000))
"""


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def git(cwd: Path, *args: str) -> None:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "HOME": str(cwd),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture
def release_tree(tmp_path_factory) -> Path:
    """A tree shaped like a featherweight release."""
    root = tmp_path_factory.mktemp("tree")
    write(root, "docs/agents.md", GUIDE)
    write(root, "docs/releasing.md", "# Releasing\n\nHow to cut a release. " * 20)
    write(root, "docs/book/01-start/01-install.md", BOOK)
    write(root, "docs/book/SUMMARY.md", "# Summary\n")
    write(root, "docs/book/code/1-1/app.py", 'print("hello")\n')
    write(root, "docs/specs/runner.md", "# Spec: runner\n\n" + "The runner runs agents with retries. " * 10)
    write(root, "CHANGELOG.md", CHANGELOG)
    write(root, "examples/jobs/README.md", "# Jobs\n\nRun a job on a worker.\n")
    write(root, "examples/jobs/run.py", "print('run')\n")
    write(root, "examples/bigapp/README.md", "# Big app\n\nA whole application.\n")
    for i in range(14):
        write(root, f"examples/bigapp/mod{i}.py", "x = 1\n" * 400)
    write(root, "examples/jobs/samples/data.md", "# Sample\n\nnot an example\n")
    return root


@pytest.fixture
def repo(release_tree) -> Path:
    """A git repository with that tree, tagged v0.1.0."""
    git(release_tree, "init", "-q", "-b", "main")
    git(release_tree, "remote", "add", "origin", "git@github.com:acme/widget.git")
    git(release_tree, "add", "-A")
    git(release_tree, "commit", "-q", "-m", "initial")
    git(release_tree, "tag", "v0.1.0")
    return release_tree
