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


def test_the_verify_gate_starts_with_the_ruff_lint_check(monkeypatch):
    verify = load_verify()
    seen = []
    monkeypatch.setattr(verify, "step", lambda name, cmd, extra_env=None: seen.append((name, cmd)))
    monkeypatch.setattr(verify, "locate", lambda *a, **k: SimpleNamespace(path=Path("blender.exe"), how=""))
    verify.main()
    name, cmd = seen[0]
    assert name == "lint" and cmd[1:] == ["-m", "ruff", "check", "."]


def test_step_passes_the_extra_environment_to_the_child(monkeypatch):
    verify = load_verify()
    captured = {}

    def fake_run(cmd, cwd, env):
        captured["env"] = env
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(verify.subprocess, "run", fake_run)
    verify.step("x", ["true"], {"ASRP_SLOW": "1"})
    assert captured["env"]["ASRP_SLOW"] == "1"


def test_the_verify_gate_checks_that_no_lab_or_vendor_file_is_tracked(monkeypatch):
    verify = load_verify()
    seen = []
    monkeypatch.setattr(verify, "step", lambda name, cmd, extra_env=None: seen.append((name, cmd)))
    monkeypatch.setattr(verify, "locate", lambda *a, **k: SimpleNamespace(path=Path("blender.exe"), how=""))
    verify.main()
    assert [cmd[-1] for name, cmd in seen if name == "no lab or vendor files in git"] == [
        str(REPO / "tools" / "check_no_lab_files.py")]


def run_level(monkeypatch, level):
    verify = load_verify()
    seen = []
    monkeypatch.setattr(verify, "step", lambda name, cmd, extra_env=None: seen.append((name, cmd, extra_env)))
    monkeypatch.setattr(verify, "locate", lambda *a, **k: SimpleNamespace(path=Path("blender.exe"), how=""))
    verify.main(["--level", level])
    return verify, seen


def test_the_docs_level_runs_lint_the_guard_and_only_the_document_tests(monkeypatch):
    verify, seen = run_level(monkeypatch, "docs")
    assert [name for name, _, _ in seen] == ["lint", "no lab or vendor files in git", "tests"]
    name, cmd, env = seen[-1]
    assert cmd[-len(verify.DOC_TESTS):] == verify.DOC_TESTS and env is None
    assert all((REPO / path).is_file() for path in verify.DOC_TESTS)


def test_the_core_level_runs_the_whole_suite_without_the_slow_switch_and_without_blender(monkeypatch):
    _, seen = run_level(monkeypatch, "core")
    assert [name for name, _, _ in seen] == ["lint", "no lab or vendor files in git", "tests"]
    assert seen[-1][2] is None and not any(str(part).startswith("tests/") for part in seen[-1][1])


def test_the_full_level_is_what_no_argument_gives(monkeypatch):
    _, full = run_level(monkeypatch, "full")
    verify = load_verify()
    plain = []
    monkeypatch.setattr(verify, "step", lambda name, cmd, extra_env=None: plain.append((name, cmd, extra_env)))
    monkeypatch.setattr(verify, "locate", lambda *a, **k: SimpleNamespace(path=Path("blender.exe"), how=""))
    verify.main()
    assert plain == full and len(full) == 8 and full[2][2] == {"ASRP_SLOW": "1"}


def test_auto_picks_the_level_from_the_changed_files():
    verify = load_verify()
    assert verify.pick_level(["docs/09-roadmap-and-tasks.md", "README.md"]) == "docs"
    assert verify.pick_level(["docs/09-roadmap-and-tasks.md", "src/asrp_core/skinning.py"]) == "core"
    assert verify.pick_level(["tools/verify.py"]) == "core"
    assert verify.pick_level(["docs/06-ui.md", "blender_addon/asrp_blender/__init__.py"]) == "full"
    assert verify.pick_level([]) == "full"
