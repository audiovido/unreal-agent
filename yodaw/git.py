"""Git finalization for accepted YODAW mission output."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(slots=True)
class GitResult:
    ok: bool
    branch: str = ""
    commit_sha: str | None = None
    remote: str | None = None
    push_status: str = "not_requested"
    stdout: str = ""
    stderr: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _run(repo: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=timeout)


def _branch(repo: Path) -> str:
    r = _run(repo, "branch", "--show-current")
    return r.stdout.strip()


def verify_base(repo: str | Path) -> dict:
    path = Path(repo).expanduser().resolve()
    root = _run(path, "rev-parse", "--show-toplevel")
    if root.returncode != 0:
        return {"ok": False, "error": root.stderr.strip() or "not a git repository"}
    status = _run(path, "status", "--porcelain", "--untracked-files=all")
    head = _run(path, "rev-parse", "HEAD")
    return {"ok": True, "repo": root.stdout.strip(), "branch": _branch(path), "head": head.stdout.strip(), "dirty": bool(status.stdout.strip()), "changes": status.stdout.splitlines()}


def push_current(repo: str | Path, remote: str = "origin", branch: str | None = None) -> GitResult:
    """Push the current branch without force-updating any remote ref."""
    path = Path(repo).expanduser().resolve()
    base = verify_base(path)
    if not base.get("ok"):
        return GitResult(False, error=base.get("error"))
    branch = branch or base.get("branch", "")
    if not branch:
        return GitResult(False, error="detached HEAD; refusing push")
    remote_check = _run(path, "remote", "get-url", remote)
    if remote_check.returncode != 0:
        return GitResult(False, branch=branch, remote=remote, push_status="no_remote", error="remote not configured")
    pushed = _run(path, "push", remote, branch, timeout=180)
    return GitResult(
        pushed.returncode == 0, branch=branch,
        commit_sha=base.get("head"), remote=remote,
        push_status="pushed" if pushed.returncode == 0 else "failed",
        stdout=pushed.stdout, stderr=pushed.stderr,
        error=None if pushed.returncode == 0 else "push failed; local commit preserved",
    )


def integrate(repo: str | Path, source_branch: str, message: str, push: bool = False, remote: str = "origin") -> GitResult:
    path = Path(repo).expanduser().resolve()
    base = verify_base(path)
    if not base.get("ok"):
        return GitResult(False, error=base.get("error"))
    if not base.get("branch"):
        return GitResult(False, error="detached HEAD; refusing integration")
    # The integration owner must start clean, but existing unrelated changes
    # are never deleted or auto-staged.
    if base.get("dirty"):
        return GitResult(False, branch=base["branch"], error="base worktree is dirty; refusing integration")
    merge = _run(path, "merge", "--no-ff", source_branch, "-m", message, timeout=180)
    if merge.returncode != 0:
        _run(path, "merge", "--abort", timeout=60)
        return GitResult(False, branch=base["branch"], stdout=merge.stdout, stderr=merge.stderr, error="merge failed; merge aborted")
    commit = _run(path, "rev-parse", "HEAD")
    sha = commit.stdout.strip() if commit.returncode == 0 else None
    result = GitResult(True, branch=base["branch"], commit_sha=sha, remote=remote, stdout=merge.stdout, stderr=merge.stderr)
    if push:
        remote_check = _run(path, "remote", "get-url", remote)
        if remote_check.returncode != 0:
            result.ok = False
            result.push_status = "no_remote"
            result.error = "remote not configured"
            return result
        pushed = _run(path, "push", remote, base["branch"], timeout=180)
        result.push_status = "pushed" if pushed.returncode == 0 else "failed"
        result.stdout += pushed.stdout
        result.stderr += pushed.stderr
        if pushed.returncode != 0:
            result.ok = False
            result.error = "push failed; local commit preserved"
    return result
