import shutil
import subprocess
from pathlib import Path

import pytest

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
needs_ruff = pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not installed")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo, check=True, capture_output=True,
    )  # fmt: skip


@pytest.fixture
def make_repo(tmp_path):
    """Create a tiny git repository with the given files and one commit."""

    def _make(files: dict[str, str]) -> Path:
        for name, content in files.items():
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-qm", "init")
        return tmp_path

    return _make
