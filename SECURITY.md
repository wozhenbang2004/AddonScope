# Security and privacy

AddonScope scans package metadata and can execute trusted add-on registration code
in a fresh Blender process. Its copied profiles are **not an operating-system
security sandbox**. An add-on can access external files, devices and services
with the current user's permissions. Do not use it to investigate untrusted code.

## Sensitive reports

If this repository has GitHub private vulnerability reporting enabled, use the
**Security → Report a vulnerability** entry. Otherwise open a minimal issue asking
for a private reporting channel, without vulnerability details, personal files,
credentials or a working harmful payload. Do not post secrets in an issue or PR.
No dedicated security response time is promised during the alpha.

Describe the affected AddonScope/Blender/OS versions, expected isolation boundary,
observed behavior and a safe minimal reproduction. Distinguish a flaw in
AddonScope from an add-on accessing external paths within its stated permissions.

## Reports and saved diagnostics

Local history can contain absolute paths, environment metadata, add-on identifiers
and captured output. Keep it under your account's control. Exported reports and
support files replace inspected-root and home-directory prefixes by default,
but arbitrary add-on output can still include passwords, tokens, file contents
or other identifying strings. Review an archive before sharing it.

Raw add-on settings snapshots are used for a test and omitted from trial exports.
This does not remove a setting printed by the add-on or included in an exception.
AddonScope does not upload diagnostics or require an analysis account.

## Release scope

Each release names its exact validation scope in [README](README.md) and
[VERIFICATION](docs/VERIFICATION.md). Older alpha
versions may not receive separate fixes. Upgrade to the latest validated release
before reporting a fixed issue; retain evidence if the behavior persists.
