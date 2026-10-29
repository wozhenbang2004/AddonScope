"""AddonScope: inspect Blender add-on environments without changing them."""

bl_info = {
    "name": "AddonScope",
    "author": "AddonScope contributors",
    "version": (0, 3, 0),
    "blender": (4, 5, 0),
    "location": "3D View > Sidebar > AddonScope",
    "description": "Trace shared Python dependencies and add-on conflicts",
    "category": "Development",
}

__version__ = "0.3.0"


def register():
    from . import blender_ui
    blender_ui.register()


def unregister():
    from . import blender_ui
    blender_ui.unregister()

