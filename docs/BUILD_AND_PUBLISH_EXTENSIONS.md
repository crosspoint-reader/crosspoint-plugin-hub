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

One public repo; direct-child `<collection-id>.crosspoint-theme/` containing a manifest with `kind: "theme-pack"`, `name`, `title`, `description`, `author`, `version`, `license`, `themes` and a complete `files` allowlist. Include the payload `README.md` and each `themes/<id>/theme.json` plus resources. **No `device.json`, `plugin.js`, or executable scripts**. Theme title in the selector comes from `themes[].title`; choose short device-friendly titles. The payload README is plain, printable ASCII (no emoji, Markdown heading markers), **maximum 2 KiB**. A rich Markdown repository-root README is fine.

Capabilities/primitives exposed by the Razor-Crest SD-theme firmware:

| Capability | Theme authoring primitive |
| --- | --- |
| `theme.sd.v1` | Bounded SD pack discovery and manifest/capability checks; Settings > Display > UI Theme and Classic fallback |
| `theme.metrics.v1` | Bounded `ThemeMetrics` layout and spacing overrides; check exact host-validator allowlist |
| `theme.images.v1` | Versioned monochrome 1-bit `.cpb` images; roles `header_emblem`, `home_hero`, `boot_art`, `sleep_art`, `sleep_emblem` |
| `theme.composition.v1` | Declarative regions `header`, `home`, `boot`, `sleep`, `hints` and operations `fill`, `rect`, `bitmap`, `text`, `line`, `book-card`, `progress` |
| `theme.fonts.v1` | Optional bounded monochrome v4 `.cpfont` UI glyph resources; stock font fallback |
| `theme.font-family.v1` | One UI font or `small`/`regular`/`large`/`display` font-family sizes; book-reading fonts unaffected |
| `theme.settings-navigation.v1` | Default List/Tabs Settings preference, subordinate to the user's override |

Additional supported theme properties: `reference` portrait width/height and `adapt` `center-crop` or `scale-to-fit`; required style fields `header_background`, `header_foreground`, `selection`, `row_separators`, `corners`, `chamfer_cut`; optional chamfer cut variants and `settings_navigation`. Text sources are **only** `screen_title`, `date`, `device_name`, `book_title`, `book_author`, `progress_percent`, `tagline`, `loading_percent`. A scene cannot execute code or invent callbacks. Multiple `sleep_art` entries rotate for regular Dark/Light sleep entry, **not timed Custom sleep wakeups**. Full field/operation bounds are in the [theme contract](https://github.com/jadehawk/halo.crosspoint-theme/blob/main/docs/THEME_CONTRACT.md).

Use the author-hosted validator, tests and packer, and only release a checked ZIP containing exactly one installable folder. Add GitHub topic `crosspoint-theme`, stable Release tag `v<manifest-version>`, and the asset **`<name>-<version>.crosspoint-theme.zip`**. The catalog scanner independently validates and records checksum and URL.

## 3. Standalone wallpaper pack

One public repo can contain **1–8 direct-child** `<package-id>.crosspoint-wallpaper/` folders; each needs `manifest.json`, `README.md`, and listed files under `wallpapers/`. Each manifest has `kind: "wallpaper-pack"`, `name` (package ID), `collection` (artwork collection ID), `title`, `author`, `version`, `target_resolution`, `images`, and a complete `files` allowlist. In multi-pack repos, `collection` and `target_resolution` are required for **every** package. Multiple resolutions for one collection are variants; separate collections may share a resolution. Do not duplicate the same `(collection, width, height)` combination. Images must be valid native BMPs with declared dimensions, at most 32 per pack, 8 MiB each, 64 MiB per package. No scripts, fonts, themes or plugin entry points. Device README is plain printable ASCII, at most 2 KiB.

`wallpaper.packs.v1` provides bounded SD discovery and verification, a named **Wallpaper Collection** selector under **Settings > Display > Sleep Screen: Custom**, independent pack selection and persistent choice, random image selection and existing timed sleep refresh integration for the chosen collection. The default **All wallpapers** merges `/.sleep` and `/sleep` and retains `/sleep.bmp` precedence. Missing collections fall back safely. Theme Dark/Light galleries and Cover sleep modes remain distinct. The firmware loads **one BMP at a time**, not the whole collection into X3 RAM. It does **not** provide executable hooks, styling, or arbitrary file access.

Run the wallpaper validator and `pack-all`; use topic `crosspoint-wallpaper`. Publish a stable, non-draft, non-prerelease Release with one distinct **`<package-id>-<version>.crosspoint-wallpaper.zip`** per variant, matching every embedded manifest. The firmware selects **one variant matching the actual screen portrait resolution**, never by model name. Each wallpaper collection can be installed separately. See the [wallpaper contract](https://github.com/jadehawk/starwars.crosspoint-wallpaper/blob/main/docs/WALLPAPER_PACK_CONTRACT.md).

## Getting published in Plugin Hub

1. Make the GitHub repo public and set its appropriate topic: `crosspoint-plugin`, `crosspoint-theme`, or `crosspoint-wallpaper`.
2. Follow the matching payload layout, exact manifest/schema and ZIP naming rules above; keep development files **outside** the installable archive.
3. Validate with the repo's own tests/packer. Check that releases match `MAJOR.MINOR.PATCH` and include immutable, install-only ZIP assets. Keep authorship/redistribution rights clear.
4. Publish a **non-draft, non-prerelease** Release at a tag matching the manifest version (for themes and wallpaper assets use `vMAJOR.MINOR.PATCH`).
5. The Plugin Hub catalog GitHub Action runs every **three hours** or when manually dispatched. It discovers eligible repos by topics (plugin name fallback also supported), checks release assets, identity, duplicate IDs, sizes, files, manifests, and wallpaper image dimensions, and publishes valid items. Invalid/conflicting entries may be omitted or quarantined in `duplicate-extension-ids.json`; a catalog entry isn't a security endorsement. Existing firmware that lacks capabilities must not show theme/wallpaper install controls.
6. Find results in `community-themes.json`, `community-wallpapers.json`, and `catalog-lists-capabilities.json`. Existing plugins remain in their legacy `catalog-lists.json` / Community catalog. Ordinary compliant repos do not require a Plugin Hub PR or allowlist exemption.

## Copy/paste instructions for an AI coding agent

> Read this entire guide and the linked contract for my requested package kind (plugin, theme, or wallpaper). Audit my existing repository first. Create a self-contained direct-child installable folder and preserve stable IDs, authored assets, existing credits and unrelated files. Generate valid author-side manifests and device-friendly README text; never add runtime text cleaners, plugins or scripts to theme/wallpaper packs. Declare only real firmware capabilities and show me stock-vs-compatible firmware support honestly. Set the correct topic and immutable-release packaging, with validation and GitHub Actions. Run unit tests and validators, inspect ZIP members and manifest versions, and report what is ready for publication. Do not commit, push, tag, or release until I explicitly authorize those actions.

Package names and version tags are **publishing contracts**, not firmware support guarantees.
