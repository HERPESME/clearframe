import pytest

adk = pytest.importorskip("google.adk")


async def test_adk_sequential_pipeline_produces_dossier(tmp_path):
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from clearframe.adk.agents import build_clearframe_agent
    from clearframe.pipeline import demo_context

    ctx = demo_context(tmp_path)
    agent = build_clearframe_agent(ctx, out_dir=tmp_path / "out", auto_approve=True)
    svc = InMemorySessionService()
    await svc.create_session(app_name="clearframe", user_id="u", session_id="s")
    runner = Runner(agent=agent, app_name="clearframe", session_service=svc)
    events = [
        e
        async for e in runner.run_async(
            user_id="u",
            session_id="s",
            new_message=types.Content(role="user", parts=[types.Part(text="run")]),
        )
    ]
    assert events, "runner should yield stage events"
    assert (tmp_path / "out" / "dossier.html").exists()
    session = await svc.get_session(app_name="clearframe", user_id="u", session_id="s")
    assert session.state.get("clearframe:dossier") == "complete"


def test_cli_adk_flag_runs_pipeline(tmp_path, capsys):
    from clearframe.cli import main

    rc = main(["run", "--demo", "--adk", "--auto-approve", "--out", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ADK SequentialAgent" in out and "CRITICAL" in out
    assert (tmp_path / "dossier.html").exists()


def test_cli_adk_without_auto_approve_exits_2(tmp_path, capsys):
    from clearframe.cli import main

    rc = main(["run", "--demo", "--adk", "--out", str(tmp_path)])
    assert rc == 2
