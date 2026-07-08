"""Configuration loading from YAML files and env vars."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


load_dotenv()


class ModelConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-5.4-mini"
    temperature: float = 0
    max_output_tokens: int = 1200
    timeout_seconds: int = 60


class AgentConfig(BaseModel):
    max_steps: int = 8
    model: str = "gpt-5.4-mini"
    provider: str = "openai"
    temperature: float = 0
    max_output_tokens: int = 1200
    timeout_seconds: int = 60

    def to_model_config(self) -> ModelConfig:
        return ModelConfig(
            provider=self.provider,
            model=self.model,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            timeout_seconds=self.timeout_seconds,
        )


class DatabaseConfig(BaseModel):
    path: str = "data/duckdb/benchmark.db"


class CacheConfig(BaseModel):
    enabled: bool = False
    memory_items_limit: int = 3


class RunConfig(BaseModel):
    tasks: str = "tasks/small.yaml"
    mode: str = "raw"
    output_dir: str = "reports"
    seed: int = 42


class HarnessConfig(BaseModel):
    run: RunConfig = Field(default_factory=RunConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> HarnessConfig:
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)


def load_config(
    config_path: str | Path | None = None,
    model_override: str | None = None,
    mode: str = "raw",
) -> HarnessConfig:
    """Load config from YAML, applying CLI overrides."""
    base_path = Path("configs/default.yaml")
    if config_path:
        base_path = Path(config_path)

    if base_path.exists():
        config = HarnessConfig.from_yaml(base_path)
    else:
        config = HarnessConfig()

    if model_override:
        config.agent.model = model_override
    if mode:
        config.run.mode = mode

    return config


def get_api_key() -> str:
    """Get OpenAI API key from environment or pass store."""
    key = os.getenv("OPENAI_API_KEY", "")
    if key:
        return key

    # Try pass store
    try:
        import subprocess
        pass_dir = os.path.expanduser("~/.hermes/.password-store")
        env = {**os.environ, "PASSWORD_STORE_DIR": pass_dir}
        result = subprocess.run(
            ["pass", "hermes/openai/api-key"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    return ""
