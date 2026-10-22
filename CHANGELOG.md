# Changelog

## 0.1.9 (2026-10-22)

- Generate separate capability-gated Community Themes and Community Wallpaper Packs catalogs from stable GitHub releases without changing legacy Community Plugins catalogs.
- Publish opt-in catalog-lists-capabilities.json with package kinds and required capabilities; legacy catalog-lists.json stays plugin-only.
- Verify theme/wallpaper ZIP contents, package IDs, image resolutions, versions, immutable asset URLs, and hashes.
- Group wallpaper resolution variants by collection, allow different collections to share resolutions and quarantine conflicting identities.
- Apply repository blacklist rules to extension discovery, add automated tests, and document the new firmware-facing schema.
- Keep theme/wallpaper installation pending the firmware's future generic package-kind and capability-aware catalog handlers.

## 0.1.8 (2026-10-21)

- Remove the version suffix from the on-reader Plugin Hub title while retaining the version in manifest/device metadata.
- Verify that both installed titles remain `Plugin Hub` and the release tag matches the metadata before packaging and stable promotion.
- Publish the release with the plain version tag as its GitHub Release name.
- Keep `stable` synchronized with the latest `main` catalog commits after release, guarded so unreleased runtime files cannot be promoted.

## 0.1.7 (2026-10-20)

- Fix inconsistent catalog action alignment by using a full-width, two-column grid (descriptions grow, actions occupy the right edge) with right-aligned mobile fallback.
- Keep Install in the normal button style, highlight Reinstall in yellow and Remove in red.
- Require confirmation before removing installed plugins; recursively remove nested plugin files and report failures instead of silently leaving incomplete installations.
- Accept an optional browser-host Reinstall handoff by plugin ID, reusing Plugin Hub's existing catalog installer without requiring that host integration.
- Keep plugin data outside the installation directory untouched when firmware provides separate persistent plugin storage.

## 0.1.6

- Compact generated catalogs and dynamically split oversized Community catalogs into balanced alphabetical ranges below the firmware-safe byte limit.
- Publish a dynamic catalog-list index so native Plugin Hub can follow Community catalog splits without requiring a plugin update.
- Add `blacklist.json`; repositories listed there are omitted from every generated catalog before whitelist or curated-source ingestion is applied.
- Add optional curated `DETAILS.md` payload content, convert its safe Markdown subset to versioned semantic HTML during catalog generation, and publish rich-details metadata for the current CrossPoint plugin contract.
- Keep `catalog.json` as the union catalog feed while `browse.lists_url` drives the current dynamic Community catalog navigation.
- Propagate optional plugin `compatibility` metadata through release discovery, curated catalogs, and release-asset imports, normalize it for native firmware filtering, and map the compatibility fields in `device.json`.
- Align the browser WebUI with firmware plugin discovery across `/.crosspoint/plugins`, `/plugins`, and `/.plugins`, preserving an existing plugin's root for update, reinstall, and removal.
- Let the browser WebUI fall back to the built-in Community catalog URL when the dynamic catalog-list index is temporarily unavailable.
- Publish all currently discovered plugins through the single user-facing Community Plugins catalog and remove the dormant Official catalog/policy path.
- Show `Plugin Hub v0.1.6` in the installed Plugins picker.
- Keep Plugin Hub itself discoverable in Community Plugins so installed copies can be updated through the normal catalog bundle update path.
- Reset automatic discovery to the folder-first repository standard: one plugin repository with exactly one direct child `<plugin-id>.crosspoint-plugin/` installable payload directory.
- Keep Plugin Hub itself as the intentional root-layout exception so its firmware bootstrap, root catalogs, and production `stable` branch remain unchanged.
- Add `PLUGIN_HUB_AGENT_GUIDE.md` so developers can hand the publishing workflow directly to an AI coding agent.
- Consolidate the authoritative publishing, catalog, manifest, capability, and maintainer rules into `PLUGIN_HUB_CONTRACT.md`; keep the README as a project overview instead of a duplicate specification.
- Move Plugin Hub's canonical repository identity, runtime/catalog URLs, bootstrap source, generated mirrors/details, and self-update endpoint to `crosspoint-reader/crosspoint-plugin-hub` after the repository transfer, with no pre-release old-repository compatibility layer.

## 0.1.5

