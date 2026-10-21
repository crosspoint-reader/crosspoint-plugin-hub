# Plugin Hub

Plugin Hub is a CrossPoint SD-card plugin for discovering, installing, updating, reinstalling, and removing CrossPoint plugins.

Plugin Hub currently publishes one user-facing catalog: **Community Plugins**. Valid discovered plugins are published there automatically.

> [!NOTE]
> Plugin Hub `0.1.8` is the current stable Plugin Hub release. Use a recent **CrossPoint Nightly** with the Plugin System enabled for the on-reader catalog, including dynamically fetched catalog lists through `browse.lists_url`. The browser interface (`plugin.js`) and on-reader interface (`device.json`) are complementary and work independently wherever the firmware exposes their standard plugin capabilities.

## Documentation

There are two canonical technical documents:

- [`PLUGIN_HUB_CONTRACT.md`](PLUGIN_HUB_CONTRACT.md) — authoritative Plugin Hub publishing, catalog, manifest, capability, workflow, and repository contract.
- [`PLUGIN_HUB_AGENT_GUIDE.md`](PLUGIN_HUB_AGENT_GUIDE.md) — instructions for an AI coding agent to organize a plugin repository for automatic discovery and long-term maintainability.

The README is intentionally only a project overview. Contract details belong in `PLUGIN_HUB_CONTRACT.md` so they are not duplicated across multiple documents.

## Getting a plugin into Plugin Hub

The preferred path requires no Plugin Hub pull request:

1. Use one public GitHub repository per plugin.
2. Put the installable payload in exactly one direct-child `<plugin-id>.crosspoint-plugin/` directory.
3. Include `manifest.json` and at least one of `device.json` or `plugin.js`.
4. Make the payload directory stem match `manifest.json -> name` exactly.
5. Add the GitHub topic `crosspoint-plugin`.
6. Publish a non-draft, non-prerelease GitHub Release whose tag matches the manifest `MAJOR.MINOR.PATCH` version.
7. Wait for the scheduled Plugin Hub catalog refresh or a maintainer-triggered refresh.

A payload README is recommended, but it is not required for automatic discovery.

For the complete contract, including `manifest.json -> files`, compatibility metadata, release-asset monorepos, curated imports, blacklist behavior, and catalog generation, see [`PLUGIN_HUB_CONTRACT.md`](PLUGIN_HUB_CONTRACT.md).

## How Plugin Hub works

The production catalog workflow:

- discovers eligible public repositories;
- reads exceptional sources configured in `whitelist.json`;
- applies `blacklist.json` as the final repository deny list;
- validates plugin IDs, versions, runtime file lists, and immutable release sources;
- publishes valid plugins in **Community Plugins**;
- automatically splits Community into alphabetical shards when required by the native catalog response-size limit;
- regenerates `catalog-lists.json` so shard-layout changes do not require a Plugin Hub release;
- generates optional item-details HTML and versioned release-asset mirrors when required.

The workflow runs every three hours and can also be started manually.

## CrossPoint integration

Plugin Hub uses the generic CrossPoint plugin system. The current contract exposes generic capabilities for named catalog lists, notices, bundle installation, version tracking, compatibility filtering, and item details. These capabilities belong to the plugin system and are available to other plugins; they are not Plugin Hub-specific firmware APIs.

Plugin Hub itself is optional. Sideloaded SD-card plugins do not depend on it.

When the Plugin System is enabled, current CrossPoint can expose **Home → Plugins** and offer the Plugin Hub bootstrap when Plugin Hub is not already installed and the bootstrap entry has not been hidden.

## Plugin Hub runtime

Plugin Hub's runtime files are:

```text
manifest.json
device.json
plugin.js
README.md
```

The firmware bootstrap installs them under:

```text
/.crosspoint/plugins/pluginhub/
```

CrossPoint can discover plugins from:

```text
/.crosspoint/plugins
/plugins
/.plugins
```

Plugin updates preserve the existing discovered plugin root.

## Browser WebUI

**Release and stable synchronization:** The publishing workflows validate the release-tag versions and ensure both display titles are exactly `Plugin Hub`. The release package archives those files unchanged. Once a stable release is published, the promotion workflow aligns `stable` to the newest eligible `main` commit; catalog refreshes do the same after their generated commits. This keeps the bootstrap branch fully caught up without exposing unreleased manifest, device or browser-plugin code. The GitHub Release keeps its immutable version tag.

`plugin.js` provides the browser-side management UI wherever the firmware hosts browser plugins. It can browse Community, install/update/reinstall/remove plugins, show installed/catalog versions, and use custom catalog URLs. Action buttons are right-aligned, with yellow **Reinstall** and red **Remove** controls. A browser host may optionally open Plugin Hub with a selected plugin and a reinstall request; Plugin Hub handles it through the existing catalog installer, without requiring any special firmware implementation. Uninstalling a plugin removes its installation files; independently stored plugin data is left untouched if the firmware provides such storage.

Custom catalogs remain separate from the built-in Community catalog and are a browser-side Plugin Hub feature.

## Trust model

Automatic discovery and schema validation are not a security review or endorsement. **Community Plugins** may contain third-party code and users should treat each plugin as software from its respective publisher.

## Development validation

Run:

```text
python -m unittest discover -s tests -v
node --test tests/test_plugin_js.mjs
```

`tools/build_catalog.py` and `tools/catalog_partitions.py` are production catalog-generation code.