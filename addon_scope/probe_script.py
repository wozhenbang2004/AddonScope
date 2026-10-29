"""Standalone Blender-side registration worker, copied into each probe profile."""

import json
from pathlib import Path
import re
import sys
import traceback
from types import ModuleType


def _failure_key(module, error):
    message = re.sub(r"addonscope-probe-[^/\\]+", "addonscope-probe-TEMP", str(error))
    return json.dumps([module, type(error).__name__, message], ensure_ascii=True)


def _seed_settings(bpy, settings):
    # A temporary preference type creates Blender's native backing IDPropertyGroup
    # before the real add-on's register() reads it. Unregistering the type retains
    # its stored values. No add-on source is imported to restore these settings.
    for index, (module, values) in enumerate(settings.items()):
        seed = type(f"SCOPE_SeedPreferences_{index}", (bpy.types.AddonPreferences,),
                    {"bl_idname": module})
        bpy.utils.register_class(seed)
        try:
            addon = bpy.context.preferences.addons.get(module)
            if addon is None:
                addon = bpy.context.preferences.addons.new()
                addon.module = module
            for key, value in values.items():
                addon.preferences[key] = value
        finally:
            bpy.utils.unregister_class(seed)


def main():
    import bpy
    import addon_utils

    job_path = Path(sys.argv[sys.argv.index("--") + 1])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    phase = Path(job["phase"])
    phase.write_text(json.dumps({"stage": "setup"}), encoding="utf-8")
    result = {"status": "unresolved", "reason": "Profile setup did not complete.",
              "errors": [], "loaded": {}, "failure_key": ""}
    try:
        preferences = bpy.context.preferences
        for repository in list(preferences.extensions.repos):
            repository.enabled = False
        for repository in job["repositories"]:
            repo = next((item for item in preferences.extensions.repos
                         if item.module == repository["module"]), None)
            if repo is None:
                repo = preferences.extensions.repos.new(
                    name="AddonScope probe " + repository["module"],
                    module=repository["module"], custom_directory=repository["directory"],
                    source="USER",
                )
            repo.custom_directory = repository["directory"]
            repo.use_custom_directory = True
            repo.remote_url = ""
            repo.enabled = True
            repo.use_sync_on_startup = False
            if repo.module != repository["module"]:
                raise RuntimeError("Blender renamed an extension repository module; probe cannot preserve its identity.")
        bpy.utils.refresh_script_paths()
        preferences.use_preferences_save = False
        _seed_settings(bpy, job.get("settings", {}))
        errors = []
        keys = []

        def capture_setup(error):
            errors.append("Extension dependency setup:\n" + traceback.format_exc())
            keys.append(_failure_key("<extension-setup>", error))

        extensions = [module for module in job["modules"] if module.startswith("bl_ext.")]
        if extensions:
            addon_utils.extensions_refresh(addon_modules_pending=extensions, handle_error=capture_setup)
            if errors:
                raise RuntimeError("Blender could not prepare extension dependencies: " + keys[0])
        for module in job["modules"]:
            phase.write_text(json.dumps({"stage": "registering", "module": module}), encoding="utf-8")

            def capture(error):
                text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                errors.append(module + ":\n" + text)
                keys.append(_failure_key(module, error))

            count_before = len(errors)
            enabled = addon_utils.enable(module, default_set=True, handle_error=capture,
                                         refresh_handled=module.startswith("bl_ext."))
            if enabled is None and len(errors) == count_before:
                errors.append(module + ": registration returned no enabled module.")
                keys.append(json.dumps([module, "RegistrationReturnedNone", ""]))
        phase.write_text(json.dumps({"stage": "collecting_imports"}), encoding="utf-8")
        targets = job.get("targets", [])
        loaded = {}
        for name, module in list(sys.modules.items()):
            if targets and not any(name == target or name.startswith(target + ".") for target in targets):
                continue
            # sys.modules can contain lazy proxies. Reading provenance must not
            # call their __getattr__ hooks or import additional add-on code.
            if not isinstance(module, ModuleType):
                continue
            filename = vars(module).get("__file__")
            if isinstance(filename, str):
                loaded[name] = filename
        result = {
            "status": "fail" if errors else "pass",
            "reason": "One or more add-ons failed registration." if errors else "Selected add-ons registered in the copied test profile.",
            "errors": errors, "loaded": loaded,
            "failure_key": keys[0] if keys else "",
        }
    except Exception as error:
        result["reason"] = "Probe setup failed: " + str(error)
        result["errors"] = [traceback.format_exc()]
    Path(job["result"]).write_text(json.dumps(result), encoding="utf-8")
    phase.write_text(json.dumps({"stage": "complete"}), encoding="utf-8")


if __name__ == "__main__":
    main()
