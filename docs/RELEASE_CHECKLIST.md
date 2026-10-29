# Release checklist

This is the sign-off record for 0.3.0 Alpha. Checked rows have local 0.3 evidence.
Remaining publication checks stay open until the final assembled assets and
hosted runs are available. A passing older version is not a current result.

## Required before a public tag

- [x] Version agrees across the Python package, Blender manifest, extension metadata and release filenames.
- [x] Core unit checks pass on the integrated source tree.
- [x] Actual Blender shared-wheel and settings-sensitive integration checks pass.
- [x] Setup, collection and registration failures are classified by the phase that actually failed.
- [x] Original inspected files and settings stay unchanged in the tested workflows.
- [x] Final extension ZIP passes Blender validation and actual install/enable/scan/uninstall.
- [x] Current native UI is inspected: comparison/import navigation, probe controls, progress, failure details, saved/live identity and history comparison.
- [x] History save/load and current-environment comparison pass, including stale-data labels and invalid input recovery.
- [x] Support ZIP opens independently, defaults to path redaction, omits source/settings snapshots and contains the promised records.
- [x] HTML report and screenshot-review navigation work at desktop and narrow widths.
- [x] Source archive restores in a clean directory and runs the documented core checks.
- [x] No credentials, original personal configuration, caches or private fixture files enter source or release assets.
- [x] Third-party licenses/notices are retained; copied cases state their source, version and permission.
- [x] README, changelog, screenshots, platform matrix and documented commands match the final implementation.
- [x] Repository CI/workflow files are validated; actual hosted-run status is recorded separately.
- [x] The independent review has no unresolved release-blocking issue.

## Platform matrix

| Platform | Core Python checks | Actual Blender runtime | Release claim |
| --- | --- | --- | --- |
| Linux x86_64 | Integrated 93 unit checks passed | 0.3 passed Blender 4.5.15 background integration and native workflow | Validated within documented registration scope |
| Windows | Pending hosted CI | Not yet verified | Experimental / unverified |
| macOS | Pending hosted CI | Not yet verified | Experimental / unverified |
| Blender 5.x | Not a substitute for runtime | Not yet verified | Not claimed |

A hosted Python matrix result is not a native Blender result. Record the precise
OS, Blender build, commit/package and tested actions when upgrading a platform claim.

## Local evidence recorded

The 0.3.0 integrated tree passed 93 core checks. The local evidence entry points
are `artifacts/release-integration/summary.json` (archive validation,
install/enable/scan/uninstall, shared-wheel reduction and settings snapshot) and
`artifacts/review/native-release/checks.json` (actual native workflow, original
files/settings, saved/live identity, history after restart and paired support ZIP).
The pinned incident-derived case is documented in [CASES](CASES.md).

Release-tag validation was independently exercised for its supported success and
failure paths after its HTTP-error handling correction. This is a local workflow
check; hosted GitHub Actions status is still pending. Source recovery, archive privacy/content inspection, screenshot HTML checks and
independent sign-off passed locally. Hosted runs and publication remain pending.

## Evidence to record at sign-off

Record final version/commit, extension/source filenames and SHA256 values;
commands and exit outcomes; native screenshots; actual CI run links; skipped
checks and known restrictions. Use [VERIFICATION](VERIFICATION.md) as the evidence
entry point. Do not attach private diagnostic history to the release.

## Publication

Create an alpha prerelease only after the required rows pass or an explicitly
narrower release scope is documented. Attach the extension ZIP, source archive
and checksums. Test the download/install path. A public repository does not mean
all experimental platforms are supported.

Do not mark community adoption, real third-party end-to-end reproduction or
measured troubleshooting improvement complete without independent evidence.
