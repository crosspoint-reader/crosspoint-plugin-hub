# Plugin Hub contract

This document is the authoritative contract for publishing plugins through Plugin Hub and for maintaining Plugin Hub's generated catalogs against the current CrossPoint SD-plugin system.

The SD-plugin system has not yet shipped in a stable CrossPoint release. This document therefore defines one current contract. It does not describe legacy plugin-system generations or require compatibility with an older released plugin API.

## Firmware support versus Plugin Hub publishing

**Firmware support:** CrossPoint can load manually installed plugins from `/.crosspoint/plugins/<name>/`, `/plugins/<name>/`, or `/.plugins/<name>/`. A plugin may include `plugin.js` for the browser WebUI, `device.json` for on-reader browsing, or both. The firmware does not require a GitHub repository, a Release, a GitHub topic, or even a manifest for basic manual installation.

**Plugin Hub publishing:** Automatic discovery adds separate rules for reproducible installation and updates: the public repository, one direct-child payload folder, valid manifest and metadata, and an immutable stable GitHub Release. Requirements in the sections below describe **automatic Plugin Hub publication**, not every firmware-loadable plugin. [local firmware plugin API reference](docs/firmware-plugin-api.md) explains the baseline firmware behavior.

### Firmware browser plugin APIs and limitations

A browser `plugin.js` registers with `CrossPoint.registerPlugin((container, api) => { ... })`. Firmware exposes methods such as `api.relay(method, url, headers, body)` for device-mediated HTTP(S), `api.fetchToSd(url, dest, headers)` for SD downloads, `api.writeFile(path, dataB64)` for small file writes, `api.pluginFile(file)` for plugin assets, `api.registerAction(name, fn)` for jobs, and `api.crypto(op, fields)` for supported cryptographic operations. File Manager plugins can use same-origin file-management endpoints where available. Review the [local firmware API reference](docs/firmware-plugin-api.md) and current firmware before depending on a particular API.

Documented limits include an approximately 32 KB relay response-body cap, no automatic redirect following by relay or fetch, and small request limits for `writeFile`. Browser plugins execute inside the device WebUI, **not in an isolated sandbox**; they can access privileged same-origin functionality. Review third-party code before installing it. Never publish account secrets or tokens with a release, and protect credentials stored on the SD card.

### Manifest versus distribution catalog

The firmware manifest describes the installed plugin (including its browser mount); an upstream multi-plugin `catalog.json` is a distinct distribution index containing plugin identifiers, versions, remote base URLs, and files. Under our standalone-repository convention, **Plugin Hub reads the payload manifest and generates that distribution catalog automatically**, pinning installed files to a stable Release. Fields required here for Hub discovery should not be presented as requirements of the firmware's manual loader. A generated catalog's remote `base` is not a required field in the on-device manifest.

## 1. Preferred plugin repository layout

Use one public GitHub repository per plugin whenever reasonably possible.

A normal automatically discovered plugin repository has exactly one direct-child installable payload directory:

```text
repository-root/
├── .github/                       # optional development/CI files
├── docs/                          # optional development documentation
├── tests/                         # optional development tests
├── tools/                         # optional development/build tooling
├── README.md                      # optional repository/development README
└── <plugin-id>.crosspoint-plugin/
    ├── manifest.json              # REQUIRED
    ├── device.json                # at least ONE of device.json/plugin.js REQUIRED
    ├── plugin.js                  # at least ONE of device.json/plugin.js REQUIRED
    ├── README.md                  # RECOMMENDED installable plugin README
    ├── DETAILS.md                 # OPTIONAL on-device details source
    └── other runtime files...     # OPTIONAL; declare in manifest files
```

Plugin Hub treats only the direct-child `*.crosspoint-plugin/` directory as the installable payload. Repository-root development files are not installed.

### Required

For automatic discovery:

