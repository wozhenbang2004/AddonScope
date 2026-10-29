# AddonScope design

Current baseline: 0.3.0 release candidate. The product diagnoses Blender add-on coexistence. It does
not install, reorder, remove or patch add-ons. The first release has a native
Blender entry point, a CLI for support workflows, and a portable report.

## First successful journey

Open Blender's sidebar → AddonScope → Scan environment → select a finding →
read all observed paths and owners → inspect inventory/imports or run a copied-profile
probe. Export is optional sharing/archiving. A scan never imports add-ons. A probe is a separate, explicitly initiated
operation because it executes their registration code.

The native panel follows Blender's theme, type sizes, keyboard handling and
standard list selection. Findings precede inventory. Selection and export remain
in context. Long paths wrap in evidence; they are never the only way to identify
an owner. An empty result says what was checked, rather than promising no conflict.

## Portable report

Use a compact scope bar, a finding queue on the left and a larger evidence pane
on the right. Inventory is a secondary view. Selection keeps the list and filter
in place. At narrow widths place detail after the list; permit long paths to wrap.
Search, severity and counts refer to the finding collection. Report export belongs
to the output. No promotional hero, fabricated score, floating decorative graph
or wall of equal-weight cards.

Visual grammar: light content surface #fff over #f4f6f9; dark ink #243145,
secondary #526178, borders #dce3ed; restrained blue #315fc1 for selection and
primary action. Error/warning always include text and an icon. System UI font,
14px/1.5 base, 12px metadata, 20px detail title, 4/8/12/16/24px spacing. Evidence
uses monospace and a lightly tinted surface. Focus uses a visible outline distinct
from selected rows. Animations are optional and respect reduced motion.

The requirements are a coherent control language, clear hierarchy, list with
following detail, actions attached to their objects, and persistent errors.
Reference products do not prescribe this project's full-page layout. Native
Blender controls retain the user's theme; the portable report has its own
consistent typography, surfaces and focus behavior.

## States and limits

Before scanning: explain scan scope and show one primary action. During scan:
keep the current report until a replacement succeeds. Error: persist the reason
and retry action. Zero findings: expose coverage, inventory and runtime limitations.
No filter matches: preserve search and offer clear filters. Probing: list selected
modules, executable, timeout and the code-execution boundary before execution.
Never silently turn a timeout or unresolved registration into a confirmed conflict.

## Acceptance

The same fixture must expose incompatible package versions, owners and concrete
paths in CLI, native panel and report. Keyboard selection, search/empty recovery,
long paths and 1280px/760px report widths are checked on the current render.
Scanning must not modify add-ons. Probe copies and common configuration redirects
must leave original fixture files unchanged. A trusted add-on can still access
hardcoded external paths; a copied profile cannot enforce filesystem isolation.


## Native diagnostic views — 0.1.1

The complete diagnostic snapshot must be inspectable in Blender. Findings,
Inventory and Imports are three parallel native views. Inventory contains add-on
and distribution lists; selected details follow their list. Search covers full
metadata and paths, not only a clipped row title. A filtered-out selection never
silently supplies unrelated details; selecting a matching row or clearing search
restores the context.

Evidence uses a scrollable list with following full text and a copy action.
There is no twelve-entry cutoff or instruction to export for the remainder.
Suggested next steps stay visible without opening raw evidence. Package fields
include owner, source, path, requirements, import names, wheel tags and native
files. Less frequent metadata, test logs and scan scope use native disclosures;
this preserves readable content without piling every record into the first view.
Trial details include selected IDs, errors, failure identity, modules, import
paths and captured output. The scan-time import snapshot stays distinct from
fresh-process trial imports.

Feedback addressed: 2026-10-29, the user rejected requiring an HTML export to
inspect diagnostics. Export must remain a secondary sharing action. Validate
more than twelve evidence entries, hidden-selection search recovery, full path
copying, all views and individual trials in the actual Blender GUI.

## 0.2: comparison and copied settings

Keep the existing native Findings / Inventory / Imports views. Within a finding,
show its package name and aligned owner/version/source rows, then the observed
module path (or an explicit not-captured state). Full candidate paths stay in
Evidence. Version candidates must never be labelled the loaded version merely
because a wheel filename or enclosing directory matches. Add-on titles stay
visible while paths follow in progressively disclosed details.

The probe dialog offers Factory defaults (default) and Current add-on settings.
The latter snapshots stored AddonPreferences, including unsaved edits, on the main
thread. Apply these values before register() in the copied worker. Do not copy
userpref.blend, which can bring original repositories/startup behavior with it.
Do not imply that global preferences, keymaps, scenes or external files are
copied. Show the mode in results and keep a digest with each trial. Raw settings snapshots are omitted from trial exports. Captured add-on output
and exceptions may still contain private content; review logs before sharing.

A running job shows the current phase, selected add-ons, trial number, maximum
run budget and completed outcomes. This is a run limit, not a percent prediction.
Keep prior results inspectable while running. Stop means stop after the current
trial; final confirmation remains required for a confirmed reduced subset.

## 0.3: history, comparison and support handoff

History and sharing is one lower-priority native disclosure after scan coverage.
It groups explicit Save snapshot, history refresh, a searchable saved-snapshot
list, View saved snapshot, Compare with current scan, and Export support bundle.
No history file is written as a side effect of scanning or opening the panel.
Local snapshots retain full paths and captured output; support ZIPs replace known
path prefixes by default and omit raw settings snapshots. Add-on output may still
contain private content and must be reviewed before sharing.

Opening history changes only the displayed diagnostic record. A persistent banner
names the saved snapshot and capture time. Saved Imports explicitly says it is
not a live observation. Probe and reduction are disabled for historical records;
return restores the current scan, test conditions, search and selection. Scanning
again establishes a new current record. Opening a snapshot before the first scan
is supported; closing it returns to the unscanned state.

Compare always runs from the chosen saved record to the current session's latest
scan, not to another record accidentally left on screen. A searchable change list
shows added, removed and changed add-ons, distribution versions/paths and captured
imports. The selected detail shows before and after values and can be copied in
full. Zero changes is explicit. Historical identity and comparison timestamps
remain visible, including when the current view is itself a saved record.

Trial controls belong in their existing confirmation dialog: 1–600 seconds per
initial trial, and 3–100 reduction trials including the final confirmation.
Reduction retains the original timeout/settings to preserve conditions. Results
record these limits. A retained failure is labelled “Failure reproduced in the
retained subset”; it must not use the registration-success checkmark.

Acceptance: in actual Blender, explicitly save and reopen a snapshot, search the
history list, compare a changed fixture against the current scan, read/copy full
changes, export and inspect the support ZIP, return to the original live selection,
and verify snapshot records cannot enable/reduce historical add-ons. Verify
restart/re-registration still finds the saved records and every new native
property is removed on unregister. Capture the actual new dialog, history and
comparison states; generated fixtures remain labelled as generated.
