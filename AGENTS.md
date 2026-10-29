# Working on AddonScope

Read docs/PROJECT.md, docs/DESIGN.md and docs/RESEARCH.md before changing behavior.
Core modules must import without bpy. Static scans never import add-ons. Probes
use copied files and disposable profiles; isolation is not a security sandbox.
Never edit or remove an inspected installation. Preserve upstream licenses.

Run `python -m unittest discover -s tests -v` and `python tools/build.py`.
Runtime checks are in `tests/blender_integration.py`; use Blender 4.5 or newer.