- the repository must be public;
- exactly one direct-child directory must end in `.crosspoint-plugin`;
- its directory stem must exactly match `manifest.json -> name`;
- `manifest.json` must exist inside the payload;
- at least one of `device.json` or `plugin.js` must exist inside the payload;
- `manifest.json -> name` must be a safe lowercase plugin ID using letters, digits, and hyphens;
- `manifest.json -> version` must use `MAJOR.MINOR.PATCH`;
- a non-draft, non-prerelease GitHub Release must exist;
- the Release tag must match the manifest version, with an optional leading `v`;
- every declared runtime file must exist and use a safe path relative to the payload directory.

### Recommended

- one repository per plugin;
- add the GitHub topic `crosspoint-plugin`;
- include an installable `README.md` in the payload;
- declare an explicit `manifest.json -> files` array containing every runtime file;
- keep tests, CI, screenshots, source-only tooling, package metadata, and other development files outside the payload.

Repository names containing `crosspoint-plugin` are also searched as a discovery fallback, but the GitHub topic is the preferred registration mechanism.

### Optional

- `DETAILS.md` for richer on-device item details;
- nested runtime paths such as `assets/icon.png` or `lib/api.js` when declared in `files`;
- `compatibility` metadata for true firmware/API/capability requirements.

## 2. Manifest contract

A typical manifest is:

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

`name` and `version` are required for the preferred automatic-discovery path. `title`, `description`, `author`, `compatibility`, and `files` are optional metadata, subject to the rules below.

### `files`

Paths are relative to the payload directory, not the repository root. Do not prefix entries with `<plugin-id>.crosspoint-plugin/`.

Paths must not be absolute, contain backslashes, contain `..` traversal components, or otherwise escape the payload.

If `files` is omitted, Plugin Hub considers the conventional runtime files that are present:

```text
manifest.json
device.json
plugin.js
README.md
```

The resulting install set must contain `manifest.json` and at least one of `device.json` or `plugin.js`.

If `DETAILS.md` or any other additional runtime file must ship with the plugin, declare it explicitly in `files`.

### `compatibility`

Compatibility metadata is optional. If omitted, Plugin Hub does not add a firmware restriction to the catalog entry.

Supported restrictions are:

- `firmware_family`: one or more compatible firmware families. CrossPoint uses `crosspoint`.
- `plugin_api_min`: minimum numeric plugin API level required.
- `requires`: capability names that must all be advertised by firmware.

Use these only for real requirements. Do not require a capability merely because it improves presentation or convenience.

Current CrossPoint advertises:

```text
firmware_family = crosspoint
plugin_api = 1
plugin_capabilities = catalog.lists,catalog.notices,catalog.bundle_install,catalog.version_tracking,catalog.compatibility,catalog.item_details
```

Current capability names are:

- `catalog.lists`
- `catalog.notices`
- `catalog.bundle_install`
- `catalog.version_tracking`
- `catalog.compatibility`
- `catalog.item_details`

Firmware-aware request templates may use:

```text
{firmware_family}
{firmware_version}
{plugin_api}
{plugin_capabilities}
```

Prefer these generic API/capability values over build-name checks.

## 3. Catalog-plugin fields used by current CrossPoint

CrossPoint's generic catalog system supports a normal `browse.url` catalog and, when needed, named lists through `browse.lists_url`.

When `browse.lists_url` is present and embedded `browse.lists` is absent, firmware fetches the remote list index and uses it to populate named catalog views. Embedded `browse.lists` are authoritative when present; do not combine both fields expecting remote-first behavior.

A list index entry may include:

```json
{
  "title": "Community Plugins",
  "url": "https://example.org/community-catalog.json",
  "notice": {
    "title": "Community Plugins",
    "message": "Third-party plugins. Not vetted by Dev Team.",
    "confirm": "Continue",
    "cancel": "Go Back"
  }
}
```

The current firmware contract also supports catalog bundle installation, installed-version tracking, compatibility filtering, and optional item details. These capabilities are generic plugin-system features and may be used by any plugin.

