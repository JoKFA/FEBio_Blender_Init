"""tools/verify.py is the definition of done, so it must run the real-lip tests (audit item 15)."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]


def load_verify():
    spec = importlib.util.spec_from_file_location("verify_tool", REPO / "tools" / "verify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_verify_gate_runs_the_test_suite_with_the_slow_real_lip_tests_switched_on(monkeypatch):
    verify = load_verify()
    seen = []
    monkeypatch.setattr(verify, "step", lambda name, cmd, extra_env=None: seen.append((name, cmd, extra_env)))
    monkeypatch.setattr(verify, "locate", lambda *a, **k: SimpleNamespace(path=Path("blender.exe"), how=""))
    verify.main()
    [(name, cmd, env)] = [s for s in seen if s[0] == "tests"]
    assert env == {"ASRP_SLOW": "1"} and "pytest" in cmd
    assert all(s[2] is None for s in seen if s[0] != "tests")  # and nothing else gets it


def test_step_passes_the_extra_environment_to_the_child(monkeypatch):
    verify = load_verify()
    captured = {}

    def fake_run(cmd, cwd, env):
        captured["env"] = env
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(verify.subprocess, "run", fake_run)
    verify.step("x", ["true"], {"ASRP_SLOW": "1"})
    assert captured["env"]["ASRP_SLOW"] == "1"
