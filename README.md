# AddonScope

Find the dependency behind a Blender add-on conflict, then reproduce it in a fresh process.

[中文说明](README.zh-CN.md) · [How it works](docs/RESEARCH.md) · [Verification](docs/VERIFICATION.md) · [Roadmap](docs/ROADMAP.zh-CN.md)

Two add-ons work separately, then fail together. AddonScope connects the packages
supplied by each add-on to Python's observed import paths. A copied-profile test
can reproduce a registration failure and look for a smaller failing combination.
All diagnostic details are available inside Blender; exporting is optional.

**0.3.0 Alpha** is validated on Linux with Blender 4.5.15 LTS. Windows, macOS
and Blender 5.x still need their own runtime validation. The exact release checks
and remaining gaps are listed in
[VERIFICATION](docs/VERIFICATION.md) and the [release checklist](docs/RELEASE_CHECKLIST.md).

## 30-second quick start

With the extension installed, open the 3D View sidebar with **N**, choose
**AddonScope**, then **Scan environment**. Select a finding to compare its owners,
supplied dependency versions and captured import path. **Inventory** and
**Imports** provide searchable, complete records with copy actions.

Scanning reads metadata and the current import snapshot. It does not import,
enable, remove or patch the inspected add-ons. A finding is a lead; it is not
proof that the add-ons fail together.

## Native interface

| Dependency evidence | Saved versus current scan |
| --- | --- |
| ![Native dependency version and import-path comparison](docs/assets/native-comparison.png) | ![Native history comparison](docs/assets/history-comparison.png) |

Actual Blender 4.5.15 panels using generated test add-ons. The history example
changes a generated add-on's manifest from 1.0.0 to 1.1.0 and rescans; it is not a
third-party success case.

## Install

1. Obtain `addon-scope-0.3.0.zip` from a release, or build it from source below.
2. In **Edit → Preferences → Get Extensions**, open the menu and choose **Install from Disk**.
3. Select the ZIP and enable AddonScope.
4. Open **3D View → Sidebar → AddonScope**.

Install the extension ZIP, not the source archive. For an update, use Blender's
extension installation flow with the newer ZIP. Keep your previous download if
you need to return to an earlier alpha.

## Reproduce a failure

**Test affected owners** selects the owners of the current finding, including
owners that are disabled. **Test enabled add-ons** selects discovered enabled
add-ons in preference order. The test dialog shows what will run and asks you to
confirm that the selected add-ons are trusted. **Seconds per trial** accepts
1–600 seconds (default 30). Reduction accepts **Maximum trials** from 3–100
(default 16, including final confirmation) and retains the original timeout.

Choose **Factory defaults**, or **Current add-on settings** to snapshot stored
AddonPreferences, including unsaved edits, before registration. Settings mode
does not copy global preferences, keymaps, scenes or external files. Saved
external paths still refer to their original locations.

A failed test offers **Reduce failing combination**. Reduction preserves declared
dependencies and registration order, keeps the same module/type/message failure
identity, and repeats the retained subset in another fresh process. The running
panel shows the current combination, phase, completed trials and run limit.
Stopping takes effect after the current trial. Review individual outcomes in
**Test details**.

A confirmed subset means **the failure repeated**. It does not mean the subset is
compatible, globally smallest, or the only cause. A broken add-on may also fail
on its own. Disabled owners have no observed registration order; the dialog
identifies their experimental order.

## Saved diagnostics and sharing

Open **History and sharing** to save the current scan with **Save snapshot**.
Saving is explicit: a scan does not silently create history. Local snapshots keep
complete paths and recorded trial results under Blender's user configuration.
**View saved snapshot** labels the capture time and keeps old imports distinct
from a live observation. Tests cannot run from a historical snapshot; use
**Return to current scan** first.

**Compare with current scan** compares the selected saved snapshot with the
latest current scan. It lists added, removed and changed add-ons, package metadata
and import paths. Differences explain what changed in the snapshots; they do not
prove causality or reproduce a conflict. Every difference remains searchable and
copyable in Blender.

