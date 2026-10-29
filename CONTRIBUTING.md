# Contributing to AddonScope

Small, reproducible reports are especially useful: which add-ons work alone,
which combination fails, the Blender/OS versions and the exact test settings.
A report that shows an unresolved or misleading result is as useful as a success.

## Report a diagnostic problem

Use the repository's bug-report template. Include:

- AddonScope, Blender and operating-system versions.
- The add-on IDs/versions, enabled state and registration order if known.
- Factory defaults or a current-settings snapshot, timeout and run limit.
- The observed result, expected result and whether it repeats in a fresh process.
- A reviewed support bundle, report or minimal reproduction you are allowed to share.

State whether the example is an original third-party add-on, a reduced derivative
of a public report, or a generated fixture. Link the original report and version
when applicable. Keep corrected/fixed historical bugs labelled historical.

Do not attach paid or proprietary source, `userpref.blend`, API keys, tokens,
private project files or unreviewed logs. Path redaction cannot remove every
private string. See [SECURITY](SECURITY.md) for sensitive reports.

## Develop

Python 3.11+ is sufficient for the core. Only the native integration and worker
require Blender; core modules must import without `bpy`. Preserve the existing
source style and make focused changes with a concrete user outcome.

```bash
python -m unittest discover -s tests -v
python tools/build.py
```

For changes to probing, run the actual Blender checks with an absolute executable
path. Use a disposable profile and generated test input.

```bash
python tests/blender_probe_integration.py --blender /path/to/blender
python tests/blender_settings_integration.py --blender /path/to/blender \
  --output artifacts/verification/settings.json
python tests/blender_install_integration.py --blender /path/to/blender
```

UI changes need a current native Blender journey, not only a syntax check. Verify
search and selection, long paths, error/cancel recovery and cleanup/re-registration.
Keep complete diagnostic information accessible inside Blender; an export must
not become a prerequisite to reading evidence.

## Review expectations

- Static scans never import inspected add-ons.
- A probe never edits or removes the inspected installation.
- Copies and redirected preferences are not a security sandbox.
- Timeout/setup/indeterminate outcomes remain unresolved.
- Reduction preserves declared dependencies, observed order and failure identity;
  final confirmation is required before reporting a confirmed failing subset.
- Imports are observations from a named interpreter/time, not a guessed winning version.
- Saved diagnostics are data; loading them must not import or execute attached code.
- New claims identify the actual OS/Blender version and the evidence that supports them.
- Preserve upstream identity, licenses and notices for copied or vendored material.

Meaningful regression checks should reproduce the failure or protect an important
contract. Do not weaken an existing assertion merely to make a change pass.
Document commands actually run and any material gaps in the pull request.

## Platform reports

For Windows/macOS, include installation, enabling, scan, successful probe, failed
probe, timeout/stop and uninstall results. Mark each action that was not tested.
A passing Python-only CI job does not establish native Blender support.
