"""Asset import (T-02): turn a Maya export into a scene.json the rest of the core can use.

`coords` holds the project's only conversion from the lab's scene coordinates to mm, Z up
(docs/03 section 10); everything else calls it. `lab` reads the export folder
(tools/maya_export.py, docs/12 part 1) and writes the scene, the converted meshes and a report.
"""
