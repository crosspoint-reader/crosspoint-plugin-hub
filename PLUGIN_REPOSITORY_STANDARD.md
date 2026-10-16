# CrossPoint Plugin Repository Standard

This document defines the repository layout Plugin Hub expects for automatically discovered CrossPoint plugins. It is a Plugin Hub publishing convention, not a firmware requirement.

## Preferred publishing path

Use **one public GitHub repository per plugin**.

The installable CrossPoint payload must live inside one direct child directory named:

```text
<plugin-id>.crosspoint-plugin/
```

This keeps development files, tests, screenshots, build tooling, CI configuration, documentation sources, and other repository-only content separate from the files that Plugin Hub installs on a reader.

A normal standards-compliant plugin does **not** need a Plugin Hub pull request. Add the `crosspoint-plugin` GitHub topic and publish a stable GitHub Release; Plugin Hub's scheduled discovery will evaluate it automatically.

This is the normal self-service ingress path and should be used whenever reasonably possible. Plugin Hub should not require maintainer-side exceptions simply to accommodate a developer's preferred repository organization. If several CrossPoint plugins can be isolated into separate repositories, authors are expected to do that rather than request monorepo configuration in Plugin Hub.

A newly discovered valid plugin is published in **Community Plugins**. Repository ownership does not create a separate trust classification.

## Required repository shape

A typical repository should look like this:

```text
example-plugin/
├── .github/
├── docs/
├── tests/
├── tools/
├── README.md                  # optional repository/development documentation
└── example-plugin.crosspoint-plugin/
    ├── manifest.json
    ├── device.json            # at least device.json or plugin.js is required
    ├── plugin.js
    ├── README.md              # installable plugin README
    ├── DETAILS.md             # optional curated on-device Details content
    └── assets/
        └── icon.png
```

Plugin Hub only treats the direct child `*.crosspoint-plugin/` directory as the installable payload. Repository-root development files are ignored.

The payload directory must contain `manifest.json` and at least one runnable CrossPoint entry point:

```text
device.json
plugin.js
```

Both entry points may be present.

The plugin README should travel with the plugin and therefore belongs inside the payload directory. Additional runtime files and nested runtime directories are allowed when they are declared in `manifest.json -> files`. Authors may also include an optional `DETAILS.md` beside it for concise, reader-focused content; declare it in `manifest.json -> files` so the file ships with the installed plugin.

Automatic discovery currently expects exactly one root-level `*.crosspoint-plugin/` payload directory per repository. The preferred standard remains one repository per plugin.

## Payload directory naming

The directory stem must exactly match the plugin ID declared by `manifest.json`:

```text
example-plugin.crosspoint-plugin/
```

```json
{
  "name": "example-plugin"
}
```

Plugin IDs use lowercase letters, digits, and hyphens.

## Manifest requirements

`manifest.json` must contain a safe plugin ID and a three-part numeric version. A typical manifest is:

```json
{
  "name": "example-plugin",
  "title": "Example Plugin",
  "description": "What the plugin does.",
  "author": "Author Name",
  "version": "1.2.0",
  "compatibility": {
    "firmware_family": ["crosspoint"],
    "plugin_api_min": 1
  },
  "files": [
    "manifest.json",
    "device.json",
    "plugin.js",
    "README.md",
    "DETAILS.md",
    "assets/icon.png"
  ]
}
```

Versions must use `MAJOR.MINOR.PATCH`, for example `1.2.0`.

`compatibility` is optional. **If it is omitted, Plugin Hub does not restrict the plugin and compatible firmware will display it normally.** Add it only when the plugin actually depends on a particular firmware family, plugin API level, or named capability.

Supported restrictions are:

- `firmware_family`: one or more compatible families. CrossPoint uses `crosspoint`.
- `plugin_api_min`: minimum numeric plugin API level required.
- `requires`: capabilities that the firmware must advertise; every listed capability must be present.

String fields may be written as a single string, a comma-separated string, or a JSON string array. Plugin Hub validates and normalizes them when building its catalogs. A catalog-capable firmware silently omits an entry when any declared restriction does not match. Missing individual restrictions impose no requirement.

Paths in `files` are relative to the payload directory, not the repository root. Do not prefix entries with `<plugin-id>.crosspoint-plugin/`.

Every file required by the installed plugin should be declared in `files`. If `files` is omitted, Plugin Hub falls back to the conventional payload files `manifest.json`, `device.json`, `plugin.js`, and `README.md` when present. Unsafe paths are rejected.

When a released payload declares and contains `DETAILS.md`, Plugin Hub may convert its safe Markdown subset (headings, paragraphs, lists, bold, and italics) to bounded semantic HTML during catalog generation. The generated catalog adds an optional `details` object with an HTML URL. This metadata is additive: older firmware ignores it, and newer firmware falls back to the normal description/author/version/repository view if the rich page is unavailable. Do not make `catalog.item_details` a hard compatibility requirement unless the plugin truly cannot function without that presentation feature.

Development-only files outside the payload directory are never installed.

## Dual-mode plugins and progressive enhancement

New plugins should be designed so the same package can provide a useful baseline on older plugin-enabled firmware and use the current CrossPoint plugin contract when available. This is the preferred authoring model when a meaningful baseline experience is possible.

The rule is simple:

1. Put a complete baseline experience in broadly supported plugin fields.
2. Add current CrossPoint contract fields beside that baseline instead of creating a firmware-specific package whenever possible.
3. Older firmware may ignore fields it does not understand; current CrossPoint can consume them and provide the richer experience.
4. Use `compatibility.requires` only when the plugin truly cannot function without a named capability. Do **not** use `requires` merely because the plugin becomes nicer when that capability exists.
5. Prefer capability-based behavior over firmware-version or build-name checks so future CrossPoint releases can provide the same enhancement through the same capability.

