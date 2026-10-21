"""Endpoints the system can run against. All of them are free to use; see ADR 0002."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from investigator.domain.base import DomainModel


class ProviderProfile(DomainModel):
    name: str
    base_url: str
    api_key_env: str | None
    """Environment variable holding the key; ``None`` for endpoints that need none."""
    model: str
    requests_per_minute: float
    temperature: float | None = None
    top_p: float | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)
    structured_output: Literal["json_schema", "json_object"] = "json_schema"
    timeout_s: float = 180.0
    fallback: str | None = None
    """Profile a request goes to when this one still fails after its retries."""


NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

PROFILES = {
    profile.name: profile
    for profile in (
        ProviderProfile(
            name="nvidia",
            base_url=NVIDIA_BASE_URL,
            api_key_env="NVIDIA_API_KEY",
            model="nvidia/nemotron-3-ultra-550b-a55b",
            requests_per_minute=35,
            temperature=1.0,
            top_p=0.95,
            # The model card's medium-effort mode: far fewer reasoning tokens per answer.
            extra_body={"chat_template_kwargs": {"enable_thinking": True, "medium_effort": True}},
            fallback="nvidia-glm",
        ),
        ProviderProfile(
            name="nvidia-glm",
            base_url=NVIDIA_BASE_URL,
            api_key_env="NVIDIA_API_KEY",
            model="z-ai/glm-5.3",
            requests_per_minute=35,
            extra_body={"reasoning_effort": "low"},
        ),
        ProviderProfile(
            name="ollama",
            base_url="http://localhost:11434/v1",
            api_key_env=None,
            model="qwen3:4b",
            requests_per_minute=600,
            structured_output="json_object",
            timeout_s=600.0,
        ),
    )
}


class MissingCredentials(Exception):
    pass


def api_key(
    profile: ProviderProfile,
    environ: Mapping[str, str] = os.environ,
    env_file: Path = Path(".env"),
) -> str:
    """The profile's key from the environment, falling back to ``.env``."""
    if profile.api_key_env is None:
        return "not-needed"
    key = environ.get(profile.api_key_env) or read_env_file(env_file).get(profile.api_key_env)
    if not key:
        raise MissingCredentials(
            f"set {profile.api_key_env} in the environment or in {env_file} to use {profile.name}"
        )
    return key


def read_env_file(path: Path) -> dict[str, str]:
    """``KEY=value`` lines from a ``.env`` file; comments and blank lines are ignored."""
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values
