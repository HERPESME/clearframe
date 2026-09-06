from clearframe.cli import main


def test_cli_demo_auto_approve(tmp_path, capsys):
    rc = main(["run", "--demo", "--out", str(tmp_path), "--auto-approve"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "CRITICAL" in out
    assert (tmp_path / "dossier.html").exists()
    assert (tmp_path / "dossier.docx").exists()
    # Two formats of one document, and nothing else. The marker CSV, the EDL,
    # the PRO cue sheet and the raw JSON dump were being written beside the
    # report and offered as equal filename links.
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == [
        "dossier.docx", "dossier.html"
    ]


def test_cli_demo_without_approve_reports_pending(tmp_path, capsys):
    rc = main(["run", "--demo", "--out", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "review" in out.lower()
    assert not (tmp_path / "dossier.html").exists()


def test_cli_second_run_resumes_persisted_state(tmp_path, capsys):
    main(["run", "--demo", "--out", str(tmp_path)])
    capsys.readouterr()
    rc = main(["run", "--demo", "--out", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Resuming production 'demo'" in out
