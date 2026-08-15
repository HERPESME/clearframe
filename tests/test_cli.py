from clearframe.cli import main


def test_cli_demo_auto_approve(tmp_path, capsys):
    rc = main(["run", "--demo", "--out", str(tmp_path), "--auto-approve"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "CRITICAL" in out
    assert (tmp_path / "dossier.html").exists()
    assert (tmp_path / "markers.edl").exists()
    assert (tmp_path / "markers.csv").exists()
    assert (tmp_path / "dossier.json").exists()
    assert (tmp_path / "cue_sheet.csv").exists()


def test_cli_demo_without_approve_reports_pending(tmp_path, capsys):
    rc = main(["run", "--demo", "--out", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "review" in out.lower()
    assert not (tmp_path / "dossier.html").exists()
