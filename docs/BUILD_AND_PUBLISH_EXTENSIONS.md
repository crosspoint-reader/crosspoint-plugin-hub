# Build and publish CrossPoint extensions

This guide is for developers and AI coding agents arriving through Plugin Hub. It covers **three separate package kinds**. Read the matching contract before writing or copying files:

- [Plugin publisher contract](../PLUGIN_HUB_CONTRACT.md) and [plugin AI guide](../PLUGIN_HUB_AGENT_GUIDE.md)
- [SD theme reference and agent instructions](https://github.com/jadehawk/halo.crosspoint-theme/blob/main/docs/AI_AGENT_GUIDE.md), with [full theme contract](https://github.com/jadehawk/halo.crosspoint-theme/blob/main/docs/THEME_CONTRACT.md)
- [Wallpaper pack reference and agent instructions](https://github.com/jadehawk/starwars.crosspoint-wallpaper/blob/main/docs/AI_AGENT_GUIDE.md), with [full wallpaper contract](https://github.com/jadehawk/starwars.crosspoint-wallpaper/blob/main/docs/WALLPAPER_PACK_CONTRACT.md)
- [Exact catalog fields, ZIP identities and compatibility flags](EXTENSION_CATALOG_SCHEMA.md)

The referenced repos are working examples, **not required firmware builds**. Developers can use any compliant publisher repository and any firmware that advertises the required capabilities. Catalog appearance is not a safety audit.

## What runs on which firmware?

**As of 2026-10-22:** the stock upstream [CrossPoint](https://github.com/crosspoint-reader/crosspoint-reader) firmware does **not yet support SD theme-pack or standalone wallpaper-pack installation, discovery or selection**. Its existing plugin system is separate. Only the following theme/wallpaper-capable implementation is currently established:

| Firmware | Status | SD theme packs | BMP wallpaper packs | Notes |
| --- | --- | --- | --- | --- |
| [Razor-Crest](https://github.com/jadehawk/Razor-Crest) | Development `razor-crest` branch / current test builds | Yes: `theme.sd.v1` plus declared theme capabilities | Yes: `wallpaper.packs.v1` | Tested on X3; HALO rendered on X4 Pro. Capability-aware catalog installation is undergoing hardware validation. Not all tagged builds necessarily include it |
| [Upstream CrossPoint](https://github.com/crosspoint-reader/crosspoint-reader) | Current examined stock firmware | No | No | Do not assume a catalog entry makes an extension installable |

This is an **informational list, not a firmware allowlist**. Future implementations are compatible if they expose and implement the corresponding capability tokens. Determine runtime support from `GET /api/status` `pluginCapabilities` or native `{plugin_capabilities}`; never gate on the string `Razor-Crest`.

## 1. Plugin

One public repo; direct-child `<id>.crosspoint-plugin/` containing `manifest.json` with matching `name`, a `MAJOR.MINOR.PATCH` `version`, safe `files` and at least one of `device.json` (on-reader) or `plugin.js` (browser). Add `crosspoint-plugin` topic. Publish a non-draft, non-prerelease GitHub Release with matching tag. See [full contract](../PLUGIN_HUB_CONTRACT.md) and [agent checklist](../PLUGIN_HUB_AGENT_GUIDE.md). **Plugins are firmware-agnostic**: use actual exposed plugin APIs/capabilities, not branded firmware dependencies.

## 2. Theme

One public repo; direct-child `<collection-id>.crosspoint-theme/` containing a manifest with `kind: "theme-pack"`, `name`, `title`, `description`, `author`, `version`, `license`, `themes` and a complete `files` allowlist. Include the payload `README.md` and packaged `DETAILS.md`, both declared in `files`, and each `themes/<id>/theme.json` plus resources. **No `device.json`, `plugin.js`, or executable scripts**. Theme title in the selector comes from `themes[].title`; choose short device-friendly titles. The payload README is plain, printable ASCII (no emoji, Markdown heading markers), **maximum 2 KiB**. A rich Markdown repository-root README is fine.

Plugin Hub defines **publication metadata and catalog compatibility checks**, not firmware rendering primitives. Themes declare capability identifiers; firmware that does not advertise them must not offer installation. Layout operations, fonts, artwork roles, sleep scenes, and UI controls belong in the implementing firmware's contracts, such as the [Razor-Crest SD-extension contract](https://github.com/jadehawk/Razor-Crest/blob/razor-crest/docs/sd-extension-contracts.md). They are not stock CrossPoint Plugin Hub primitives.

Publish **one independently validated archive per supported portrait resolution** from a theme source repository. Theme asset filenames must include a suffix after the stable name, even for a single resolution, because compatible firmware selects variants by the `<name>-` prefix. For example, use `<name>-x3-<version>.crosspoint-theme.zip` for 528 × 792 and `<name>-x4plus-<version>.crosspoint-theme.zip` for 480 × 800. Each archive contains only the assets for its declared `manifest.target_resolution`, with its own exact file list. The ZIP root and embedded `manifest.name` must be the stable `<name>.crosspoint-theme/`, without any resolution suffix. Publish the variants together under one stable release tag `v<manifest-version>` with GitHub topic `crosspoint-theme`. Plugin Hub groups them into one listing; capable firmware selects a matching archive using measured display resolution. Do not infer firmware support from model names.


## 3. Standalone wallpaper pack

One public repo can contain **1–8 direct-child** `<package-id>.crosspoint-wallpaper/` folders; each needs `manifest.json`, `README.md`, `DETAILS.md`, and listed files under `wallpapers/`. Each manifest has `kind: "wallpaper-pack"`, `name` (package ID), `collection` (artwork collection ID), `title`, `description`, `author`, `version`, `target_resolution`, `images`, and a complete `files` allowlist. In multi-pack repos, `collection` and `target_resolution` are required for **every** package. Multiple resolutions for one collection are variants; separate collections may share a resolution. Do not duplicate the same `(collection, width, height)` combination. Images must be valid native BMPs with declared dimensions, at most 32 per pack, 8 MiB each, 64 MiB per package. No scripts, fonts, themes or plugin entry points. Device README is plain printable ASCII, at most 2 KiB.

`wallpaper.packs.v1` is the advertised capability required to discover and install wallpaper collections. Plugin Hub validates package metadata and assets; firmware-specific wallpaper selectors, rotation rules, and sleep behavior are documented by the implementing firmware, not by this catalog publisher.

Run the wallpaper validator and `pack-all`; use topic `crosspoint-wallpaper`. Publish a stable, non-draft, non-prerelease Release with one distinct **`<package-id>-<version>.crosspoint-wallpaper.zip`** per variant, matching every embedded manifest. The firmware selects **one variant matching the actual screen portrait resolution**, never by model name. Each wallpaper collection can be installed separately. See the [wallpaper contract](https://github.com/jadehawk/starwars.crosspoint-wallpaper/blob/main/docs/WALLPAPER_PACK_CONTRACT.md).

## Shared catalog metadata and details contract

For plugins, themes and wallpaper packs alike, keep the `name` identity,
`title`, `description`, `author` and `version` in the package manifest.
Declare a device-friendly plain-text `README.md` and a rich Markdown
`DETAILS.md` in the installable `files` list for theme and wallpaper
packages. Plugin Hub verifies both from the released ZIP, sanitizes the rich
description into a versioned HTML page, and publishes `details.url` and
`details.format`. Compatible consumers may display the short description in installed lists and rich details before an installation action. A release is not ready until the catalog fixture verifies both metadata fields and the immutable details asset.

## Required pre-release acceptance checks (all three kinds)

A repository is **not release-ready** merely because an archive can be built.
Before publishing a tag, verify:

1. The payload manifest has stable `name`, readable `title`,
   **`description`**, `author`, `version`, and every exact ZIP member
   declared in `files`.
2. An installed, plain-text `README.md` and a packaged Markdown
   `DETAILS.md` are present for themes and wallpapers, with valid UTF-8
   within bounded file sizes. Plugins use the same optional rich-details
   mechanism and should include it for a comparable catalog experience.
3. Plugin Hub validates the **release ZIP**, produces the short description
   from the manifest, and emits an immutable `details.url` and
   `details.format: html` based on its packaged `DETAILS.md`.
4. The native browse list displays the short **description**, not the author.
   A normal tap opens details first; Install/Update is a separate action.
   Author, version, source and details remain distinguishable.
5. The installed list shows a description, not an author subtitle; the
   author's credit is retained in item details. Existing installations
   continue to work during a format transition.
6. Wallpaper **and theme** variants have matching collection metadata and
   distinct verified resolutions. Plugin Hub chooses **one** matching ZIP,
   never a hard-coded model name; theme install identity remains stable.
7. Run author-side tests, the Plugin Hub catalog fixture suite, firmware
   inspection, and actual X3/X4Pro touch/button tests before publishing.
   Keep old release tags immutable; changing the format requires a **new
   version and tag**.

## Getting published in Plugin Hub

1. Make the GitHub repo public and set its appropriate topic: `crosspoint-plugin`, `crosspoint-theme`, or `crosspoint-wallpaper`.
2. Follow the matching payload layout, exact manifest/schema and ZIP naming rules above; keep development files **outside** the installable archive.
3. Validate with the repo's own tests/packer. Check that releases match `MAJOR.MINOR.PATCH` and include immutable, install-only ZIP assets. Keep authorship/redistribution rights clear.
4. Publish a **non-draft, non-prerelease** Release at a tag matching the manifest version (for themes and wallpaper assets use `vMAJOR.MINOR.PATCH`). For theme and wallpaper variants, attach each independently validated resolution-specific ZIP to that **same Release**, not separate tags.
5. The Plugin Hub catalog GitHub Action runs every **three hours** or when manually dispatched. It discovers eligible repos by topics (plugin name fallback also supported), checks release assets, identity, duplicate IDs, sizes, files, manifests, and wallpaper image dimensions, and publishes valid items. Invalid/conflicting entries may be omitted or quarantined in `duplicate-extension-ids.json`; a catalog entry isn't a security endorsement. Existing firmware that lacks capabilities must not show theme/wallpaper install controls.
6. Find results in `community-themes.json`, `community-wallpapers.json`, and `catalog-lists-capabilities.json`. Existing plugins remain in their legacy `catalog-lists.json` / Community catalog. Ordinary compliant repos do not require a Plugin Hub PR or allowlist exemption.

## Copy/paste instructions for an AI coding agent

> Read this entire guide and the linked contract for my requested package kind (plugin, theme, or wallpaper). Audit my existing repository first. Create a self-contained direct-child installable folder and preserve stable IDs, authored assets, existing credits and unrelated files. Generate valid author-side manifests and device-friendly README text; never add runtime text cleaners, plugins or scripts to theme/wallpaper packs. Declare only real firmware capabilities and show me stock-vs-compatible firmware support honestly. Set the correct topic and immutable-release packaging, with validation and GitHub Actions. Run unit tests and validators, inspect ZIP members and manifest versions, and report what is ready for publication. Do not commit, push, tag, or release until I explicitly authorize those actions.

Package names and version tags are **publishing contracts**, not firmware support guarantees.



