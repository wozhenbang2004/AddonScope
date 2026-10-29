# Changelog

Versions are alpha releases. Entries describe implemented behavior only after
integration and verification; planned work stays in the roadmap.

## 0.3.0 — Alpha (2026-10-29)

- Explicitly save diagnostic snapshots locally, including the recorded trial results; scanning does not automatically write history.
- View saved snapshots with their capture identity, return to the current scan, and compare add-on/package/import changes in searchable native lists.
- Keep historical imports separate from live observations and disable probes while viewing a saved snapshot.
- Export a support ZIP containing the offline report, scan JSON, recorded trials and summary; redact path prefixes by default and omit original settings snapshots/source code.
- Configure per-trial timeout and reduction run budget; label a confirmed subset as a reproduced failure rather than a compatibility success.
- Distinguish registration from later import-provenance collection so a later process exit is not attributed to the last registered add-on; avoid arbitrary module attribute hooks during provenance collection.
- Read stored module dictionaries without executing stdlib LazyLoader code or proxy type hooks in scans and probes; preserve distinct error reasons when normalizing known trial paths.
- Add an incident-derived `Sentinel` reproduction using pinned upstream `typing_extensions` sources, licences and checksums. This is not an original Speckle installation test.
- Add cross-platform core CI, Blender integration workflows, checked release assets and reproducible archive validation/recovery tooling.
- Add contribution, security, case-evidence and release documentation.

The integrated core passed 93 unit checks. On Linux with Blender 4.5.15 LTS, the
extension passed validation and install/enable/scan/uninstall; generated shared-wheel
and settings-sensitive reproductions passed. The actual native workflow verified
saved/live identity, history comparison, support-bundle pairing and unchanged
original files/settings. The incident-derived case reproduced both order outcomes
and reconfirmed the failing pair. Exact evidence is in [VERIFICATION](docs/VERIFICATION.md).

Windows/macOS native runtime and Blender 5.x remain unverified. Hosted CI results
must be read from the actual run; workflow files alone are not platform evidence.

## 0.2.0

- Compare supplied package versions by owner beside captured import paths.
- Jump from a comparison into the full searchable import inventory.
- Test registration with a snapshot of current stored AddonPreferences, including unsaved edits.
- Preserve a settings identity across reduced trials while omitting raw snapshots from trial exports.
- Show live trial phases, combinations, completed outcomes and the run limit.
- Keep prior result/spec pairing when a later asynchronous job fails.

Validated on Linux with Blender 4.5.15 LTS. Generated fixtures cover a shared-wheel
conflict and a settings-sensitive failure. Windows/macOS and Blender 5.x were not
runtime-validated in that release.

## 0.1.1

- Make every evidence record inspectable and copyable inside Blender.
- Add native add-on/package inventories and scan-time import views.
- Expose individual trial details and remove the twelve-evidence export gate.

## 0.1.0

- Read-only manifests, wheel metadata and cross-owner collision findings.
- Runtime import provenance, copied-profile registration tests and bounded reduction.
- Native Blender panel, CLI and self-contained HTML/JSON reports.
