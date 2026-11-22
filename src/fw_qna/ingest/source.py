"""Get the files of one featherweight release.

Only release tags (``vX.Y.Z``) are accepted, so an index always matches what was published. A branch name or a
commit hash is refused. The source is a local clone or a git URL.
"""

import io
import re
import subprocess
import tarfile
from pathlib import Path

RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
PATHS = ("docs", "CHANGELOG.md", "examples", "skills")  # what we take; whichever of these the release has


class SourceError(ValueError):
    """The source or the tag cannot be used."""


def check_tag(tag: str) -> str:
    if not RELEASE_TAG.match(tag):
        raise SourceError(f"{tag!r} is not a release tag. Use a tag like v0.1.0, not a branch or a commit.")
    return tag


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)
    except subprocess.CalledProcessError as error:
        raise SourceError(f"git {' '.join(args[:2])} failed: {error.stderr.decode().strip()}") from error
    return done.stdout.decode()


def github_url(remote: str) -> str:
    """The https address of a repository, from an ssh or https remote. Citation links are built from it."""
    remote = remote.strip()
    ssh = re.match(r"^git@([^:]+):(.+?)(\.git)?$", remote)
    if ssh:
        return f"https://{ssh.group(1)}/{ssh.group(2)}"
    return re.sub(r"\.git$", "", remote).rstrip("/")


def export_release(source: str, tag: str, dest: Path) -> str:
    """Write the release's docs, changelog and examples into ``dest``. Return the repository's https URL."""
    check_tag(tag)
    clone = None
    repo = Path(source).expanduser()
    if not repo.is_dir():  # a git URL: fetch only that tag
        clone = dest.parent / f"{dest.name}-clone"
        _git("clone", "--quiet", "--depth", "1", "--branch", tag, source, str(clone))
        repo = clone
    if not _git("tag", "--list", tag, cwd=repo).strip():
        raise SourceError(f"{source} has no tag {tag}")
    present = set(_git("ls-tree", "--name-only", tag, cwd=repo).split("\n"))
    wanted = [p for p in PATHS if p in present]
    if not wanted:
        raise SourceError(f"{tag} has none of {', '.join(PATHS)}")
    archive = subprocess.run(
        ["git", "archive", "--format=tar", tag, "--", *wanted], cwd=repo, capture_output=True, check=True
    ).stdout
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data")
    remote = _git("remote", "get-url", "origin", cwd=repo).strip() if clone is None else source
    return github_url(remote)
