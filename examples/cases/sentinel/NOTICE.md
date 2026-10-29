# Pinned dependency sources

`vendor/4.12.2/typing_extensions.py` and `vendor/4.14.0/typing_extensions.py`
are unmodified copies from the official `python/typing_extensions` repository.
The adjacent `LICENSE` files retain the upstream Python Software Foundation
license and historical license terms. Exact commits, Git blob IDs and SHA256
checksums are recorded in `sources.json`.

These files are test-case dependencies in the source distribution, not vendored
dependencies of the installed AddonScope extension. The small generated add-ons
and reproduction runner are AddonScope test code. No Speckle connector code is
included or executed. This example is derived from a documented incident; it is
not a reproduction of the reporter's complete original installation.
