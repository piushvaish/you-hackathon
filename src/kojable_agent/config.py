"""Centralized, root-level configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict


DEMO_QUESTION = "Which is better for AI agent web search, You.com or Exa?"
SEARCH_QUERIES: tuple[tuple[str, str], ...] = (
    ("You.com AI agent web search API", "you.com"),
    ("Exa AI agent web search API", "exa"),
    ("You.com Exa comparison AI agent search pricing", "comparison"),
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing."""


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    root: Path
    ydc_api_key: str | None = None
    daytona_api_key: str | None = None
    one_secret: str | None = None

    @classmethod
    def load(
        cls,
        root: Path | None = None,
        environ: Mapping[str, str] | None = None,
        *,
        require_credentials: bool = True,
    ) -> "Settings":
        resolved_root = (root or repository_root()).resolve()
        file_values = {
            key: value
            for key, value in dotenv_values(resolved_root / ".env").items()
            if value is not None
        }
        environment = dict(os.environ if environ is None else environ)
        values = {**file_values, **environment}
        settings = cls(
            root=resolved_root,
            ydc_api_key=_clean(values.get("YDC_API_KEY")),
            daytona_api_key=_clean(values.get("DAYTONA_API_KEY")),
            one_secret=_clean(values.get("ONE_SECRET")),
        )
        if require_credentials:
            settings.require_runtime_credentials()
        return settings

    @property
    def output_path(self) -> Path:
        return self.root / "data" / "run_1.json"

    @property
    def data_directory(self) -> Path:
        return self.root / "data"

    def require_runtime_credentials(self) -> None:
        missing = []
        if not self.ydc_api_key:
            missing.append("YDC_API_KEY")
        if not self.daytona_api_key:
            missing.append("DAYTONA_API_KEY")
        if missing:
            joined = " and ".join(missing)
            raise ConfigurationError(
                f"Missing {joined}.\n\nAdd it to:\n{self.root / '.env'}"
            )


def _clean(value: str | None) -> str | None:
    stripped = value.strip() if value else ""
    return stripped or None
