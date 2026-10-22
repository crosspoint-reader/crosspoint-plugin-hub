# Capability-aware catalog schema (v2)

The scheduled Plugin Hub workflow now generates the data below. Firmware and
Plugin Hub installation support for themes/wallpapers is **not yet implemented**.

## URLs

Legacy plugin files remain unchanged: catalog.json, community-catalog*.json,
and catalog-lists.json.

The extended, opt-in files on the main branch are:

- https://raw.githubusercontent.com/crosspoint-reader/crosspoint-plugin-hub/main/catalog-lists-capabilities.json
- https://raw.githubusercontent.com/crosspoint-reader/crosspoint-plugin-hub/main/community-themes.json
- https://raw.githubusercontent.com/crosspoint-reader/crosspoint-plugin-hub/main/community-wallpapers.json
- duplicate-extension-ids.json (quarantined conflicting IDs)

Legacy plugin consumers must continue using catalog-lists.json.

## Extended list index

Schema version 2, object with keys: schema_version, generated_at, lists.

Every entry in lists contains:

- title: human-readable title
- url: absolute HTTPS URL of a catalog
- kind: one of plugin, theme-pack, wallpaper-pack
- items: the field containing entries in that catalog, either plugins or items
- requires: all-of firmware capability identifiers
- notice: optional title/message/confirm/cancel text

Existing plugin lists and their URLs are copied from the legacy index, with
kind=plugin, items=plugins, requires=[catalog.lists]. They are **not** removed
or rewritten to include unsupported package kinds.

Community Themes has requires=[theme.sd.v1], items=items.
Community Wallpaper Packs has requires=[wallpaper.packs.v1], items=items.

## Theme catalog

community-themes.json is a JSON object containing:

- schema_version: 2
- kind: theme-pack
- name: Community Themes
- generated_at: UTC timestamp, retained when the content does not change
- items: list of theme collection entries

Each theme collection entry contains name, title, kind, author, description,
version, repository, release, release_url, requires, asset_url, sha256, bytes,
and themes. The themes array contains id, title and its own requires array.
Consumers must check both the list-level and per-theme capabilities. The
release asset is an immutable, verified, single-root ZIP installed at
/.crosspoint/themes/<name>.crosspoint-theme/.

## Wallpaper catalog

community-wallpapers.json has schema_version=2, kind=wallpaper-pack,
name="Community Wallpaper Packs", generated_at, and items.

Each item is **one independent artwork collection** with fields:
name (collection ID), title, kind, author, version, repository, release,
release_url, requires=[wallpaper.packs.v1], and variants.

Each entry in variants contains the installable name (package ID),
target_resolution={width,height}, asset_url, sha256 and bytes.

Example: collection starwars contains variants starwars-x3 (528x792) and
starwars-x4plus (480x800). A second collection starwarsyoda may contain
starwarsyoda-x3 (528x792) and starwarsyoda-x4plus (480x800).
Duplicate (collection,target_resolution) pairs are rejected *within one
repository*. The same resolution is valid across different collections.

**Installation:** a user may install multiple independent collections,
but should receive at most one matching resolution variant of any selected
collection. Download only that one ZIP and install it at
/.crosspoint/wallpapers/<variant-name>.crosspoint-wallpaper/.
Do not download every ZIP in a repository or activate the pack implicitly.

Firmware must expose a trustworthy actual display resolution before
automatic selection is enabled; the current /api/status exposes capabilities
but not screen width/height. Do not hardcode a device/model name to pick a ZIP.

## Publishing and safety

The generator finds public repositories via crosspoint-theme and
crosspoint-wallpaper GitHub topics. It validates the latest non-draft,
non-prerelease GitHub releases, version matching, per-package ZIP names,
ZIP safety, the embedded manifests and file allowlists, BMP dimensions and
the declared target resolutions. Release download URL, size and SHA-256 are
recorded. Repository blacklists apply. Colliding identities are quarantined
in duplicate-extension-ids.json; other valid collections remain published.

The future firmware installer must independently verify ZIP content and
checksum, route each kind to its proper SD root and protect against partial
installation. The current Plugin Hub device.json and WebUI installer remain
plugin-only. Nothing changes the legacy catalog-list URL yet.