- Split Plugin Hub into separate **Official Plugins** and **Community Plugins** feeds while retaining `catalog.json` as the backward-compatible union feed.
- Add explicit `catalog-policy.json` curation so Official status is tied to a plugin ID and trusted source instead of repository ownership or discovery order.
- Make trusted Official sources win conflicting claims and fail catalog generation on ambiguous duplicate Community plugin IDs.
- Add an on-reader Official/Community chooser through the firmware's existing `browse.lists` support, with no firmware-specific Plugin Hub changes required.
- Add a concise confirmation notice before opening **Community Plugins** so third-party plugins are clearly identified as not vetted by the Dev Team.
- Refactor the browser WebUI to browse one built-in catalog at a time, keep Official selected by default, and move custom/private catalogs into a secondary Custom catalogs section.
- Filter the legacy union and both built-in catalog URLs out of migrated custom-catalog settings so they cannot appear as duplicate user-facing choices.
- Add repository-standard documentation for the recommended no-PR standalone plugin layout and Community-by-default classification.
- Add `release_asset_repositories` support for monorepos that publish one or more `*.crosspoint-plugin.zip` assets from stable GitHub Releases.
- Validate release ZIPs safely, mirror declared runtime files under immutable per-plugin/version directories, and publish them through the normal Plugin Hub `base` plus `files` contract.
- Configure `readest/readest` as the first release-asset repository and process every matching CrossPoint plugin ZIP from its newest stable Release that contains one.

## 0.1.4

- Adopt the firmware `api.dir` plugin-directory API when available while retaining operation when that API is unavailable.
- Store Plugin Hub configuration as plugin-local `config.json` when `api.dir` is available, while retaining `/.crosspoint/plugin-hub.json` as the fallback path.
- Migrate legacy catalog settings by reading the old config when plugin-local config is absent, then saving future changes to the plugin directory without deleting the legacy file.
- Read Plugin Hub's own `manifest.json` from its actual runtime directory for self-version detection, with the legacy `/.crosspoint/plugins/pluginhub` lookup retained as a fallback.
- Add browser regression coverage for both the no-`api.dir` path and the `api.dir` path.

## 0.1.3

- Add a release-promotion workflow that moves the `stable` branch to each published non-prerelease Plugin Hub release.
- Allow the stable-promotion workflow to run manually for a specific published stable tag or the latest stable Release.
- Make the bootstrap catalog versionless and point it at `stable`, so fresh installs receive the latest stable Plugin Hub without future catalog PRs.
- Rename the bootstrap catalog heading to `Plugin Hub` so users do not see the internal bootstrap label.
- Package every stable release as `pluginhub-X.Y.Z.zip`, expanding to `.crosspoint/plugins/pluginhub/` for direct SD-card installation without Plugin Store.
- Allow the release-package workflow to be run manually for a specific stable tag or the latest stable Release.
- Document direct SD-card installation, the firmware's in-place plugin loading behavior, and the catalog ID/title fallback rules.
- Correct the README to describe both the on-reader `device.json` catalog and browser-side `plugin.js` management UI.

## 0.1.2

- Standardize newly published Plugin Hub and discovered plugin versions on three-part `MAJOR.MINOR.PATCH` to match the CrossPoint firmware catalog contract.
- Tighten catalog-builder validation so two-part and four-part release versions are rejected for new catalog entries.
- Keep browser-side version comparison backward-compatible with legacy multi-part installed versions during migration.
- Point the bootstrap catalog at the immutable `v0.1.2` Plugin Hub release.
- Update the firmware note to reference CrossPoint PR #3824 for directional native version comparison.

## 0.1.1

- Add `whitelist.json` support for explicitly curated repositories and imported catalog entries.
- Import the existing CrossPoint Plugin Store entries except the legacy `send2ereader` entry.
- Resolve mutable GitHub Raw branch URLs from curated catalogs to immutable commit-SHA URLs.
- Prefer release-discovered plugins over curated catalog entries when the same plugin ID appears in both.
- Add the browser-side `plugin.js` management UI with install, update, reinstall, and remove controls.
- Show Plugin Hub's installed version in the WebUI and check the latest stable GitHub Release for an available self-update.
- Keep the generated Plugin Hub catalog as the built-in browser source while allowing users to add and remove extra custom, test, or private catalog URLs.
- Use directional two-to-four-part numeric version comparison in the browser UI so older catalog versions are not offered as downgrades.
- Add a browser integration test covering custom catalogs and directional update handling.
- Give generated catalogs a friendly `Plugin Hub` name instead of falling back to the raw host name.
- Document the complete self-service listing requirements, custom catalog format, troubleshooting checks, and version-tracking rules for release-discovered and curated plugins.

## 0.1.0

- Add the initial Plugin Hub CrossPoint plugin.
- Add GitHub discovery by `crosspoint-plugin` topic and compatible repository names.
- Generate catalog entries from stable GitHub Releases using immutable tag URLs.
- Support two-, three-, and four-part numeric versions, including an optional leading `v`.
- Validate release and manifest versions before publishing a catalog entry.
- Support explicit runtime file lists in `manifest.json`, with conventional CrossPoint files as the fallback.
- Add automated catalog refreshes and catalog-builder tests.
- Add a temporary bootstrap catalog for installing Plugin Hub through the existing CrossPoint Plugin Store before official catalog inclusion.
