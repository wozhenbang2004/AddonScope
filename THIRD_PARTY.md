# Third-party notices

`addon_scope/_vendor/packaging` contains packaging 26.3, copied from the installed
Python distribution. Upstream: https://github.com/pypa/packaging and
https://pypi.org/project/packaging/26.3/. No functional changes were made.
Bytecode caches are excluded. Packaging is available under either Apache-2.0 or
BSD-2-Clause; the original LICENSE, LICENSE.APACHE and LICENSE.BSD are retained.
The BSD terms are used for this distribution.

Blender (https://www.blender.org) is the host application, not included in the
extension. AddonScope is an independent project, not endorsed by Blender.

The source-only Sentinel reproduction includes unmodified typing_extensions
4.12.2 and 4.14.0 source files under their Python Software Foundation licenses.
They are not bundled in the installed extension. Fixed upstream commits, hashes,
copyright notices and the distinction between the historical event and this
minimal reproduction are in examples/cases/sentinel/NOTICE.md and sources.json.

The design of the diagnostic workflow was informed by RimCrow (MIT), RimSort
(GPL-3.0) and Qendolin/mod-bisect-tool (MPL-2.0). Their source code is not copied
or translated into this project. See docs/RESEARCH.md for source links and limits.
