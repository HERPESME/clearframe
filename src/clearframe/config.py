"""Environment-driven configuration and mode selection."""

from typing import Literal, Mapping

from pydantic import BaseModel


class ClearFrameConfig(BaseModel):
    mode: Literal["demo", "live"]
    project: str | None
    location: str
    parallel_api_key: str | None
    gemini_model: str
    territories: list[str] = []

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ClearFrameConfig":
        return cls(
            mode="live" if env.get("CLEARFRAME_MODE") == "live" else "demo",
            project=env.get("GOOGLE_CLOUD_PROJECT"),
            location=env.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
            parallel_api_key=env.get("PARALLEL_API_KEY"),
            gemini_model=env.get("CLEARFRAME_GEMINI_MODEL", "gemini-3-pro-preview"),
            territories=[
                t.strip().upper()
                for t in env.get("CLEARFRAME_TERRITORIES", "US").split(",")
                if t.strip()
            ],
        )


def validate_live(cfg: ClearFrameConfig) -> list[str]:
    """Return the env var names still required before live mode can run."""
    missing = []
    if not cfg.project:
        missing.append("GOOGLE_CLOUD_PROJECT")
    if not cfg.parallel_api_key:
        missing.append("PARALLEL_API_KEY")
    return missing
