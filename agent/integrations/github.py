from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True)
class GitHubConfig:
    repository: str
    token: str
    api_url: str = "https://api.github.com"

    @classmethod
    def from_environment(cls) -> GitHubConfig:
        repository = os.getenv("GITHUB_REPOSITORY", "")
        token = os.getenv("GITHUB_TOKEN", "")
        if not repository or not token:
            raise RuntimeError("GITHUB_REPOSITORY and GITHUB_TOKEN must be configured.")
        repository = repository.removesuffix(".git").rstrip("/")
        if repository.startswith("https://github.com/"):
            repository = repository.removeprefix("https://github.com/")
        if repository.startswith("git@github.com:"):
            repository = repository.removeprefix("git@github.com:")
        return cls(repository, token, os.getenv("GITHUB_API_URL", "https://api.github.com"))


class GitHubClient:
    def __init__(self, config: GitHubConfig) -> None:
        self.config = config
        self.client = httpx.Client(
            base_url=config.api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {config.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )

    def validate(self) -> dict[str, object]:
        identity = self.client.get("/user")
        identity.raise_for_status()
        repository = self.client.get(f"/repos/{self.config.repository}")
        repository.raise_for_status()
        data = repository.json()
        return {
            "authenticated": True,
            "repository": self.config.repository,
            "permissions": data.get("permissions", {}),
            "default_branch": data.get("default_branch"),
        }

    def create_pull_request(self, branch: str, title: str, body: str) -> dict[str, object]:
        if not re.fullmatch(r"prahari/fix-[a-f0-9]{10}", branch):
            raise ValueError("Only a Prahari-generated remediation branch can open a pull request.")
        repository = self.client.get(f"/repos/{self.config.repository}")
        repository.raise_for_status()
        default_branch = repository.json().get("default_branch")
        if not default_branch:
            raise RuntimeError("GitHub repository did not report its default branch.")
        response = self.client.post(
            f"/repos/{self.config.repository}/pulls",
            json={"title": title[:250], "body": body[:60_000], "head": branch, "base": default_branch},
        )
        response.raise_for_status()
        data = response.json()
        return {"number": data["number"], "url": data["html_url"], "state": data["state"], "base": default_branch}

    def push_branch(self, branch: str, worktree: str) -> None:
        path = Path(worktree).resolve()
        temp_root = Path(__import__("tempfile").gettempdir()).resolve()
        if temp_root not in path.parents or not (path.parent / ".git").exists():
            raise ValueError("Refusing to push a path that is not a generated Prahari worktree.")
        actual_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        if actual_branch != branch:
            raise ValueError("The worktree branch does not match the approved branch.")
        subprocess.run(["git", "push", "--set-upstream", "origin", branch], cwd=path, check=True, timeout=120)

    def close(self) -> None:
        self.client.close()
