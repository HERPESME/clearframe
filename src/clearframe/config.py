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
    audd_api_token: str | None = None

    # Where state lives, which is a different question from whether the
    # detectors are real. `mode` picks fixtures or live APIs; `profile` picks a
    # directory or a bucket. All four combinations mean something, and
    # profile=cloud with mode=demo is the one to deploy first: the whole cloud
    # topology, exercised end to end, with no spend attached to it.
    profile: Literal["local", "cloud"] = "local"
    bucket: str | None = None
    tasks_queue: str | None = None
    worker_url: str | None = None
    tasks_sa: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ClearFrameConfig":
        return cls(
            mode="live" if env.get("CLEARFRAME_MODE") == "live" else "demo",
            project=env.get("GOOGLE_CLOUD_PROJECT"),
            location=env.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
            parallel_api_key=env.get("PARALLEL_API_KEY"),
            gemini_model=env.get("CLEARFRAME_GEMINI_MODEL", "gemini-3-pro-preview"),
            # AUDIO_API_KEY is the older name this project's .env already used.
            audd_api_token=env.get("AUDD_API_TOKEN") or env.get("AUDIO_API_KEY"),
            territories=[
                t.strip().upper()
                for t in env.get("CLEARFRAME_TERRITORIES", "US").split(",")
                if t.strip()
            ],
            # Default local, and unset means local, so every existing command,
            # the whole test suite and the smoke script keep the behaviour they
            # have. Opting in to the cloud is a deliberate act, like the auth
            # gate before it.
            profile="cloud" if env.get("CLEARFRAME_PROFILE") == "cloud" else "local",
            bucket=env.get("CLEARFRAME_BUCKET"),
            tasks_queue=env.get("CLEARFRAME_TASKS_QUEUE"),
            worker_url=env.get("CLEARFRAME_WORKER_URL"),
            tasks_sa=env.get("CLEARFRAME_TASKS_SA"),
        )


def validate_live(cfg: ClearFrameConfig) -> list[str]:
    """Return the env var names still required before live mode can run."""
    missing = []
    if not cfg.project:
        missing.append("GOOGLE_CLOUD_PROJECT")
    if not cfg.parallel_api_key:
        missing.append("PARALLEL_API_KEY")
    return missing


def validate_cloud(cfg: ClearFrameConfig) -> list[str]:
    """Return the env var names still required before the cloud profile can run.

    Deliberately does NOT require a task queue. Pointing `CLEARFRAME_WORKER_URL`
    at a worker with no queue in front of it is a supported arrangement — it is
    how the two-container topology runs on a laptop — and refusing to start
    without a queue would make that impossible to try.
    """
    missing = []
    if not cfg.bucket:
        missing.append("CLEARFRAME_BUCKET")
    if not cfg.project:
        missing.append("GOOGLE_CLOUD_PROJECT")
    return missing
