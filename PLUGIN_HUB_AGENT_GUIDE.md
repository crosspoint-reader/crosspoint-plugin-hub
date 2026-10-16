# Plugin Hub AI Agent Guide

Use this document when asking an AI coding agent to make a CrossPoint plugin repository compatible with Plugin Hub automatic discovery.

## Goal

Organize the repository without changing the plugin's runtime behavior.

Plugin Hub's preferred standard is:

- one public GitHub repository per plugin;
- one direct child payload directory named `<plugin-id>.crosspoint-plugin/`;
- development files remain outside that payload directory;
- the payload directory contains every file that must travel with and be installed with the plugin.

Treat this as the default publishing architecture, not merely one option among equals. If a source repository contains several CrossPoint plugins, prefer isolating each plugin into its own standards-compliant repository. Do not recommend Plugin Hub's release-asset monorepo exception merely because the developer currently keeps several plugins together; that path exists for genuine upstream monorepo constraints and requires maintainer approval.

## Required result

For a plugin whose ID is `example-plugin`, produce this shape:

```text
repository-root/
├── .github/
├── docs/
├── tests/
├── tools/
├── README.md                     # optional repository/development README
└── example-plugin.crosspoint-plugin/
    ├── manifest.json
    ├── device.json               # at least device.json or plugin.js is required
    ├── plugin.js
    ├── README.md                 # plugin README; this travels with the plugin
    └── other runtime files...
```

Do not move tests, CI workflows, source-only tooling, screenshots, build scripts, package-manager metadata, or other development-only material into the plugin payload unless the installed plugin actually needs it.

## Rules

1. Inspect the repository before changing anything. Identify which files the installed CrossPoint plugin actually uses.
2. Determine the plugin ID from `manifest.json -> name`. If `name` is missing, add a safe lowercase ID using only letters, digits, and hyphens.
3. Create a direct child directory named exactly `<manifest.name>.crosspoint-plugin/`.
4. Move the installable plugin payload into that directory.
5. The payload must contain `manifest.json` and at least one of `device.json` or `plugin.js`.
6. The plugin's README belongs inside the payload directory so it travels with the plugin.
7. Keep repository/development material outside the payload directory.
8. `manifest.json -> version` must be `MAJOR.MINOR.PATCH`, for example `1.2.0`.
9. Prefer an explicit `manifest.json -> files` array listing every installed runtime file. Paths are relative to the payload directory. Never prefix them with `<plugin-id>.crosspoint-plugin/`.
10. Nested runtime paths such as `assets/icon.png` or `lib/api.js` are allowed when declared in `files`.
11. Do not use absolute paths, backslashes, `..`, or other traversal paths in `files`.
12. Update repository-owned catalog or release tooling so its `base` points at the payload directory and its file list stays relative to that payload root.
13. Update tests, packaging workflows, and release workflows to use the new payload path.
14. Preserve the plugin's installed destination name and runtime behavior unless the user explicitly asks for behavioral changes.
15. Run the repository's existing validation/tests after reorganizing it and show the resulting Git diff before release.

## Capability-aware plugin design

When creating a new plugin or materially revising `device.json`, design against the CrossPoint plugin contract rather than a specific firmware build name. Prefer the dual-mode / progressive-enhancement model documented in `PLUGIN_REPOSITORY_STANDARD.md` when a useful baseline is possible.

Agent rules:

1. Preserve a complete baseline path using fields understood by older plugin-enabled firmware.
2. Add optional current-contract fields beside the baseline so current CrossPoint can provide richer behavior without requiring a separate plugin package.
3. For catalog plugins, keep `browse.url` as a complete baseline and add `browse.lists_url` only when dynamic named lists are needed. Do not ship embedded `browse.lists` beside `browse.lists_url` expecting remote-first behavior: embedded lists are authoritative.
4. If `browse.lists_url` is used, keep the `browse.url` catalog fully usable for firmware that ignores the newer field. Do not assume the native list-index path automatically falls back if the remote index fails.
5. Use `compatibility.requires` only for a **hard dependency** that makes the plugin unusable when absent. Do not require a capability merely because it improves presentation.
6. Prefer generic firmware capabilities and plugin API levels over firmware-version or build-name checks.
7. Treat unknown fields as optional progressive enhancements unless the CrossPoint plugin contract explicitly requires otherwise.
8. Keep the baseline experience useful even when optional notices, compatibility filtering, rich item details, or dynamic lists are unavailable.

Before creating a firmware-specific plugin package, first determine whether one package can provide a reasonable baseline and progressively enhance on current CrossPoint.

## Release contract

For automatic Plugin Hub discovery:

- add the GitHub topic `crosspoint-plugin`;
- publish a non-draft, non-prerelease GitHub Release;
- the Release tag must match the payload manifest version, optionally prefixed with `v`;
- the released repository snapshot must contain `<plugin-id>.crosspoint-plugin/manifest.json`;
- publish a new version for every runtime change users should receive;
- do not move or reuse an existing Release tag.

Plugin Hub reads automatic-discovery plugins from the immutable Release tag, not from `main`.

## Validation checklist

Before declaring the repository Plugin Hub-ready, verify all of the following:

- [ ] exactly one direct child directory ends with `.crosspoint-plugin`;
- [ ] its directory stem exactly equals `manifest.json -> name`;
- [ ] `manifest.json` exists inside it;
- [ ] at least one of `device.json` or `plugin.js` exists inside it;
- [ ] the plugin README exists inside it;
- [ ] the manifest version is three-part numeric semver;
- [ ] every declared `files` path is relative to the payload directory and safe;
- [ ] every declared runtime file actually exists;
- [ ] development-only files remain outside the payload;
- [ ] release/catalog tooling points at the payload directory;
- [ ] existing tests pass after the move;
- [ ] a new or materially revised plugin has been checked for a usable basic-CrossPoint fallback;
- [ ] optional enhanced behavior does not incorrectly appear in `compatibility.requires`;
- [ ] catalog plugins that can be dual-mode keep a complete `browse.url` baseline and add `browse.lists_url` only when dynamic named-list navigation is needed; do not combine it with embedded `browse.lists` expecting remote-first behavior.

## Plugin Hub repository exception

Do not reorganize `jadehawk/PluginHub.crosspoint-plugin` using these steps.

Plugin Hub itself intentionally remains a root-layout exception because its firmware bootstrap, root-generated catalogs, and production `stable` branch already depend on those paths. This exception is specific to Plugin Hub and is not the model for new plugins.
