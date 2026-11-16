"""The repository holds the project, not the process (docs/08 section 1, T-38).

The one-off development files that docs/13 E-12 lists as PROCESS are gone from `git ls-files`: one left over fails.
The local AI development files (`AGENTS.md`, `CLAUDE.md`, `.claude/`) are each machine's own and not tracked either.
Two of E-12's entries became product after it was written and are not in the list: `tools/prototype_numbers.py` and
`tests/test_prototype_page.py` (the results page docs/15 is checked against them), `tests/test_render_prototype.py`
(tests the tool that renders the page's pictures), and the `data/preview/prototype_*` archives and pictures the page reads.
"""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# E-12's PROCESS paths that must not be tracked (files), and the folders under which nothing may be tracked.
ONE_OFF_FILES = [
    "tools/aa_" + "standin.py",  # in two pieces: tests/test_prototype_page.py looks for the whole name in code
    "tests/test_aa_" + "standin.py", "tools/landmark_layer_check.py", "tools/prototype2_numbers.py", "tools/rehearse_ziva_export.py",
    "tools/lip_attachments_preview.py", "tools/render_playback.py",
    "tools/briefing/app.js", "tools/briefing/build.py", "tools/briefing/template.html",
    "spikes/s2_tetmesh.py", "spikes/blender_background_run.py", "spikes/attachment_overlap.py", "spikes/audit_aa_fit.py",
    "spikes/audit_aa_folds.py", "spikes/audit_attachment.py", "spikes/audit_cycles.py", "spikes/audit_cycles_aa.py",
    "spikes/audit_head_shake.py", "spikes/audit_head_shake_timestep.py", "spikes/audit_material.py", "spikes/audit_p2.py",
    "spikes/audit_rhoi_springs.py", "spikes/audit_skin_identity.py", "spikes/audit_threads.py", "spikes/t28_damped_cube.py",
    "spikes/t28_head_shake.py",
    "tests/test_audit_cycles_aa.py", "tests/test_prototype2_page.py",
    # what the one-off scripts wrote into data/preview, and the pictures of the onboarding page
    "data/preview/audit_head_shake_timestep.json", "data/preview/audit_rhoi_springs.json", "data/preview/t28_damped_cube.json",
    "data/preview/t28_demo_run_report.json", "data/preview/t28_head_shake_report.json",
    "data/preview/t28_shake_default_run_report.json", "data/preview/t28_still_default_run_report.json",
    "data/preview/prototype_provenance.json", "data/preview/prototype_rest.png", "data/preview/prototype_settled.png",
    "data/preview/prototype_open.png",
    "data/preview/01_all_parts.webp", "data/preview/02_lips_on_bone.webp", "data/preview/03_lips_and_landmarks.webp",
    "data/preview/04_side_hinge.webp", "data/preview/05_jaw_open_lips_stay.webp",
]
ONE_OFF_FOLDERS = ["spikes/", "tools/briefing/", "data/briefing/", "data/lab_export/manual_maya_obj/"]
ONE_OFF_PREFIXES = ["data/preview/aa_"]  # the retired stand-ins' archives (T-36)
LOCAL_AI = ["AGENTS.md", "CLAUDE.md", ".claude/"]


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return [line for line in out.splitlines() if line]


def left_over(tracked: list[str]) -> list[str]:
    """The tracked paths that are one-off development files or the local AI development files."""
    return sorted(p for p in tracked
                  if p in ONE_OFF_FILES or p.startswith(tuple(ONE_OFF_FOLDERS + ONE_OFF_PREFIXES))
                  or p in LOCAL_AI[:2] or p.startswith(LOCAL_AI[2]))


def test_no_one_off_development_file_is_tracked():
    tracked = tracked_files()
    assert len(tracked) > 100 and "src/asrp_core/cli.py" in tracked  # the listing itself works
    assert left_over(tracked) == []


def test_the_three_checks_that_were_spikes_are_still_there():
    tracked = tracked_files()
    for path in ("tests/s1_dynamic_jaw.py", "tests/s2_lips_febio.py", "tests/s3_attachment.py", "tests/landmark_layer_check.py"):
        assert path in tracked and (REPO / path).is_file()


def test_the_check_can_fail():
    tracked = ["README.md", "spikes/audit_p2.py", "tools/render_playback.py", "tools/briefing/x.js", "AGENTS.md",
               ".claude/verify.json", "data/preview/aa_run_a.json", "data/lab_export/manual_maya_obj/chin.obj",
               "tools/prototype_numbers.py", "tests/test_prototype_page.py", "data/preview/prototype_jaw32_fine.png"]
    assert left_over(tracked) == [".claude/verify.json", "AGENTS.md", "data/lab_export/manual_maya_obj/chin.obj",
                                  "data/preview/aa_run_a.json", "spikes/audit_p2.py", "tools/briefing/x.js",
                                  "tools/render_playback.py"]
    assert left_over(["README.md", "tests/s1_dynamic_jaw.py"]) == []
