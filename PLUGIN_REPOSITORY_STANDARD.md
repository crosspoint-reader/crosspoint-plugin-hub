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

A newly discovered plugin is published in **Community Plugins** unless maintainers explicitly classify that plugin ID and trusted source as Official in `catalog-policy.json`. Repository ownership does not determine Official status.

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

`compatibility` is optional. **If it is omitted, Plugin Hub does not restrict the plugin and compatible firmware will display it normally.** Add it only when the plugin actually depends on a particular firmware family, firmware implementation, plugin API level, or named capability.

Supported restrictions are:

- `firmware_family`: one or more compatible families. Stock CrossPoint uses `crosspoint`. A compatible fork can keep the `crosspoint` family.
- `firmware`: one or more exact firmware IDs. Stock CrossPoint uses `crosspoint`; a fork can use its own ID when a plugin depends on fork-only behavior.
- `plugin_api_min`: minimum numeric plugin API level required.
- `requires`: capabilities that the firmware must advertise; every listed capability must be present.

String fields may be written as a single string, a comma-separated string, or a JSON string array. Plugin Hub validates and normalizes them when building its catalogs. A catalog-capable firmware silently omits an entry when any declared restriction does not match. Missing individual restrictions impose no requirement.

Paths in `files` are relative to the payload directory, not the repository root. Do not prefix entries with `<plugin-id>.crosspoint-plugin/`.

Every file required by the installed plugin should be declared in `files`. If `files` is omitted, Plugin Hub falls back to the conventional payload files `manifest.json`, `device.json`, `plugin.js`, and `README.md` when present. Unsafe paths are rejected.

When a released payload declares and contains `DETAILS.md`, Plugin Hub may convert its safe Markdown subset (headings, paragraphs, lists, bold, and italics) to bounded semantic HTML during catalog generation. The generated catalog adds an optional `details` object with an HTML URL. This metadata is additive: older firmware ignores it, and newer firmware falls back to the normal description/author/version/repository view if the rich page is unavailable. Do not make `catalog.item_details` a hard compatibility requirement unless the plugin truly cannot function without that presentation feature.

Development-only files outside the payload directory are never installed.

## Dual-mode plugins and progressive enhancement

New plugins should be designed so the same package can run on the current CrossPoint plugin system **and** take advantage of richer firmware capabilities when they are available. This is the preferred authoring model when a useful baseline experience can be provided without the newer capability.

The rule is simple:

1. Put a complete baseline experience in the fields current CrossPoint already understands.
2. Add enhanced fields beside that baseline instead of creating a second fork-specific plugin whenever possible.
3. Older firmware may ignore fields it does not understand; capable firmware can consume them and provide the richer experience.
4. Use `compatibility.requires` only when the plugin truly cannot function without a named capability. Do **not** use `requires` merely because the plugin becomes nicer when that capability exists.
5. Prefer capability-based behavior over firmware-name checks. A future CrossPoint release or another compatible fork should be able to gain the same enhancement by implementing the same capability.

This lets one repository, one Release, one plugin ID, and one installed payload serve multiple firmware generations.

### Baseline + enhanced catalog pattern

For a catalog plugin, the most important dual-mode pattern is to keep both a static list snapshot and a dynamic list index:

```json
{
  "title": "Example Plugin v1.0.0",
  "browse": {
    "format": "json",
    "url": "https://example.org/catalog/latest/{page}.json",
    "items": "items",
    "page_size": 16,
    "fields": {
      "title": "title",
      "id": "id",
      "url": "url",
      "thumbnail": "thumbnail"
    },
    "lists": [
      {
        "title": "Latest",
        "url": "https://example.org/catalog/latest/{page}.json"
      },
      {
        "title": "Popular",
        "url": "https://example.org/catalog/popular/{page}.json"
      }
    ],
    "lists_url": "https://example.org/catalog/index.json"
  },
  "author": "Author Name",
  "version": "1.0.0"
}
```

Expected behavior:

- current/basic CrossPoint uses the embedded `browse.lists` snapshot;
- capable firmware prefers `browse.lists_url` and can receive new/removed/renamed lists without a plugin update;
- if the remote list index fails, capable firmware can fall back to the embedded static lists;
- `browse.url` remains the baseline catalog/fallback request and should still be valid on its own.

The embedded list snapshot is intentionally less dynamic. If a new category is created later, basic firmware will not see that **new navigation entry** until the plugin is updated. The contents of already-known catalog URLs can still change live. Enhanced firmware using `lists_url` can discover the new category immediately.

