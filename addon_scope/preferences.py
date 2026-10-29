"""Portable stored add-on settings; importing this module does not require bpy."""

import hashlib
import json
import math


def _plain(value, depth=0):
    if depth > 16:
        raise ValueError("Add-on settings exceed the supported nesting depth.")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if hasattr(value, "items"):
        return {str(key): _plain(item, depth + 1) for key, item in value.items()}
    if hasattr(value, "to_list"):
        value = value.to_list()
    if isinstance(value, (list, tuple)):
        return [_plain(item, depth + 1) for item in value]
    raise ValueError("An add-on setting cannot be copied as JSON. Use the factory profile for this test.")


def capture_settings(preferences, modules):
    """Capture stored ID properties, including unsaved edits, on Blender's main thread.

    Unset properties retain the copied add-on's defaults. Unsupported pointers or
    non-finite numbers stop capture rather than silently changing test conditions.
    """
    result = {}
    for module in modules:
        addon = preferences.addons.get(module)
        if addon is not None and addon.preferences is not None:
            result[module] = _plain(addon.preferences)
    settings_identity(result)  # Enforce the same size/type contract as the worker.
    return result


def settings_identity(settings):
    plain = _plain(settings)
    if not isinstance(plain, dict) or any(not isinstance(v, dict) for v in plain.values()):
        raise ValueError("Settings must map module names to stored property dictionaries.")
    encoded = json.dumps(plain, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > 2 * 1024 * 1024:
        raise ValueError("Add-on settings exceed the 2 MiB snapshot limit.")
    return hashlib.sha256(encoded).hexdigest()