## 4. Automatic discovery and releases

The normal no-PR publishing path is:

1. Host the plugin in a public GitHub repository.
2. Add the `crosspoint-plugin` GitHub topic.
3. Use exactly one direct-child `<plugin-id>.crosspoint-plugin/` payload directory.
4. Make its stem match `manifest.json -> name` exactly.
5. Publish a non-draft, non-prerelease GitHub Release.
6. Tag it with the manifest version, optionally prefixed with `v`.
7. Publish a new version and new Release for every runtime change installed users should receive.

Plugin Hub publishes automatically discovered repositories from the immutable Release tag, not mutable `main` content.

A normal standards-compliant plugin does not require a Plugin Hub pull request. The catalog refresh runs every three hours and can also be triggered manually.

## 5. Exceptional ingestion paths

`whitelist.json` exists for sources that cannot use the normal automatic-discovery path.

It supports:

```json
{
  "repositories": [
    "owner/standalone-exception"
  ],
  "release_asset_repositories": [
    "owner/monorepo"
  ],
  "direct_plugins": [
    {
      "name": "hosted-plugin",
      "title": "Hosted Plugin",
      "description": "Plugin hosted outside GitHub.",
      "author": "Example Author",
      "version": "1.0.0",
      "base": "https://plugins.example.org/hosted-plugin/",
      "files": ["manifest.json", "plugin.js"]
    }
  ],
  "catalogs": [
    {
      "url": "https://example.org/catalog.json",
      "plugins": ["plugin-id"]
    }
  ]
}
```

- `repositories`: manually include a standalone repository while still requiring normal Release/manifest validation.
- `release_asset_repositories`: inspect stable Releases for `*.crosspoint-plugin.zip` assets.
- `direct_plugins`: directly define a plugin whose canonical payload has no suitable GitHub repository or catalog source. Entries use the normal plugin ID, version, HTTP(S) base, runtime-file, compatibility, and duplicate-ID validation.
- `catalogs`: import only explicitly named plugin IDs from another catalog.

These paths require maintainer configuration and therefore a Plugin Hub pull request. They should not be used merely to avoid the preferred repository layout.

### Release-asset monorepos

A configured monorepo may publish one or more `*.crosspoint-plugin.zip` assets. Each ZIP must contain exactly one CrossPoint plugin root with a valid manifest and at least one of `device.json` or `plugin.js`.

Validated runtime files are mirrored under:

```text
release-assets/<plugin-id>/<version>/
```

Mirrored plugin versions are immutable. If the same plugin/version later contains different bytes, catalog refresh fails and the publisher must release a new plugin version.

### Curated catalog imports

For configured external catalogs, Plugin Hub imports only the explicitly allowed plugin IDs. GitHub Raw branch URLs are pinned to the branch's current commit SHA before publication so generated catalog rows use an immutable source snapshot.

## 6. Blacklist and duplicate IDs

`blacklist.json` is the repository-level deny list:

```json
{
  "repositories": [
    "owner/repository"
  ]
}
```

Repository matching is case-insensitive. Blacklist rules win over automatic discovery, whitelist entries, release-asset sources, and curated catalogs.

If multiple sources claim the same plugin ID, that ID is quarantined for the refresh rather than silently selecting a winner. Non-conflicting plugins continue to publish, and the conflicting sources are recorded in `duplicate-plugin-ids.json` for maintainers to resolve.

## 7. Generated catalogs

The production refresh workflow generates:

- `catalog.json` — union catalog containing the published plugin set;
- `community-catalog.json` — Community catalog while it fits in one response;
- `community-catalog-<range>.json` — generated alphabetical shards when splitting is required;
- `catalog-lists.json` — live user-facing named-list index;
- `duplicate-plugin-ids.json` - duplicate-ID quarantine report; `duplicates` is empty when no conflicts are present;
- versioned `release-assets/` mirrors for configured release-asset repositories;
- generated `details/` HTML for plugins that provide supported `DETAILS.md` content.

