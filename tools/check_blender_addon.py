"""Load the add-on in a real Blender and run its backend check end to end.

    blender --background --factory-startup --python-exit-code 1 --python tools/check_blender_addon.py

Proves the Blender -> uv subprocess -> asrp_core -> JSON round trip works on this machine.
"""

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the repo clean when run from the verify gate
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_addon"))

import bpy  # noqa: E402

import asrp_blender  # noqa: E402

asrp_blender.register()
try:
    result = bpy.ops.asrp.check_backend()
    assert result == {"FINISHED"}, f"operator returned {result}"
    checks = json.loads(bpy.context.window_manager.asrp_status)
    names = [c["name"] for c in checks]
    assert names == ["python", "febio", "blender", "ascii path"], names
    print(f"blender {bpy.app.version_string}, python {sys.version.split()[0]}")
    for c in checks:
        print(f"  [{c['status']:5}] {c['name']:12} {c['detail']}")
    print("ADDON CHECK PASSED")
finally:
    asrp_blender.unregister()
