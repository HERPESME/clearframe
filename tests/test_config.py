from pathlib import Path

import pytest

from clearframe.config import ClearFrameConfig, validate_live
from clearframe.models import Production
from clearframe.pipeline import build_context


def test_from_env_defaults():
    cfg = ClearFrameConfig.from_env({})
    assert cfg.mode == "demo"
    assert cfg.location == "us-central1"
    assert cfg.gemini_model == "gemini-3-pro-preview"


def test_from_env_live():
    cfg = ClearFrameConfig.from_env(
        {
            "CLEARFRAME_MODE": "live",
            "GOOGLE_CLOUD_PROJECT": "my-proj",
            "PARALLEL_API_KEY": "pk",
            "CLEARFRAME_GEMINI_MODEL": "gemini-2.5-pro",
        }
    )
    assert cfg.mode == "live" and cfg.project == "my-proj"
    assert cfg.gemini_model == "gemini-2.5-pro"


def test_validate_live_lists_missing():
    cfg = ClearFrameConfig.from_env({"CLEARFRAME_MODE": "live"})
    missing = validate_live(cfg)
    assert "GOOGLE_CLOUD_PROJECT" in missing and "PARALLEL_API_KEY" in missing


def test_build_context_demo_uses_fixtures(tmp_path):
    from clearframe.integrations.gemini_client import FixtureGeminiClient

    cfg = ClearFrameConfig.from_env({})
    prod = Production(id="x", title="T", footage_uri="demo://s", duration_s=10)
    ctx = build_context(cfg, prod, tmp_path)
    assert isinstance(ctx.gemini, FixtureGeminiClient)


def test_build_context_live_wires_live_clients(tmp_path):
    from clearframe.integrations.gemini_live import LiveGeminiClient
    from clearframe.integrations.parallel_client import LiveParallelClient

    cfg = ClearFrameConfig.from_env(
        {
            "CLEARFRAME_MODE": "live",
            "GOOGLE_CLOUD_PROJECT": "my-proj",
            "PARALLEL_API_KEY": "pk",
        }
    )
    prod = Production(id="x", title="T", footage_uri="clip.mp4", duration_s=10)
    ctx = build_context(cfg, prod, tmp_path)
    assert isinstance(ctx.gemini, LiveGeminiClient)
    assert isinstance(ctx.parallel, LiveParallelClient)


def test_cli_live_without_env_exits_2(capsys, monkeypatch):
    for var in ("CLEARFRAME_MODE", "GOOGLE_CLOUD_PROJECT", "PARALLEL_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    from clearframe.cli import main

    rc = main(["run", "--live", "--footage", "clip.mp4"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "GOOGLE_CLOUD_PROJECT" in out and "PARALLEL_API_KEY" in out


def test_territories_parse_from_env():
    from clearframe.config import ClearFrameConfig

    cfg = ClearFrameConfig.from_env({"CLEARFRAME_TERRITORIES": "us, de ,fr"})
    assert cfg.territories == ["US", "DE", "FR"]


def test_territories_default_to_us():
    from clearframe.config import ClearFrameConfig

    assert ClearFrameConfig.from_env({}).territories == ["US"]
