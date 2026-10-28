"""ASRP Blender add-on: UI only. All solver work runs in asrp_core, as a subprocess."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import bpy

STATUS_ICONS = {"ok": "CHECKMARK", "warn": "INFO", "error": "ERROR"}


def core_project() -> Path | None:
    """The asrp project whose venv runs the core: $ASRP_PROJECT, else the repo this add-on lives in."""
    override = os.environ.get("ASRP_PROJECT")
    if override:
        return Path(override)
    repo = Path(__file__).resolve().parents[2]
    return repo if (repo / "pyproject.toml").is_file() else None


def run_core(*args: str) -> subprocess.CompletedProcess:
    project = core_project()
    uv = shutil.which("uv")
    if project is None:
        raise RuntimeError("asrp project not found; set ASRP_PROJECT")
    if uv is None:
        raise RuntimeError("uv not found on PATH")
    return subprocess.run(
        [uv, "run", "--project", str(project), "asrp", *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


class ASRP_OT_check_backend(bpy.types.Operator):
    bl_idname = "asrp.check_backend"
    bl_label = "Check Backend"
    bl_description = "Run `asrp doctor` in the solver core and show what it finds"

    def execute(self, context):
        try:
            proc = run_core("doctor", "--json")
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if not proc.stdout.strip():
            self.report({"ERROR"}, f"asrp doctor printed nothing: {proc.stderr.strip()}")
            return {"CANCELLED"}
        context.window_manager.asrp_status = proc.stdout
        checks = json.loads(proc.stdout)
        problems = [c["name"] for c in checks if c["status"] != "ok"]
        self.report({"WARNING" if problems else "INFO"}, f"backend checks not ok: {problems}" if problems else "backend ready")
        return {"FINISHED"}


class ASRP_PT_main(bpy.types.Panel):
    bl_label = "ASRP"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"

    def draw(self, context):
        layout = self.layout
        layout.operator(ASRP_OT_check_backend.bl_idname, icon="FILE_REFRESH")
        status = context.window_manager.asrp_status
        if not status:
            return
        for check in json.loads(status):
            layout.label(text=f"{check['name']}: {check['detail']}", icon=STATUS_ICONS[check["status"]])


classes = (ASRP_OT_check_backend, ASRP_PT_main)


def register():
    # WindowManager properties live only for the session; nothing is saved into the .blend.
    bpy.types.WindowManager.asrp_status = bpy.props.StringProperty()
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.WindowManager.asrp_status