All valid published plugins appear in **Community Plugins**. Repository ownership does not create another trust class.

### Community splitting

The native catalog reader has a 1 MiB browse-response safety limit. Plugin Hub measures actual compact serialized UTF-8 size, not plugin count.

When the Community catalog exceeds the limit, the production partitioner finds the minimum number of contiguous alphabetical shards that fit, preferring balanced splits. It never splits one first-letter bucket across shards. Stale shard files are removed automatically when the required partition changes.

`catalog-lists.json` is regenerated with the current shard layout, so changing the number of Community shards does not require a Plugin Hub release.

Every Community list carries the notice:

```text
Third-party plugins. Not vetted by Dev Team.
```

## 8. Plugin Hub runtime and bootstrap

Plugin Hub is itself a normal SD-card plugin and is optional. Sideloaded plugins do not depend on Plugin Hub.

Plugin Hub intentionally remains a repository-root payload exception. Its firmware bootstrap, root-generated catalogs, release workflow, and production `stable` branch depend on the current root layout. New plugins must not copy this exception.

When the Plugin System is enabled, current CrossPoint exposes **Home → Plugins**. If Plugin Hub is not installed and its bootstrap entry has not been hidden, firmware can offer the Plugin Hub installer.

The bootstrap installs the Plugin Hub runtime to:

```text
/.crosspoint/plugins/pluginhub/
```

and uses staged replacement plus an `.installing` marker so incomplete installs are not treated as valid plugins.

Current CrossPoint discovers installed plugins across:

```text
/.crosspoint/plugins
/plugins
/.plugins
```

Updates reuse an existing plugin's discovered root so settings and tokens remain with that installation.

## 9. Browser WebUI

`plugin.js` provides Plugin Hub's browser-side management UI. It can browse the generated Community list index, install/update/reinstall/remove plugins, inspect installed versions, and use custom catalog URLs.

For catalogs too large for the normal relay response, Plugin Hub uses the firmware fetch-to-SD path, reads the temporary downloaded catalog, then removes the temporary file.

Custom catalogs remain separate from the built-in Community catalog. They are a browser-side Plugin Hub feature; the on-reader Plugin Hub screen follows the built-in catalog configuration in `device.json`.

## 10. Production workflows

### Refresh Plugin Catalog

`.github/workflows/refresh-catalog.yml` runs every three hours, on manual dispatch, and on relevant `main` changes. It:

1. runs the Python catalog tests;
2. runs the browser Plugin Hub tests;
3. builds the catalog with `tools/build_catalog.py`;
4. applies automatic discovery, whitelist, blacklist, release-asset, and curated-source rules;
5. rebuilds generated catalogs/details/release mirrors and writes the duplicate-ID quarantine report;
6. commits generated changes only when content changed.

`tools/build_catalog.py` and `tools/catalog_partitions.py` are production code used by this workflow.

### Promote Stable Plugin Hub Release

The stable-promotion workflow advances `stable` to the exact commit behind a newly published non-prerelease Plugin Hub Release. `stable` is the production bootstrap pointer; normal discovered plugins remain pinned to immutable Release tags or other immutable generated sources.

## 11. Local validation

No third-party Python packages are required for catalog tests. Node.js is used for the browser-side test.

```text
python -m unittest discover -s tests -v
node --test tests/test_plugin_js.mjs
```

Running `python tools/build_catalog.py` performs a live catalog build and may require `GITHUB_TOKEN` or `GH_TOKEN` to avoid unauthenticated GitHub API rate limits.

## 12. Plugin Hub release status

Plugin Hub `0.1.7` is the current production Plugin Hub release.

- `v0.1.7` is the current stable GitHub Release;
- the `stable` branch is the production bootstrap pointer and is promoted to the published stable release commit;
- firmware bootstrap installs Plugin Hub from `stable`;
- Plugin Hub's generated Community entry resolves from its latest stable Release after catalog refresh.
