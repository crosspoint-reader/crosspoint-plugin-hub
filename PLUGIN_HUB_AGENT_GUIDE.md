# Plugin Hub AI Agent Guide

Use this document when asking an AI coding agent to make a CrossPoint plugin repository ready for Plugin Hub.

`PLUGIN_HUB_CONTRACT.md` is authoritative. This guide explains the preferred workflow for producing a maintainable repository that conforms to that contract without changing runtime behavior unnecessarily.

## Understand the two contracts first

CrossPoint firmware can load a manually sideloaded plugin with a browser `plugin.js`, an on-reader `device.json`, or both, without requiring a GitHub repository, release, GitHub topic, or even a manifest. **The repository layout, manifest metadata, explicit installed-file list, and stable-release rules below are Plugin Hub automatic-discovery requirements**, not universal firmware-loader requirements. See [the publishing contract](PLUGIN_HUB_CONTRACT.md) and [upstream SD-plugin docs](https://github.com/itsthisjustin/sd-plugins).

For browser plugins, use the actual firmware-provided `CrossPoint.registerPlugin` API. Available interfaces include `api.relay`, `api.fetchToSd`, `api.writeFile`, `api.pluginFile`, `api.registerAction`, and `api.crypto`; File Manager plugins may also access same-origin file endpoints. Check the [upstream reference](https://github.com/itsthisjustin/sd-plugins/blob/main/.claude/skills/create-plugin/reference.md) for supported shapes and limits: relay response bodies are limited (about 32 KB), relay/fetch do not automatically follow redirects, and `writeFile` is intended for small files.

**Security:** browser plugin JavaScript runs in the device WebUI, not a sandbox, with access to sensitive same-origin device functionality. Review source, do not publish credentials/tokens, and warn users when configuration secrets are persisted on the SD card.

An upstream multi-plugin `catalog.json` is a distribution index, not the same thing as the firmware manifest. In our standalone-repository model, Plugin Hub uses the payload manifest and immutable GitHub Release to generate catalog entries automatically. The generated catalog's remote `base` URL does not belong in the installed plugin manifest.

## Goal

Produce a repository that is easy to maintain, easy to release, and automatically discoverable by Plugin Hub.

Prefer:

- one public GitHub repository per plugin;
- one direct-child payload directory named `<plugin-id>.crosspoint-plugin/`;
- development-only material outside the installable payload;
- an explicit runtime file list in `manifest.json`;
- stable GitHub Releases with immutable version tags;
- capability/API requirements only when they are real hard dependencies.

Do not reorganize the Plugin Hub repository itself using this guide. Plugin Hub is an intentional root-layout exception documented in `PLUGIN_HUB_CONTRACT.md`.

## Canonical target layout

For plugin ID `example-plugin`:

```text
repository-root/
├── .github/                       # optional CI/release workflows
├── docs/                          # optional development documentation
├── tests/                         # optional tests
├── tools/                         # optional build/release tooling
├── README.md                      # optional repository/development README
└── example-plugin.crosspoint-plugin/
    ├── manifest.json              # REQUIRED
    ├── device.json                # at least ONE of device.json/plugin.js REQUIRED
    ├── plugin.js                  # at least ONE of device.json/plugin.js REQUIRED
    ├── README.md                  # RECOMMENDED installable plugin README
    ├── DETAILS.md                 # OPTIONAL
    └── other runtime files...     # OPTIONAL
```

The payload directory stem must exactly match `manifest.json -> name`.

## Agent workflow

1. **Inspect before changing anything.** Identify the files actually required by the installed plugin, existing release automation, tests, generated files, configuration/state files, and any paths assumed by runtime code.
2. **Determine the plugin ID.** Use `manifest.json -> name`. It must be a safe lowercase ID using letters, digits, and hyphens.
3. **Create the payload directory.** It must be a direct child named exactly `<plugin-id>.crosspoint-plugin/`.
4. **Move only installable runtime files into the payload.** Keep tests, CI, screenshots, source-only tooling, package-manager files, build scripts, and development docs at repository root unless the installed plugin truly requires them.
5. **Preserve runtime behavior.** Do not rename installed files, change config locations, alter API requests, or change plugin behavior unless required by the layout change or explicitly requested.
6. **Keep required entry points.** The payload must contain `manifest.json` and at least one of `device.json` or `plugin.js`.
7. **Include an installable README when practical.** It is recommended for maintainability and user documentation, but it is not a Plugin Hub discovery requirement.
8. **Use an explicit `files` array.** List every installed runtime file relative to the payload root. Never prefix entries with `<plugin-id>.crosspoint-plugin/`.
9. **Keep paths safe.** Do not use absolute paths, backslashes, `..`, or path traversal in `manifest.json -> files`.
10. **Update repository tooling.** Adjust tests, packaging, release workflows, generated catalog helpers, and documentation so they reference the payload directory correctly.
11. **Use a three-part version.** `manifest.json -> version` must be `MAJOR.MINOR.PATCH` such as `1.2.0`.
12. **Prepare immutable releases.** A stable GitHub Release tag must match the manifest version, optionally prefixed with `v`.
13. **Do not reuse Release tags.** Every runtime change intended for installed users must receive a new plugin version and new stable Release.
14. **Validate the result.** Run the repository's existing tests/checks, inspect the final diff, and confirm the release snapshot contains the required payload structure.

## Manifest guidance

Prefer an explicit manifest such as:

```json
{
  "name": "example-plugin",
  "title": "Example Plugin",
  "description": "What the plugin does.",
  "author": "Author Name",
  "version": "1.2.0",
  "files": [
    "manifest.json",
    "device.json",
    "plugin.js",
    "README.md"
  ]
}
```

Only include files that need to be installed on the reader.

If the plugin includes optional richer on-device information, add `DETAILS.md` and declare it in `files`.

## Compatibility and capabilities

Design against the current CrossPoint plugin contract documented in `PLUGIN_HUB_CONTRACT.md`.

Use `compatibility` only when the plugin truly requires a firmware family, minimum plugin API, or named capability to function.

Supported fields are:

```json
{
  "compatibility": {
    "firmware_family": ["crosspoint"],
    "plugin_api_min": 1,
    "requires": ["catalog.lists"]
  }
}
```

Do not add `requires` simply because a capability improves presentation. Prefer generic capability/API checks over firmware build-name checks.

Current CrossPoint capability names are:

```text
catalog.lists
catalog.notices
catalog.bundle_install
catalog.version_tracking
catalog.compatibility
catalog.item_details
```

## Catalog plugins

For plugins that use the generic catalog UI:

- use `browse.url` for the plugin's normal catalog feed;
- use `browse.lists_url` when remote named-list navigation is required;
- do not combine embedded `browse.lists` with `browse.lists_url` expecting remote-first behavior, because embedded lists are authoritative;
- use list notices only when user confirmation is appropriate;
- use compatibility requirements only for hard dependencies;
- keep catalog item descriptions concise and use optional details content when richer explanation is useful.

## Automatic Plugin Hub discovery

Before declaring the repository ready, verify:

- [ ] repository is public;
- [ ] GitHub topic `crosspoint-plugin` is present when possible (recommended registration; repository-name discovery is only a fallback);
- [ ] exactly one direct-child directory ends in `.crosspoint-plugin`;
- [ ] its stem exactly matches `manifest.json -> name`;
- [ ] `manifest.json` exists inside it;
- [ ] at least one of `device.json` or `plugin.js` exists inside it;
- [ ] manifest version is three-part numeric `MAJOR.MINOR.PATCH`;
- [ ] every declared `files` entry is safe, relative to the payload, and exists;
- [ ] development-only files remain outside the payload;
- [ ] release/package tooling points at the correct payload root;
- [ ] repository tests/checks pass;
- [ ] a non-draft, non-prerelease GitHub Release will use a tag matching the manifest version.

A normal repository that satisfies this contract does not require a Plugin Hub pull request. Plugin Hub's scheduled catalog refresh evaluates it automatically.

## Exceptional sources

Do not recommend Plugin Hub whitelist exceptions merely because the developer currently uses an unusual repository layout.

Use an exceptional Plugin Hub ingestion path only when there is a real reason the preferred one-plugin-per-repository flow cannot apply, such as a genuine upstream monorepo that publishes `*.crosspoint-plugin.zip` Release assets, an explicitly curated external catalog, or a canonical payload hosted outside GitHub with no suitable repository/catalog source. The last case belongs in `whitelist.json -> direct_plugins`. These paths require Plugin Hub maintainer configuration and are defined in `PLUGIN_HUB_CONTRACT.md`.