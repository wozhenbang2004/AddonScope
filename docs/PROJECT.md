# AddonScope

Goal: shorten the path from "these add-ons work separately" to a reproducible,
evidence-bearing conflict report that an add-on maintainer can use.

Scope: read-only manifests and package metadata; cross-owner version and module
collisions; actual import sources; copied-profile registration tests, stored
add-on settings and bounded failure reduction; explicit diagnostic history and
comparison; native inspection, CLI, offline reports and support bundles.

Non-goals: universal DLL isolation, malicious-code sandboxing, dependency
installation, automatic repairs, changing the original load order, cloud accounts
or an LLM service.

Architecture: portable dataclasses → static scanner → comparison/native UI/report.
Probe jobs run an explicit Blender executable with disposable profile directories
and copied add-on files. History files contain validated data only. Support ZIPs
contain evidence without add-on sources or raw preference snapshots. Core modules
import without bpy. Python 3.11+; the extension targets Blender 4.5 LTS. Supported
platform claims follow actual validation in docs/VERIFICATION.md.

Release conditions: passing core checks, real host installation and removal,
repeatable copied-profile failures, viewed native journeys, safe evidence exports,
byte-identical rebuilds and independently restored source archives. The roadmap
in docs/ROADMAP.zh-CN.md separates this Alpha from future capability claims.
