from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class GitHubConfig:
    repository: str
    token: str
    api_url: str = "https://api.github.com"

    @classmethod
    def from_environment(cls) -> "GitHubConfig":
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

    def close(self) -> None:
        self.client.close()
