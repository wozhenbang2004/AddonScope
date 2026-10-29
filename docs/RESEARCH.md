# Mechanism and prior work

Research checkpoint: 2026-10-29. Source descriptions are separated from this
release's observed behavior. This is a coexistence diagnostic tool, not a novel
package solver or a universal sandbox.

## Blender's shared wheel environment

Official sources examined:

- [Extension package implementation](https://github.com/blender/blender/blob/v4.5.15/scripts/addons_core/bl_pkg/readme.rst).
- [Wheel manager](https://github.com/blender/blender/blob/v4.5.15/scripts/modules/_bpy_internal/extensions/wheel_manager.py), especially `wheel_list_deduplicate_as_skip_set`.
- [Extension refresh and add-on enable](https://github.com/blender/blender/blob/v4.5.15/scripts/modules/addon_utils.py).
- [Official command-line add-on activation](https://github.com/blender/blender/blob/v4.5.15/scripts/modules/_bpy_internal/addons/cli.py).
- [User directory overrides](https://github.com/blender/blender/blob/v4.5.15/source/blender/blenkernel/intern/appdir.cc).

Extensions use `bl_ext.<repository>.<id>` namespaces, but their wheel dependencies
are applied to a shared, Python-version-specific `.local/.../site-packages`.
Blender deduplicates wheel distributions by version; that does not solve every
extension's version requirements or isolate top-level Python import names.
`sys.modules` and native libraries are process-wide concerns. Disabling a plugin
does not guarantee that imports, handlers or loaded native code have disappeared.

Consequences: static presence is a candidate finding; an in-process import path
is an observation; a repeatable failed registration is a reproduction. They are
different evidence strengths. Native DLL/SO filename overlap alone cannot prove
an ABI or symbol conflict.

## Community demand and existing tools

- [Speckle discussion](https://speckle.community/t/blender-4-5-and-speckle-3-3-0/21042): a historical `typing_extensions` conflict led to manual add-on isolation. This is evidence of troubleshooting cost, not a claim of an unfixed current Speckle bug.
- [Poly Hammer discussion 60](https://github.com/orgs/poly-hammer/discussions/60): multi-add-on troubleshooting and initialization-order problems. A reported fix already exists; dependencies are only one possible cause.
- [Blender Extension Install Doctor](https://github.com/toastyengi/blender-extension-install-doctor): archive/install linting overlaps some static checks; AddonScope concentrates on multiple installed owners, actual import provenance and controlled combination tests.
- [Peeler](https://github.com/Maxioum/Peeler): helps package wheel dependencies. Packaging automation does not itself diagnose an already-installed coexistence failure.
- [Native symbol conflicts](https://devtalk.blender.org/t/managing-symbol-conflicts-for-python-addons/41342): native loading problems need stronger reproduction than matching filenames. Forum content was only partly retrievable; no implementation promise relies on it.

## Mod-manager analogy

| Prior work | License | Decision and boundary |
| --- | --- | --- |
| [RimCrow](https://github.com/Inky-Feather/RimCrow) | MIT | Reference environment snapshots and troubleshooting. Automatic bisection was still an unchecked roadmap item in the README examined. No source copied. |
| [RimSort](https://github.com/RimSort/RimSort) | GPL-3.0 | Reference rule provenance and dependency explanations. RimWorld load-order rules do not map directly to Python imports. No source copied. |
| [mod-bisect-tool](https://github.com/Qendolin/mod-bisect-tool) | MPL-2.0 | Reference three-state outcomes, dependency closure, fixed context and final confirmation. No source copied or translated. |
| [packaging](https://github.com/pypa/packaging) | Apache-2.0 or BSD-2-Clause | Adopt the installed 26.3 distribution for Python requirements, markers, versions and wheel tags. Original licenses retained; BSD terms selected. |

Qendolin's algorithm documentation and main implementation differed on some
indeterminate branches. AddonScope makes its own bounded reduction contract:
preserve declared dependency closure and original order, retain the failing
module/type/message signature, record unresolved trials, and confirm the final
subset in a new process. It does not promise global minimality, all independent
conflicts, monotonic behavior or the true root cause of every exception.

## Delivery decisions and open branches

Build a small Python core, a native Blender panel and an offline report rather
than a second all-purpose mod manager. Avoid an account system, telemetry, an LLM
API, automatic dependency replacement and automatic load-order repair.

The shipped reproduction fixture uses two generated pure-Python wheels: one
exports LegacyToken, the other ModernToken. Each extension works alone. The
shared higher wheel version breaks the older import when combined. This proves
the diagnostic path on controlled input, not a measured success rate on community
installations. Next useful research is opt-in maintainer reproductions, Windows
DLL cases, interactive repro actions and persistent add-on preferences.

## 0.3 release case: real dependency, incident-derived harness

The [case catalogue](CASES.md) now separates original third-party reproduction,
incident-derived minimal reproduction and generated fixtures. The Speckle
discussion specifically reports `Sentinel`, introduced by typing_extensions
4.14.0 according to its [upstream release](https://github.com/python/typing_extensions/releases/tag/4.14.0).
The reporter says another reload order worked, but does not identify a complete
pair of add-ons or dependency versions. We therefore cannot certify a reproduction
of their original installation.

`tools/reproduce_case.py` instead uses unchanged official typing_extensions 4.12.2
and 4.14.0 sources in two minimal test add-ons. The sources are fixed to commits
`e1250ff869e7ee5ad05170d8a4b65469f13801c3` and
`b07d24525615ba9377e47aaf5a26650a2517b2c4`; blob IDs, SHA256 and original
licenses are retained in `examples/cases/sentinel/`. On Blender 4.5.15 Linux,
both singles register, old-first fails with the reported missing symbol,
new-first registers, and five trials reconfirm the old-first pair. The original
case files remain unchanged. This tests a plausible mechanism with a real
dependency API change; it does not execute Speckle, prove the reporter's root
cause or recommend reordering arbitrary user installations.

Reuse decision: REFERENCE the community failure report; ADOPT the pinned official
dependency sources strictly as offline test inputs; BUILD the minimal harness.
No original connector, paid add-on or private profile is redistributed. The
extension install ZIP does not include these source-distribution case files.

Poly Hammer discussion 60 was reread through its maintainer follow-up: the user
lost the original reliable reproduction after reinstalling, and the maintainer
reported an initialization-order fix in Character DNA 0.14.4 on 2026-10-14. That
case remains an explicit scene/reload limitation, not a background-registration
case or an unresolved current-defect claim.
