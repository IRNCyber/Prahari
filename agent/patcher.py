"""Create a constrained local Git branch from a reviewed unified diff."""

from __future__ import annotations

import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from otel.tracing import traced

ROOT = Path(__file__).resolve().parents[1]
MAX_DIFF_BYTES = 64_000
ALLOWED_PATHS = (
    re.compile(r"^(target_app|faults)/[A-Za-z0-9_./-]+\.py$"),
    re.compile(r"^tests/test_[A-Za-z0-9_]+\.py$"),
)


class PatchError(RuntimeError):
    pass


def _git(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise PatchError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result


@traced("agent.patch.create_branch")
def create_patch_branch(diff: str, title: str) -> dict[str, object]:
    if not diff.strip() or len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        raise PatchError("Patch must be non-empty and no larger than 64 KiB.")
    if not diff.startswith(("diff --git ", "--- ")):
        raise PatchError("Only a unified Git diff is accepted.")

    try:
        git_root = Path(_git("rev-parse", "--show-toplevel").stdout.strip()).resolve()
    except PatchError as error:
        raise PatchError("A Git repository must be mounted to create a remediation branch.") from error
    project_prefix = ROOT.relative_to(git_root).as_posix()
    if project_prefix == ".":
        project_prefix = ""
    tracked_source_path = f"{project_prefix}/main.py" if project_prefix else "main.py"
    try:
        tracked_source = _git("ls-files", "--error-unmatch", tracked_source_path, cwd=git_root)
    except PatchError as error:
        raise PatchError("The Prahari project source must be committed to Git before creating a patch branch.") from error
    if not tracked_source.stdout.strip():
        raise PatchError("The Prahari project source must be committed to Git before creating a patch branch.")

    status_path = f"{project_prefix}/" if project_prefix else "."
    status = _git("status", "--porcelain", "--", status_path, cwd=git_root).stdout.strip()
    if status:
        raise PatchError("Refusing to create a patch branch while the repository worktree is dirty.")
    paths = re.findall(r"^diff --git a/(.+?) b/(.+)$", diff, flags=re.MULTILINE)
    if not paths:
        raise PatchError("The unified diff has no Git file headers.")
    relative_paths: list[str] = []
    for old_path, new_path in paths:
        prefix = f"{project_prefix}/" if project_prefix else ""
        if not old_path.startswith(prefix) or not new_path.startswith(prefix) or old_path != new_path:
            raise PatchError(f"Patch path is outside the Prahari project: {new_path}")
        relative_path = new_path.removeprefix(prefix)
        if not any(pattern.fullmatch(relative_path) for pattern in ALLOWED_PATHS):
            raise PatchError(f"Patch path is outside the approved sample-service scope: {relative_path}")
        relative_paths.append(new_path)

    branch = f"prahari/fix-{uuid.uuid4().hex[:10]}"
    worktree_root = Path(tempfile.gettempdir()) / f"prahari-{uuid.uuid4().hex}"
    worktree = worktree_root / project_prefix
    _git("worktree", "add", "-b", branch, str(worktree_root), "HEAD", cwd=git_root)
    try:
        patch_path = worktree_root / ".prahari.patch"
        patch_path.write_text(diff, encoding="utf-8")
        try:
            _git("apply", "--check", str(patch_path), cwd=worktree_root)
            _git("apply", str(patch_path), cwd=worktree_root)
        finally:
            patch_path.unlink(missing_ok=True)

        _git("add", "--", *relative_paths, cwd=worktree_root)
        _git(
            "-c",
            "user.name=Prahari",
            "-c",
            "user.email=prahari@localhost",
            "commit",
            "-m",
            title[:120],
            cwd=worktree_root,
        )
        commit = _git("rev-parse", "HEAD", cwd=worktree_root).stdout.strip()
        return {
            "branch": branch,
            "commit": commit,
            "worktree": str(worktree),
            "changed_files": [path.removeprefix(f"{project_prefix}/" if project_prefix else "") for path in relative_paths],
            "status": "committed_for_isolated_verification",
        }
    except (PatchError, OSError, subprocess.SubprocessError):
        _git("worktree", "remove", "--force", str(worktree_root), cwd=git_root)
        _git("branch", "-D", branch, cwd=git_root)
        raise
