# Cases and evidence

Checked on 2026-10-29. These examples describe evidence strength, not a measured
success rate across the Blender add-on ecosystem.

| Case | What was actually run | What it establishes |
| --- | --- | --- |
| Sentinel import cache | Two minimal add-ons with unmodified upstream `typing_extensions` 4.12.2 and 4.14.0 | A real dependency API difference and process-wide import cache can reproduce the same missing symbol and order sensitivity reported in a community incident. |
| Generated shared wheel | Generated add-ons and generated `scope_tokens` wheels | Shared-wheel selection, failure matching and combination reduction work on controlled input. |
| Character DNA discussion | Primary discussion and maintainer follow-up were read; the original installation was not run | Scene reopening and initialization order can cause failures beyond background registration. |

No original Speckle connector installation or Character DNA scene was executed
for this release. Neither case should be advertised as an end-to-end third-party
compatibility certification.

## Sentinel: an incident-derived minimal reproduction

In [Speckle's Blender 4.5 / connector 3.3.0 discussion](https://speckle.community/t/blender-4-5-and-speckle-3-3-0/21042),
the reported error was a missing `Sentinel` import from `typing_extensions`.
The maintainer identified another add-on's dependency as a likely cause and
recommended testing in isolation. The reporter said a different reload order
resolved the problem. The post does not identify the other add-on, its package
version, or a complete original installation that we can reproduce.

The [official typing_extensions release history](https://github.com/python/typing_extensions/releases/tag/4.14.0)
documents the addition of sentinels in 4.14.0. Our example uses the real upstream
4.12.2 and 4.14.0 modules, pinned by commit, Git blob and SHA256 in
[`sources.json`](../examples/cases/sentinel/sources.json). The adjacent upstream
licenses are retained. The generated add-ons are deliberately small:

1. The older provider places its vendored 4.12.2 on `sys.path` and imports a
   supported symbol, caching that module in `sys.modules`.
2. The newer consumer supplies 4.14.0 and imports `Sentinel`.
3. In a fresh Blender process, each add-on registers on its own.
4. With the older provider registered first, the consumer reads the already
   cached old module and fails its `Sentinel` import.
5. With the consumer first, both register. This is a controlled experiment in
   this example, not an automatic load-order repair recommendation.

Run from the source checkout with Python 3.11+ and a trusted Blender executable:

```bash
python tools/reproduce_case.py --blender /path/to/blender \
  --output artifacts/cases/sentinel
```

The command needs no network or pip install. It verifies pinned source and
license checksums, creates disposable add-ons, runs the empty profile and each
single add-on, checks both orders, reduces and reconfirms the failing pair, and
verifies the original case files were not modified. `scan.html`, `scan.json` and
`evidence.json` record the observed versions, paths, statuses and exceptions.
Generated profiles are removed after each trial. Registration executes trusted
test code; copied profiles are not operating-system sandboxes.

The [checked Linux result](../examples/cases/sentinel/verification-linux.json)
used Blender 4.5.15 LTS: both singles passed, old-first failed, new-first passed,
and five reduction trials confirmed the original ordered pair. Windows/macOS
results require runs on those platforms.

This demonstrates a mechanism consistent with the report. The selected package
versions and add-on code are our test conditions; they are **not known versions
or source code from the reporter's installation**. It does not establish that
current Speckle releases still have this issue, that these versions conflict in
every application, or that reordering is safe for another installation.

## Generated shared-wheel case

```bash
python tests/blender_probe_integration.py --blender /path/to/blender \
  --output artifacts/verification/probe.json
```

This is the fully generated `LegacyToken` / `ModernToken` example. Each extension
works separately, while a higher shared wheel breaks the older import when
combined. It also exercises declared dependency closure and redirected ordinary
configuration writes. The fixture is synthetic; no real add-on author is
associated with it.

## Character DNA: why registration is not the whole workflow

[Poly Hammer discussion 60](https://github.com/orgs/poly-hammer/discussions/60)
describes a face rig failing after reopening a `.blend` file. The user found an
add-on combination after extensive manual isolation, but reinstalling removed
the reproduction. The maintainer then described an initialization-order issue
and reported a fix in Character DNA 0.14.4 on 2026-10-14.

We cannot turn this into a reproducible background-registration claim: the
original profile and scene are unavailable, and the symptom depends on scene
loading and driver evaluation. Keep it as evidence for a future explicit
scene/action reproduction mode. Do not present it as an unresolved current
Character DNA defect.

## Name check

On 2026-10-29, GitHub repository search for `AddonScope in:name` returned no
repositories. Two web search engines were also checked for the exact name plus
Blender, diagnostic, conflict and extension-manager terms. They did not surface
a directly matching Blender diagnostic product. Existing uses of `AddonScope`
include an internal Android UI interface and a Rust type name; these are not
evidence of a Blender product collision. This is a bounded discoverability
check, not a trademark or exhaustive name-availability clearance.
