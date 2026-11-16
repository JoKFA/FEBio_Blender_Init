import json
from pathlib import Path

from asrp_core import doctor
from asrp_core.cli import main


def test_env_override_pointing_at_file_wins(tmp_path, monkeypatch):
    exe = tmp_path / "febio4.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("ASRP_FEBIO", str(exe))

    check = doctor.find_tool("febio", "ASRP_FEBIO", ["febio4"], [])

    assert check.status == "ok"
    assert str(exe) in check.detail


def test_env_override_pointing_nowhere_is_error_not_fallback(tmp_path, monkeypatch):
    # Even with a binary on PATH, a wrong override must not silently fall back to it.
    monkeypatch.setenv("ASRP_FEBIO", str(tmp_path / "missing.exe"))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: r"C:\elsewhere\febio4.exe")

    check = doctor.find_tool("febio", "ASRP_FEBIO", ["febio4"], [])

    assert check.status == "error"
    assert "missing.exe" in check.detail


def test_missing_tool_is_warning(monkeypatch, tmp_path):
    monkeypatch.delenv("ASRP_FEBIO", raising=False)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)

    check = doctor.find_tool("febio", "ASRP_FEBIO", ["febio4"], [str(tmp_path / "nope*.exe")])

    assert check.status == "warn"


def test_non_ascii_path_is_flagged():
    assert doctor.check_ascii_path(Path(r"D:\work\模拟")).status == "warn"
    assert doctor.check_ascii_path(Path(r"D:\work\asrp")).status == "ok"


def test_cli_json_reports_every_check(capsys, monkeypatch):
    monkeypatch.delenv("ASRP_FEBIO", raising=False)
    monkeypatch.delenv("ASRP_BLENDER", raising=False)

    code = main(["doctor", "--json"])
    report = json.loads(capsys.readouterr().out)

    names = [c["name"] for c in report]
    assert names == ["python", "febio", "blender", "ascii path"]
    assert report[0]["status"] == "ok"
    assert code == 0


def test_cli_exits_1_on_misconfigured_override(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("ASRP_BLENDER", str(tmp_path / "no-blender.exe"))

    assert main(["doctor"]) == 1
    assert "[error] blender" in capsys.readouterr().out
