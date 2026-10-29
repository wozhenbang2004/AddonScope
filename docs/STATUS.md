# AddonScope release status

Current release: 0.3.0 Alpha. The implemented scope is read-only dependency
inspection, observed import provenance, copied-profile registration probes,
settings-sensitive reproduction, bounded reduction, explicit saved diagnostics,
environment comparison and portable support bundles.

The full diagnostic snapshot remains inspectable inside Blender. Saved snapshots
are labelled historical and cannot launch tests against old paths. Tests retain
their original settings identity, timeout and run budget. Support archives omit
raw preference snapshots and contain one matching scan/result pair.

Local release validation: 93 core tests passed; actual Blender 4.5.15 Linux
archive validation, install/enable/scan/uninstall, shared-wheel and settings
reproduction passed. The native GUI completed history comparison, safe return to
the current scan, failure reduction and support export. Original test installations
and settings remained unchanged. See [verification](VERIFICATION.md).

The Sentinel case uses pinned upstream dependency sources to reproduce a known
class of reported failure. It does not run the original Speckle connector.

Hosted Actions and Windows/macOS Blender checks are pending the first repository
runs. Future scene/actions, order experiments and ABI diagnostics are described
in the [roadmap](ROADMAP.zh-CN.md). No universal compatibility, stable-release,
community adoption or Star-growth claim is made.

Continue from the release checklist and hosted CI results. Preserve non-importing
scans, copied installations, original registration order, three-state outcomes and
fresh final failure confirmation while resolving real platform feedback.