When catalogs are generated by tooling, generate `browse.lists` and the remote list index from the same source data so they do not drift.

### Optional enhanced presentation

A dual-mode `device.json` may also carry richer presentation/configuration fields for firmware that understands them, while keeping the baseline browse/download contract intact. Examples currently used by the enhanced firmware work include:

- declarative plugin tabs and settings (`ui`, `settings`, `{cfg.KEY}` values);
- grid/list presentation controls;
- catalog thumbnails and image previews;
- per-list notices;
- catalog/image caching and cache seeds;
- compatibility filtering;
- bundle installation and installed-version tracking.

Do not assume every firmware implements every field. The baseline path should remain useful when those fields are ignored. If an enhancement is only optional, leave it out of `compatibility.requires`.

### Capability-aware hard requirements

Current capability-aware firmware can advertise named plugin-system capabilities. The Razor-Crest reference implementation currently exposes capability names including:

- `catalog.lists`
- `catalog.notices`
- `catalog.bundle_install`
- `catalog.version_tracking`
- `catalog.compatibility`
- `catalog.images`
- `catalog.cache`

These names describe generic plugin-system features, not Plugin Hub-specific behavior. Any plugin may use them.

Use them as hard requirements only when absence of the feature makes the plugin unusable. Example:

```json
{
  "compatibility": {
    "firmware_family": ["crosspoint"],
    "plugin_api_min": 1,
    "requires": ["catalog.images"]
  }
}
```

A plugin that can fall back to a text list should **not** require `catalog.images` simply because capable firmware can show thumbnails.

Firmware-aware request templates may use these values when a remote service needs to adapt its response:

```text
{firmware_family}
{firmware_id}
{firmware_version}
{plugin_api}
{plugin_capabilities}
```

Prefer these generic identity/capability values over special-casing one fork name.

### Reference implementation: Wallpaper Downloader

[Wallpaper Downloader](https://github.com/jadehawk/wallpapers.crosspoint-plugin) is the reference dual-mode example. Version `0.1.1` was physically tested with the **same installed plugin package** on both current CrossPoint `develop` and Razor-Crest:

- basic CrossPoint shows the embedded category/catalog picker and standard list UI;
- Razor-Crest uses the live `lists_url`, grid/list views, thumbnails, preview, settings, cache, and downloaded-state enhancements;
- both firmwares use the same `manifest.json`, `device.json`, plugin version, and Release.

See the tested [`device.json`](https://github.com/jadehawk/wallpapers.crosspoint-plugin/blob/v0.1.1/wallpapers.crosspoint-plugin/device.json) and [`tools/build_catalog.py`](https://github.com/jadehawk/wallpapers.crosspoint-plugin/blob/v0.1.1/tools/build_catalog.py) for a production example of keeping the static baseline lists and dynamic enhanced index generated from the same source.

When starting a new plugin, use this architecture as the default template whenever a meaningful baseline experience is possible.

## GitHub Release requirements

1. Add the repository topic `crosspoint-plugin`.
2. Publish a non-draft, non-prerelease GitHub Release.
3. Use a Release tag matching the manifest version, optionally prefixed with `v`, such as `v1.2.0`.
4. At that exact tag, `<plugin-id>.crosspoint-plugin/manifest.json` must declare the same version.
5. Publish a new version and Release for every runtime change that installed users should receive. Do not move or reuse an existing Release tag.

Plugin Hub publishes automatically discovered repositories from the immutable Release tag, not from `main`.

The generated catalog `base` points directly at the payload directory. Catalog `files` entries remain relative to that payload root.

## What happens after release

Plugin Hub's catalog workflow runs every three hours and can also be started manually. It discovers eligible repositories, validates the Release and payload directory, and publishes valid non-Official plugins in the Community catalog.

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
- an exceptional repository that cannot use automatic discovery;
- a maintainer-approved change to Official catalog policy.

These cases are configured in `whitelist.json` and/or `catalog-policy.json` as appropriate.

## Official versus Community

**Community** is the default classification for valid automatically discovered third-party plugins.

**Official** is explicit curation. An Official policy entry identifies both the plugin ID and its trusted source. If another repository claims the same Official ID, it cannot replace the trusted Official entry. Ambiguous duplicate Community IDs fail the catalog refresh instead of being resolved silently.

The generated `catalog.json` remains a compatibility union of Official and Community, but new Plugin Hub interfaces present the two catalogs separately.
