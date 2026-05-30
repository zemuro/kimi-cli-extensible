"""Tests for GitSnapshot."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kimi_cli.do.git_snapshot import GitSnapshot, GitSnapshotError


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


def test_git_snapshot_detects_repo(temp_repo: Path) -> None:
    git = GitSnapshot(temp_repo)
    assert git.is_repo is True

    non_repo = temp_repo.parent / "non_repo"
    non_repo.mkdir()
    git2 = GitSnapshot(non_repo)
    assert git2.is_repo is False


def test_git_snapshot_stash_and_pop(temp_repo: Path) -> None:
    git = GitSnapshot(temp_repo)

    # Create a tracked file and commit it
    (temp_repo / "tracked.txt").write_text("hello")
    subprocess.run(["git", "add", "tracked.txt"], cwd=temp_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=temp_repo,
        check=True,
        capture_output=True,
    )

    # Modify the file
    (temp_repo / "tracked.txt").write_text("world")

    state = git.capture_state()
    assert state.has_uncommitted_changes is True

    stash_ref = git.stash("test-stash")
    assert stash_ref is not None

    state2 = git.capture_state()
    assert state2.has_uncommitted_changes is False

    ok = git.pop(stash_ref)
    assert ok is True

    state3 = git.capture_state()
    assert state3.has_uncommitted_changes is True
    assert (temp_repo / "tracked.txt").read_text() == "world"


def test_git_snapshot_commit(temp_repo: Path) -> None:
    git = GitSnapshot(temp_repo)

    (temp_repo / "file.txt").write_text("content")
    subprocess.run(["git", "add", "file.txt"], cwd=temp_repo, check=True, capture_output=True)

    commit_hash = git.commit("test commit")
    assert commit_hash is not None
    assert len(commit_hash) > 0

    # Nothing to commit should return None
    commit_hash2 = git.commit("empty commit")
    assert commit_hash2 is None


def test_git_snapshot_start_session_stashes_dirty(temp_repo: Path) -> None:
    git = GitSnapshot(temp_repo)

    # Create tracked file and commit
    (temp_repo / "a.txt").write_text("a")
    subprocess.run(["git", "add", "a.txt"], cwd=temp_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=temp_repo,
        check=True,
        capture_output=True,
    )

    # Make it dirty
    (temp_repo / "a.txt").write_text("b")

    state = git.start_session("session-123")
    assert state.has_uncommitted_changes is True  # returned state is pre-stash
    assert git._initial_stash is not None
    post_state = git.capture_state()
    assert post_state.has_uncommitted_changes is False  # stashed


def test_git_snapshot_abort_pops_stash(temp_repo: Path) -> None:
    git = GitSnapshot(temp_repo)

    # Create tracked file and commit
    (temp_repo / "a.txt").write_text("a")
    subprocess.run(["git", "add", "a.txt"], cwd=temp_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=temp_repo,
        check=True,
        capture_output=True,
    )

    (temp_repo / "a.txt").write_text("b")
    git.start_session("session-123")

    ok = git.abort_session()
    assert ok is True
    assert (temp_repo / "a.txt").read_text() == "b"  # pre-session dirty state restored
