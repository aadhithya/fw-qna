"""The skills of a release, kept next to the index.

A featherweight release has its own skill (``skills/featherweight``: instructions for building with that release).
Ingestion copies it from the same tag as the docs, so the two always match:

    <data dir>/skills/<tag>/<skill name>/SKILL.md ...
    <data dir>/skills/<tag>/source.json            where it came from, for links to the files

The chat gives the skills of the release it answers from to its agent.
"""

import json
import logging
import shutil
from pathlib import Path

from featherweight import Skill

from .ingest.source import check_tag

SOURCE_FILE = "source.json"
log = logging.getLogger(__name__)


def skills_root(data_dir: Path, tag: str) -> Path:
    return data_dir / "skills" / check_tag(tag)  # the tag is checked, so it cannot point outside the data dir


def install_skills(exported: Path, data_dir: Path, tag: str, repo_url: str) -> list[str]:
    """Copy the skills of an exported release into the data directory, replacing any earlier copy.

    Return the names of the skills installed. A release with no skills installs none.
    """
    source = exported / "skills"
    names = sorted(p.name for p in source.iterdir() if (p / "SKILL.md").is_file()) if source.is_dir() else []
    target = skills_root(data_dir, tag)
    shutil.rmtree(target, ignore_errors=True)  # a fresh copy: nothing from an earlier ingest stays behind
    if not names:
        return []
    for name in names:
        shutil.copytree(source / name, target / name)
    (target / SOURCE_FILE).write_text(json.dumps({"repo_url": repo_url, "tag": tag}, indent=2) + "\n")
    return names


def installed_skills(data_dir: Path, tag: str) -> list[str]:
    root = skills_root(data_dir, tag)
    return sorted(p.name for p in root.iterdir() if (p / "SKILL.md").is_file()) if root.is_dir() else []


def remove_skills(data_dir: Path, tag: str) -> bool:
    """Remove a release's skills. Return whether there were any."""
    root = skills_root(data_dir, tag)
    existed = root.is_dir()
    shutil.rmtree(root, ignore_errors=True)
    return existed


def skill_source(data_dir: Path, tag: str) -> dict[str, str] | None:
    """Where a release's skills came from: ``{"repo_url": ..., "tag": ...}``, for links to their files."""
    path = skills_root(data_dir, tag) / SOURCE_FILE
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def load_skills(data_dir: Path, tag: str) -> list[Skill]:
    """The release's skills, ready to give to an agent. A skill that cannot be loaded is skipped, and logged."""
    skills = []
    for name in installed_skills(data_dir, tag):
        try:
            skills.append(Skill.from_directory(skills_root(data_dir, tag) / name))
        except ValueError as error:  # featherweight's SkillError and ValidationError are both ValueErrors
            log.warning("skill %s of %s was not loaded: %s", name, tag, error)
    return skills
