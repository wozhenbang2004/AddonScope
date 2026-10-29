# Verification — 0.3.0 Alpha

Checked on 2026-10-29. Local host: Linux x86_64, Python 3.12.14 and official
Blender 4.5.15 LTS, build `5afeabba6097`. Platform claims below reflect executed
checks, not the availability of CI configuration.

## Core and archives

`python -m unittest discover -s tests -q`: **93 tests passed** on the integrated
source. Coverage includes static non-importing scans, Python wheel targets and
requirements, safe archive parsing, import provenance, copied-profile execution,
three-state outcomes, failure identity, cancellation, stored settings, history
validation, comparison, redaction and support-bundle contents.

`python tools/check_release.py --rebuild --restore-test --expect-tag v0.3.0`
checks matching versions, exact archive contents, retained licenses, fixed ZIP
metadata, checksums, byte-identical repeated builds and tests from a freshly
extracted source archive. The final archives passed these checks before publication.

## Actual Blender host

`python tools/run_blender_checks.py --blender /path/to/blender --output artifacts/release-integration`
completed archive validation and installation/activation/scanning/removal of the
built extension. Three generated wheel fixtures each passed alone, failed as a
combination, and six trials reconfirmed the two-owner conflict. Declared dependency
closure and common configuration redirection remained intact; original files were
unchanged.

The settings fixture passed with defaults and failed with copied bool, string,
integer, vector, nested PropertyGroup and populated/empty CollectionProperty
values. The retained settings-sensitive subset was confirmed in a fresh process.
Raw settings were absent from exported results, and originals were unchanged.
Native scan and probe regressions use Python's actual stdlib LazyLoader plus
attribute-intercepting proxies. They verify that collecting stored import paths
does not execute deferred code or access proxy hooks. These tests exposed and
fixed the earlier `vars(module)` and `isinstance` side effects.

A separate real-host adversarial test gives the complete set and a smaller
subset different error reasons following the same temporary path. Both reasons
remain distinct after path normalization; reduction retains the original failure
instead of confirming the unrelated subset. Registration and collection phases
remain distinct when classifying process exits.

## Native journey

`tests/blender_release_ui.py` ran in the real Blender GUI. It checked:

- Complete dependency comparison and observed import navigation.
- A 12-second trial timeout and eight-run reduction budget, including final confirmation.
- Explicit wording that confirmation means a reproduced failure.
- Saved history and an actual generated manifest update from 1.0.0 to 1.1.0.
- Full before/after records, historical identity, and disabled historical probes.
- Returning to the current scan with the original selection/search restored.
- Opening saved history after native re-registration and before any new scan.
- A support ZIP with four readable files and a matching archived scan/result pair.
- Original add-on directories and settings unchanged apart from the deliberately
  performed fixture manifest update.

Current review screenshots show generated test add-ons in the actual application,
not community installations or fabricated UI. HTML exports remain optional.

## Sourced reproduction

`python tools/reproduce_case.py --blender /path/to/blender --output artifacts/cases/sentinel`
uses unmodified pinned typing_extensions 4.12.2 and 4.14.0 sources. Each generated
add-on passes alone. Loading the older dependency first fails to import Sentinel;
reversing the order passes. Five trials retain and reconfirm the failing pair.
Sources and original case files remain unchanged.

This is an incident-derived minimal reproduction. No original Speckle connector
was installed or executed. Sources and boundaries are in [CASES](CASES.md).

## Independent checks

Cross-module review reproduced and verified fixes for lost trial limits,
malformed historical records, stale/current pairing, and unknown nested metadata
entering support exports. Unsupported or damaged records are rejected without
preventing valid history from being listed. Logs may still contain private output
emitted by inspected add-ons; path redaction is not a general privacy filter.

Adversarial reduction checks covered a single broken add-on, independent failures,
order-sensitive and non-monotonic outcomes, declared dependencies and a passing
final confirmation. Reduction follows the first failure only. It may retain the
original set when candidates are unresolved, does not prove global minimality,
and one final confirmation is not a statistical test for intermittent failures.

Release automation review checked missing/same/mismatched and annotated tag
conditions, permissions, input handling, fixed action refs, downloader checksums
and generated Linux-tar/Windows-ZIP extraction tests. These are local checks;
hosted Actions and actual Windows/macOS Blender results are recorded separately.

## Portable report and screenshot review

The current report passed actual Headless Shell checks at 1280px, 760px and
1440px: navigation, filters/recovery, inventory, JSON download, literal HTML
escaping, empty results and no external requests. The seven-image native review
HTML passed selection, zoom and 1280px/390px layout checks.

## Pending platform evidence

Windows/macOS Blender startup and interaction, Blender 5.x, third-party complete
installations, scene/viewport actions and native DLL/SO conflict isolation remain
unverified. Core Python CI on those systems does not substitute for Blender
runtime validation. No performance, adoption or troubleshooting success rate is
claimed from the fixtures.