This lets one repository, one Release, one plugin ID, and one installed payload serve multiple firmware generations.

### Baseline + enhanced catalog pattern

For a catalog plugin, keep a complete `browse.url` baseline and add enhanced
navigation only when firmware can use it. With the firmware contract associated
with Plugin Hub 0.1.6, `browse.lists_url` is loaded only when embedded
`browse.lists` is absent. Do **not** combine both fields expecting remote-first
behavior or automatic fallback.

```json
{
  "title": "Example Plugin v1.0.0",
  "browse": {
    "format": "json",
    "url": "https://example.org/catalog/all.json",
    "items": "items",
    "page_size": 16,
    "fields": {
      "title": "title",
      "id": "id",
      "url": "url",
      "thumbnail": "thumbnail"
    },
    "lists_url": "https://example.org/catalog/index.json"
  },
  "author": "Author Name",
  "version": "1.0.0"
}
```

Expected behavior with the current contract:

- firmware that does not understand `browse.lists_url` ignores it and continues
  through the complete `browse.url` baseline;
- capability-aware firmware with `catalog.lists`, `browse.lists_url`, and no
  embedded `browse.lists` fetches the dynamic named-list index;
- if that remote list index fails, the current native implementation fails the
  named-list browse cleanly; it does not automatically fall back to
  `browse.url` or an embedded snapshot;
- if a plugin instead ships embedded `browse.lists`, current firmware treats
  those lists as authoritative and does not fetch `browse.lists_url`.

Plugin Hub 0.1.6 therefore uses the backward-compatible `catalog.json` union as
its baseline `browse.url` and uses `catalog-lists.json` only for the enhanced
dynamic named-list navigation. This keeps one package usable across firmware
generations without disabling the dynamic shard layout on capable firmware.

### CrossPoint capability-aware presentation

Current CrossPoint firmware advertises these plugin-system capabilities:

- `catalog.lists`
- `catalog.notices`
- `catalog.bundle_install`
- `catalog.version_tracking`
- `catalog.compatibility`
- `catalog.item_details`

These names describe generic plugin-system features, not Plugin Hub-specific behavior. Any plugin may use them.

Use a capability as a hard requirement only when the plugin cannot function without it. For example, a plugin that has no meaningful fallback without dynamic named-list navigation may declare:

```json
{
  "compatibility": {
    "firmware_family": ["crosspoint"],
    "plugin_api_min": 1,
    "requires": ["catalog.lists"]
  }
}
```

A plugin that can fall back to a complete `browse.url` catalog should not require `catalog.lists` merely because current firmware can provide the richer named-list experience.

Firmware-aware request templates may use these values when a remote service needs to adapt its response:

```text
{firmware_family}
{firmware_version}
{plugin_api}
{plugin_capabilities}
```

Prefer these generic identity and capability values over firmware-name checks.

### Generic dual-mode example

A catalog plugin can support older plugin-enabled firmware and current CrossPoint with one package:

- keep a complete `browse.url` baseline;
- add `browse.lists_url` when dynamic named lists are useful;
- attach optional list notices when user confirmation is appropriate;
- declare `compatibility` only for true hard requirements;
- include optional rich `DETAILS.md` content for `catalog.item_details`;
- keep the same `manifest.json`, `device.json`, plugin ID, version, and Release across both paths.

When starting a new plugin, use this architecture whenever a meaningful baseline experience is possible.

## GitHub Release requirements

1. Add the repository topic `crosspoint-plugin`.
2. Publish a non-draft, non-prerelease GitHub Release.
3. Use a Release tag matching the manifest version, optionally prefixed with `v`, such as `v1.2.0`.
4. At that exact tag, `<plugin-id>.crosspoint-plugin/manifest.json` must declare the same version.
5. Publish a new version and Release for every runtime change that installed users should receive. Do not move or reuse an existing Release tag.

Plugin Hub publishes automatically discovered repositories from the immutable Release tag, not from `main`.

The generated catalog `base` points directly at the payload directory. Catalog `files` entries remain relative to that payload root.

## What happens after release

Plugin Hub's catalog workflow runs every three hours and can also be started manually. It discovers eligible repositories, validates the Release and payload directory, and publishes all valid plugins in Community.

No Plugin Hub pull request, whitelist entry, or issue is required for this normal path.

## Plugin Hub repository exception

`jadehawk/PluginHub.crosspoint-plugin` intentionally remains a root-layout exception.

Plugin Hub's own firmware/bootstrap integration and generated catalogs already depend on repository-root paths and on the production `stable` branch. Its payload layout is therefore not being reorganized as part of this standard reset.

This exception is specific to Plugin Hub and should not be copied by new plugins.

## When a Plugin Hub pull request is required

A pull request is required only for publishing paths that need explicit configuration. These are secondary or exceptional ingress paths, not alternatives that plugin authors should choose merely to avoid isolating a plugin into its own repository.

They include:

- a genuine monorepo that cannot reasonably isolate its CrossPoint plugin or plugins and therefore publishes one or more `*.crosspoint-plugin.zip` Release assets;
- a plugin that must temporarily be imported from another catalog;
- an exceptional repository that cannot use automatic discovery.

These cases are configured in `whitelist.json` as appropriate.

## Community catalog

**Community Plugins** is the single user-facing catalog for valid published plugins. Ambiguous duplicate plugin IDs fail the catalog refresh instead of being resolved silently.

The generated `catalog.json` remains a compatibility catalog containing the same published plugin set.