**Export support bundle** writes a ZIP containing `report.html`, `scan.json`,
`trials.json` and `summary.txt`. It includes no add-on source or original settings
snapshot and cannot reconstruct the full environment. Shared environment data
is limited to known version/platform fields; arbitrary nested environment data is
not included. Paths are redacted by default. HTML/JSON reports and per-trial logs can also be exported separately.
Full evidence stays available in Blender, without any export.

Path replacement is not a general privacy filter: review add-on output,
exception messages and reports before sharing them. Local history keeps full
paths; protect it like other personal diagnostic data.

No account, API key, telemetry or remote analysis service is required.
AddonScope does not install replacement dependencies or automatically repair
add-ons.

## CLI and a runnable demonstration

Python 3.11+; run from the source directory. There are no runtime pip dependencies.

```bash
python -m addon_scope scan /path/to/extensions/repository \
  /path/to/extensions/.local/lib/python3.11/site-packages \
  --html report.html --json report.json
```

Include Blender's own `site-packages` when comparing bundled dependencies.
CLI-only scans cannot observe imports inside another Blender process. The native
panel captures its own interpreter's import paths and target wheel platform.

The demonstration generates two small add-ons with different versions of one
pure-Python dependency. It is a controlled fixture, not a community success case.

```bash
python tools/demo.py /tmp/addon-scope-demo
python -m addon_scope probe /tmp/addon-scope-demo/extensions/demo \
  --blender /path/to/blender \
  --addon bl_ext.demo.scope_legacy --addon bl_ext.demo.scope_modern \
  --trust-addons --minimize --max-runs 16 --output trials.json
```

`--trust-addons` acknowledges code execution. To retain a required context add-on,
add `--depends ADDON_ID=DEPENDENCY_ID`; repeat as needed. IDs are listed in the
JSON inventory. Arguments preserve requested enable order before extra dependencies.

Scan exits 0 unless `--fail-on error|warning` finds that severity. Probe exits 0
for registration success, 1 for reproduced failure or a confirmed retained
combination, and 2 for unresolved/invalid input. The run limit includes final
confirmation. Read the result's reason before interpreting a reduced set.

## What a result means

| Result | Meaning |
| --- | --- |
| Potential conflict | Installed metadata warrants investigation; no failure has been reproduced. |
| Observed import | A module path was captured in that interpreter at scan time. |
| Probe pass | Background registration completed under the recorded test settings. |
| Probe fail | A selected add-on raised an exception or the process exited during its registration. |
| Unresolved | Setup, timeout, missing results or intermittency prevented a conclusion. |
| Confirmed subset | A fresh run repeated the retained failure. |

## Boundaries

Only probe add-ons you trust. Copied files, separate processes and redirected
home/XDG/AppData directories isolate common configuration writes; they are **not
an operating-system security sandbox**. Add-on code can still access external
paths, services and devices. Blender's offline flag does not block arbitrary
Python network calls.

Background registration does not reproduce scene actions, viewport callbacks or
external services. Native DLL/SO filename overlap is a lead, not proof of an ABI
or symbol conflict. Stored add-on settings can contain sensitive values. Raw
settings snapshots are omitted from trial exports, but an add-on can print those
values or include them in an exception.

The release includes generated fixtures and an [incident-derived Sentinel
reproduction](docs/CASES.md) using pinned upstream `typing_extensions` modules.
It does not run the original Speckle connector. Historical community reports and
derived reproductions are labelled separately. No compatibility success rate,
performance improvement or community adoption is implied by passing the fixtures.

## Contribute

```bash
python -m unittest discover -s tests -v
python tests/blender_probe_integration.py --blender /path/to/blender
python tests/blender_settings_integration.py --blender /path/to/blender \
  --output artifacts/verification/settings.json
python tools/build.py
```

The integration checks generate their own wheels/add-ons, verify separate success
and combined failure, reduce the pair, preserve declared dependencies and check
that original fixture/configuration files stay unchanged.

See [CONTRIBUTING](CONTRIBUTING.md) for reports and development, and
[SECURITY](SECURITY.md) for sensitive findings. Include Blender/OS versions, the
recorded test settings and the smallest reproduction you are allowed to share.
Do not attach proprietary add-on code or personal configuration.

GPL-3.0-or-later. Bundled dependency notices and upstream attributions are in
[THIRD_PARTY](THIRD_PARTY.md).
