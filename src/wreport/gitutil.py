"""Git integration for `wreport sync`.

Kept intentionally dumb: stage the files this tool owns, commit with a message, push to
origin. No rebasing, no force, no branch surgery -- if the push fails the user is told
and nothing has been rewritten.
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional, Tuple


def _run(args: List[str], cwd: str) -> Tuple[int, str]:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def is_repo(repo_root: str) -> bool:
    code, _ = _run(["git", "rev-parse", "--is-inside-work-tree"], repo_root)
    return code == 0


def remote_url(repo_root: str) -> Optional[str]:
    code, out = _run(["git", "remote", "get-url", "origin"], repo_root)
    return out if code == 0 else None


def has_commits(repo_root: str) -> bool:
    code, _ = _run(["git", "rev-parse", "HEAD"], repo_root)
    return code == 0


def status_porcelain(repo_root: str) -> List[str]:
    _, out = _run(["git", "status", "--porcelain"], repo_root)
    return [l for l in out.split("\n") if l.strip()]


def stage(repo_root: str, paths: List[str]) -> None:
    for p in paths:
        _run(["git", "add", "--", p], repo_root)


def commit(repo_root: str, message: str) -> Tuple[bool, str]:
    code, out = _run(["git", "commit", "-m", message], repo_root)
    return code == 0, out


def push(repo_root: str, branch: str = "main") -> Tuple[bool, str]:
    code, out = _run(["git", "push", "-u", "origin", branch], repo_root)
    return code == 0, out


def current_branch(repo_root: str) -> str:
    code, out = _run(["git", "branch", "--show-current"], repo_root)
    return out if code == 0 and out else "main"


def last_commit_summary(repo_root: str) -> str:
    code, out = _run(["git", "log", "-1", "--pretty=%h %s"], repo_root)
    return out if code == 0 else ""