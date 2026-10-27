import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "build_catalog.py"
SPEC = importlib.util.spec_from_file_location("build_catalog", MODULE_PATH)
build_catalog = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(build_catalog)


class FakeClient:
    def __init__(self, manifest=None, root=None, directories=None, text_files=None):
        self.manifest = manifest or {}
        self.root = root or []
        self.directories = directories or {}
        self.text_files = text_files or {}

    def root_contents(self, full_name, ref):
        return self.root

    def directory_contents(self, full_name, ref, path):
        return self.directories[path]

    def json_file(self, full_name, ref, path):
        return self.manifest

    def text_file(self, full_name, ref, path, max_bytes=build_catalog.MAX_DETAILS_SOURCE_BYTES):
        return self.text_files[path]


class ReleaseAssetClient:
    def __init__(self, releases, payloads):
        self.releases = releases
        self.payloads = payloads

    def repository(self, full_name):
        owner, repo = full_name.split("/", 1)
        return {
            "full_name": full_name,
            "name": repo,
            "description": "Repository fallback description",
            "owner": {"login": owner},
        }

    def stable_releases(self, full_name):
        return self.releases

    def fetch_bytes_url(self, url):
        return self.payloads[url]


def plugin_zip(manifest, prefix="", missing=(), extras=None):
    files = manifest.get(
        "files",
        ["manifest.json", "device.json", "plugin.js", "README.md"],
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative_path in files:
            if relative_path in missing:
                continue
            archive_path = f"{prefix}{relative_path}"
            if relative_path == "manifest.json":
                payload = json.dumps(manifest).encode("utf-8")
            elif relative_path.endswith(".json"):
                payload = b"{}\n"
            elif relative_path.endswith(".js"):
                payload = b"module.exports = {};\n"
            else:
                payload = f"fixture for {relative_path}\n".encode("utf-8")
            archive.writestr(archive_path, payload)
        for path, payload in (extras or {}).items():
            archive.writestr(path, payload)
    return buffer.getvalue()


class CatalogBuilderTests(unittest.TestCase):
    def test_normalize_version_requires_three_parts_and_supports_v_prefix(self):
        self.assertEqual(build_catalog.normalize_version("v0.1.2"), "0.1.2")
        self.assertEqual(build_catalog.normalize_version("1.2.3"), "1.2.3")
        self.assertIsNone(build_catalog.normalize_version("1.2"))
        self.assertIsNone(build_catalog.normalize_version("1.2.3.4"))
        self.assertIsNone(build_catalog.normalize_version("1"))
        self.assertIsNone(build_catalog.normalize_version("1.2.3.4.5"))
        self.assertIsNone(build_catalog.normalize_version("v1.2.3-beta"))

    def test_compatibility_normalizes_strings_arrays_and_api_minimum(self):
        self.assertEqual(
            build_catalog.normalize_compatibility(
                {
                    "firmware_family": ["crosspoint", "crosspoint"],
                    "plugin_api_min": "2",
                    "requires": ["catalog.item_details", "catalog.compatibility"],
                }
            ),
            {
                "firmware_family": "crosspoint",
                "plugin_api_min": 2,
                "requires": "catalog.item_details,catalog.compatibility",
            },
        )
        self.assertIsNone(build_catalog.normalize_compatibility(None))
        self.assertIsNone(build_catalog.normalize_compatibility({}))
        with self.assertRaises(build_catalog.CatalogError):
            build_catalog.normalize_compatibility({"firmware_family": ["crosspoint", 3]})
        with self.assertRaises(build_catalog.CatalogError):
            build_catalog.normalize_compatibility({"plugin_api_min": -1})

    def test_memory_and_device_recommendations_are_advisory(self):
        result = build_catalog.normalize_compatibility({
            "devices": ["x4", "x4pro"],
            "exclude_devices": ["x3"],
            "recommended": {"min_psram_mb": 2},
            "requires": ["theme.sd.v1"],
        })
        self.assertEqual(result["advisory"], "models=x4|x4pro;exclude=x3;psram_mb=2")
        self.assertEqual(result["recommended"], {"min_psram_mb": 2})
        self.assertEqual(result["requires"], "theme.sd.v1")
        for invalid in (-1, 65, 1.5, True):
            with self.assertRaises(build_catalog.CatalogError):
                build_catalog.normalize_compatibility({"recommended": {"min_psram_mb": invalid}})
        with self.assertRaises(build_catalog.CatalogError):
            build_catalog.normalize_compatibility({"devices": ["../bad"]})
        with self.assertRaises(build_catalog.CatalogError):
            build_catalog.normalize_compatibility({"devices": ["longdevicename123456789012345678901"] * 10})

    def test_plugin_id_prefers_valid_manifest_name(self):
        manifest = {"name": "sampleplugin"}
        self.assertEqual(
            build_catalog.derive_plugin_id("SomethingElse.xp-plugin", manifest),
            "sampleplugin",
        )

    def test_plugin_id_falls_back_to_repo_name(self):
        self.assertEqual(
            build_catalog.derive_plugin_id("Example.crosspoint-plugin", {}),
            "example",
        )
        self.assertEqual(
            build_catalog.derive_plugin_id("Month-Wallpaper.crosspoint-plugin", {}),
            "month-wallpaper",
        )
        self.assertEqual(
            build_catalog.derive_plugin_id("month-wallpaper-crosspoint-plugin", {}),
            "month-wallpaper",
        )

    def test_runtime_files_default_to_conventional_plugin_files(self):
        root = {"manifest.json", "device.json", "plugin.js", "README.md", "tests"}
        self.assertEqual(
            build_catalog.safe_runtime_files({}, root),
            ["manifest.json", "device.json", "plugin.js", "README.md"],
        )

    def test_runtime_files_allow_explicit_nested_assets(self):
        manifest = {
            "files": [
                "manifest.json",
                "device.json",
                "assets/icon.bin",
                "README.md",
            ]
        }
        self.assertEqual(
            build_catalog.safe_runtime_files(manifest, {"manifest.json", "device.json"}),
            manifest["files"],
        )

    def test_runtime_files_reject_traversal_and_non_plugins(self):
        self.assertIsNone(
            build_catalog.safe_runtime_files(
                {"files": ["manifest.json", "device.json", "../secret"]},
                {"manifest.json", "device.json"},
            )
        )
        self.assertIsNone(
            build_catalog.safe_runtime_files(
                {"files": ["manifest.json", "README.md"]},
                {"manifest.json", "README.md"},
            )
        )

    def test_build_entry_uses_release_tag_as_immutable_base(self):
        client = FakeClient(
            manifest={
                "name": "sampleplugin",
                "title": "Sample Plugin",
                "description": "Example plugin for CrossPoint.",
                "author": "Example Author",
                "version": "0.1.2",
                "compatibility": {
                    "firmware_family": ["crosspoint"],
                    "plugin_api_min": 1,
                    "requires": "catalog.bundle_install,catalog.item_details",
                },
                "files": ["manifest.json", "device.json", "plugin.js", "README.md"],
            },
            root=[{"name": "sampleplugin.crosspoint-plugin", "type": "dir"}],
            directories={
                "sampleplugin.crosspoint-plugin": [
                    {"name": "manifest.json", "type": "file"},
                    {"name": "device.json", "type": "file"},
                    {"name": "plugin.js", "type": "file"},
                    {"name": "README.md", "type": "file"},
                ]
            },
        )
        repo = {
            "full_name": "example-owner/sampleplugin.crosspoint-plugin",
            "name": "sampleplugin.crosspoint-plugin",
            "description": "fallback",
            "owner": {"login": "example-owner"},
        }
        release = {
            "tag_name": "v0.1.2",
            "html_url": "https://github.com/example-owner/sampleplugin.crosspoint-plugin/releases/tag/v0.1.2",
            "published_at": "2026-10-01T12:00:00Z",
        }

        entry = build_catalog.build_entry(client, repo, release)

        self.assertIsNotNone(entry)
        self.assertEqual(entry["version"], "0.1.2")
        self.assertEqual(
            entry["base"],
            "https://raw.githubusercontent.com/example-owner/sampleplugin.crosspoint-plugin/v0.1.2/sampleplugin.crosspoint-plugin/",
        )
        self.assertEqual(entry["files"], client.manifest["files"])
        self.assertEqual(
            entry["compatibility"],
            {
                "firmware_family": "crosspoint",
                "plugin_api_min": 1,
                "requires": "catalog.bundle_install,catalog.item_details",
            },
        )

    def test_build_entry_reads_declared_details_markdown_from_release(self):
        client = FakeClient(
            manifest={
                "name": "example",
                "title": "Example",
                "version": "1.2.3",
                "files": ["manifest.json", "device.json", "DETAILS.md"],
            },
            root=[{"name": "example.crosspoint-plugin", "type": "dir"}],
            directories={
                "example.crosspoint-plugin": [
                    {"name": "manifest.json", "type": "file"},
                    {"name": "device.json", "type": "file"},
                    {"name": "DETAILS.md", "type": "file"},
                ]
            },
            text_files={"example.crosspoint-plugin/DETAILS.md": "# Example\n\n- Feature\n"},
        )
        repo = {
            "full_name": "owner/example.crosspoint-plugin",
            "name": "example.crosspoint-plugin",
            "owner": {"login": "owner"},
        }

        entry = build_catalog.build_entry(client, repo, {"tag_name": "v1.2.3"})

        self.assertIsNotNone(entry)
        self.assertEqual(entry["_details_markdown"], "# Example\n\n- Feature\n")

    def test_markdown_details_to_html_formats_supported_subset_and_escapes_html(self):
        rendered = build_catalog.markdown_details_to_html(
            "# Example\n\nSummary with **bold** and *italic* plus <script>alert(1)</script>.\n\n- One\n- Two\n"
        )

        self.assertIn("<h1>Example</h1>", rendered)
        self.assertIn("<strong>bold</strong>", rendered)
        self.assertIn("<em>italic</em>", rendered)
        self.assertIn("<ul>", rendered)
        self.assertIn("<li>One</li>", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script>", rendered)

    def test_publish_details_assets_writes_versioned_html_and_refuses_same_version_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "details"
            plugin = {
                "name": "example",
                "version": "1.2.3",
                "_details_markdown": "# Example\n\nOriginal details.\n",
            }

            changed = build_catalog.publish_details_assets(
                [plugin],
                output,
                "crosspoint-reader/crosspoint-plugin-hub",
                "main",
            )

            self.assertTrue(changed)
            self.assertTrue((output / "example" / "1.2.3.html").exists())
            self.assertEqual(
                plugin["details"],
                {
                    "url": "https://raw.githubusercontent.com/crosspoint-reader/crosspoint-plugin-hub/main/details/example/1.2.3.html",
                    "format": "html",
                },
            )
            self.assertNotIn("_details_markdown", plugin)

            with self.assertRaises(build_catalog.CatalogError):
                build_catalog.publish_details_assets(
                    [
                        {
                            "name": "example",
                            "version": "1.2.3",
                            "_details_markdown": "# Example\n\nChanged without a version bump.\n",
                        }
                    ],
                    output,
                    "crosspoint-reader/crosspoint-plugin-hub",
                    "main",
                )

    def test_build_entry_rejects_manifest_release_version_mismatch(self):
        client = FakeClient(
            manifest={
                "name": "example",
                "version": "0.1.1",
                "files": ["manifest.json", "device.json"],
            },
            root=[{"name": "example.crosspoint-plugin", "type": "dir"}],
            directories={
                "example.crosspoint-plugin": [
                    {"name": "manifest.json", "type": "file"},
                    {"name": "device.json", "type": "file"},
                ]
            },
        )
        repo = {
            "full_name": "owner/example.crosspoint-plugin",
            "name": "example.crosspoint-plugin",
            "owner": {"login": "owner"},
        }
        release = {"tag_name": "v0.1.2"}

        self.assertIsNone(build_catalog.build_entry(client, repo, release))

    def test_build_entry_rejects_root_layout_for_normal_plugins(self):
        client = FakeClient(
            manifest={"name": "example", "version": "0.1.2", "files": ["manifest.json", "device.json"]},
            root=[
                {"name": "manifest.json", "type": "file"},
                {"name": "device.json", "type": "file"},
            ],
        )
        repo = {"full_name": "owner/example.crosspoint-plugin", "name": "example.crosspoint-plugin", "owner": {"login": "owner"}}
        self.assertIsNone(build_catalog.build_entry(client, repo, {"tag_name": "v0.1.2"}))

    def test_build_entry_keeps_plugin_hub_root_layout_exception(self):
        client = FakeClient(
            manifest={"name": "pluginhub", "version": "0.1.6", "files": ["manifest.json", "device.json", "plugin.js", "README.md"]},
            root=[
                {"name": "manifest.json", "type": "file"},
                {"name": "device.json", "type": "file"},
                {"name": "plugin.js", "type": "file"},
                {"name": "README.md", "type": "file"},
            ],
        )
        repo = {"full_name": "crosspoint-reader/crosspoint-plugin-hub", "name": "crosspoint-plugin-hub", "owner": {"login": "crosspoint-reader"}}
        entry = build_catalog.build_entry(client, repo, {"tag_name": "v0.1.6"})
        self.assertIsNotNone(entry)
        self.assertEqual(entry["base"], "https://raw.githubusercontent.com/crosspoint-reader/crosspoint-plugin-hub/v0.1.6/")

    def test_build_entry_rejects_folder_manifest_id_mismatch(self):
        client = FakeClient(
            manifest={"name": "different", "version": "0.1.2", "files": ["manifest.json", "device.json"]},
            root=[{"name": "example.crosspoint-plugin", "type": "dir"}],
            directories={"example.crosspoint-plugin": [{"name": "manifest.json", "type": "file"}, {"name": "device.json", "type": "file"}]},
        )
        repo = {"full_name": "owner/example.crosspoint-plugin", "name": "example.crosspoint-plugin", "owner": {"login": "owner"}}
        self.assertIsNone(build_catalog.build_entry(client, repo, {"tag_name": "v0.1.2"}))

    def test_build_entry_requires_manifest_name_for_folder_layout(self):
        client = FakeClient(
            manifest={"version": "0.1.2", "files": ["manifest.json", "device.json"]},
            root=[{"name": "example.crosspoint-plugin", "type": "dir"}],
            directories={
                "example.crosspoint-plugin": [
                    {"name": "manifest.json", "type": "file"},
                    {"name": "device.json", "type": "file"},
                ]
            },
        )
        repo = {
            "full_name": "owner/example.crosspoint-plugin",
            "name": "example.crosspoint-plugin",
            "owner": {"login": "owner"},
        }
        self.assertIsNone(build_catalog.build_entry(client, repo, {"tag_name": "v0.1.2"}))

    def test_discovery_does_not_globally_search_xp_plugin_names(self):
        self.assertIn("topic:crosspoint-plugin", build_catalog.SEARCH_QUERIES)
        self.assertIn('in:name "crosspoint-plugin"', build_catalog.SEARCH_QUERIES)
        self.assertNotIn('in:name ".xp-plugin"', build_catalog.SEARCH_QUERIES)

    def test_pin_raw_github_base_uses_commit_sha_for_branch(self):
        class PinClient:
            def __init__(self):
                self.calls = []

            def commit_sha(self, full_name, ref):
                self.calls.append((full_name, ref))
                return "a" * 40

        client = PinClient()

        self.assertEqual(
            build_catalog.pin_raw_github_base(
                client,
                "https://raw.githubusercontent.com/itsthisjustin/sd-plugins/main/bookfusion/",
            ),
            f"https://raw.githubusercontent.com/itsthisjustin/sd-plugins/{'a' * 40}/bookfusion/",
        )
        self.assertEqual(
            build_catalog.pin_raw_github_base(
                client,
                "https://raw.githubusercontent.com/marczykm/month-wallpaper-crosspoint-plugin/refs/heads/main/",
            ),
            f"https://raw.githubusercontent.com/marczykm/month-wallpaper-crosspoint-plugin/{'a' * 40}/",
        )
        self.assertEqual(
            client.calls,
            [
                ("itsthisjustin/sd-plugins", "main"),
                ("marczykm/month-wallpaper-crosspoint-plugin", "main"),
            ],
        )

    def test_curated_catalog_imports_only_whitelisted_plugins(self):
        class CuratedClient:
            def fetch_json_url(self, url):
                return {
                    "plugins": [
                        {
                            "name": "bookfusion",
                            "title": "BookFusion",
                            "description": "Browse books.",
                            "author": "Diirge",
                            "version": "1.2.0",
                            "compatibility": {
                                "firmware_family": "crosspoint",
                                "requires": ["catalog.bundle_install", "catalog.compatibility"],
                            },
                            "base": "https://raw.githubusercontent.com/itsthisjustin/sd-plugins/main/bookfusion/",
                            "files": [
                                "manifest.json",
                                "device.json",
                                "plugin.js",
                                "README.md",
                            ],
                        },
                        {
                            "name": "sampleplugin",
                            "title": "Old Sample Plugin",
                            "description": "Legacy entry.",
                            "author": "Example Author",
                            "version": "0.1.0",
                            "base": "https://example.invalid/",
                            "files": ["manifest.json", "device.json"],
                        },
                    ]
                }

            def commit_sha(self, full_name, ref):
                return "b" * 40

        whitelist = {
            "repositories": [],
            "catalogs": [
                {
                    "url": "https://example.test/catalog.json",
                    "plugins": ["bookfusion"],
                }
            ],
        }

        plugins = build_catalog.curated_catalog_plugins(CuratedClient(), whitelist)

        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0]["name"], "bookfusion")
        self.assertEqual(plugins[0]["version"], "1.2.0")
        self.assertEqual(
            plugins[0]["base"],
            f"https://raw.githubusercontent.com/itsthisjustin/sd-plugins/{'b' * 40}/bookfusion/",
        )
        self.assertEqual(plugins[0]["source_catalog"], "https://example.test/catalog.json")
        self.assertEqual(
            plugins[0]["compatibility"],
            {
                "firmware_family": "crosspoint",
                "requires": "catalog.bundle_install,catalog.compatibility",
            },
        )

    def test_direct_whitelist_plugin_is_ingested_without_source_catalog(self):
        whitelist = {
            "direct_plugins": [
                {
                    "name": "protected-content",
                    "title": "Protected Content",
                    "description": "Fulfill protected content from an online provider.",
                    "author": "Diirge",
                    "version": "1.0.5",
                    "base": "https://protected-content-host-production.up.railway.app/",
                    "files": ["manifest.json", "plugin.js"],
                }
            ],
            "catalogs": [],
        }

        plugins = build_catalog.curated_catalog_plugins(object(), whitelist)

        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0]["name"], "protected-content")
        self.assertEqual(plugins[0]["version"], "1.0.5")
        self.assertEqual(
            plugins[0]["base"],
            "https://protected-content-host-production.up.railway.app/",
        )
        self.assertEqual(plugins[0]["files"], ["manifest.json", "plugin.js"])
        self.assertNotIn("source_catalog", plugins[0])

    def test_direct_and_catalog_whitelist_duplicate_id_is_rejected(self):
        class CuratedClient:
            def fetch_json_url(self, url):
                return {
                    "plugins": [
                        {
                            "name": "protected-content",
                            "version": "1.0.5",
                            "base": "https://example.test/protected-content/",
                            "files": ["manifest.json", "plugin.js"],
                        }
                    ]
                }

        direct = {
            "name": "protected-content",
            "title": "Protected Content",
            "version": "1.0.5",
            "base": "https://protected-content-host-production.up.railway.app/",
            "files": ["manifest.json", "plugin.js"],
        }
        whitelist = {
            "direct_plugins": [direct],
            "catalogs": [
                {
                    "url": "https://example.test/catalog.json",
                    "plugins": ["protected-content"],
                }
            ],
        }

        with self.assertRaises(build_catalog.CatalogError):
            build_catalog.curated_catalog_plugins(CuratedClient(), whitelist)

    def test_duplicate_plugin_id_is_quarantined_without_blocking_other_plugins(self):
        first = {
            "name": "example",
            "title": "Example",
            "version": "1.0.0",
            "repository": "owner/one",
        }
        second = {
            "name": "example",
            "title": "Example Fork",
            "version": "2.0.0",
            "repository": "owner/two",
        }
        unique = {
            "name": "unique",
            "title": "Unique",
            "version": "1.0.0",
            "repository": "owner/unique",
        }
        duplicate_reports = []

        plugins = build_catalog.merge_plugins(
            [first, second, unique],
            [],
            [],
            duplicate_reports,
        )

        self.assertEqual([plugin["name"] for plugin in plugins], ["unique"])
        self.assertEqual(len(duplicate_reports), 1)
        self.assertEqual(duplicate_reports[0]["plugin_id"], "example")
        self.assertEqual(duplicate_reports[0]["scope"], "catalog-sources")
        self.assertEqual(
            [source["repository"] for source in duplicate_reports[0]["sources"]],
            ["owner/one", "owner/two"],
        )

    def test_discovery_preserves_duplicate_ids_for_collision_check(self):
        class DuplicateDiscoveryClient:
            repositories = [
                {
                    "full_name": "owner/one.crosspoint-plugin",
                    "name": "one.crosspoint-plugin",
                    "owner": {"login": "owner"},
                },
                {
                    "full_name": "other/two.crosspoint-plugin",
                    "name": "two.crosspoint-plugin",
                    "owner": {"login": "other"},
                },
            ]

            def search_repositories(self, query):
                return self.repositories

            def latest_stable_release(self, full_name):
                return {"tag_name": "v1.0.0"}

            def root_contents(self, full_name, ref):
                return [{"name": "duplicate-id.crosspoint-plugin", "type": "dir"}]

            def directory_contents(self, full_name, ref, path):
                return [
                    {"name": "manifest.json", "type": "file"},
                    {"name": "plugin.js", "type": "file"},
                ]

            def json_file(self, full_name, ref, path):
                return {
                    "name": "duplicate-id",
                    "title": full_name,
                    "version": "1.0.0",
                    "files": ["manifest.json", "plugin.js"],
                }

        discovered = build_catalog.discover_plugins(DuplicateDiscoveryClient())

        self.assertEqual(len(discovered), 2)
        self.assertEqual([item["name"] for item in discovered], ["duplicate-id", "duplicate-id"])
        duplicate_reports = []
        plugins = build_catalog.merge_plugins(discovered, [], [], duplicate_reports)
        self.assertEqual(plugins, [])
        self.assertEqual(duplicate_reports[0]["plugin_id"], "duplicate-id")

    def test_load_whitelist_accepts_manual_release_asset_repository_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "whitelist.json"
            path.write_text(
                json.dumps(
                    {
                        "repositories": [],
                        "release_asset_repositories": ["readest/readest"],
                        "direct_plugins": [
                            {
                                "name": "protected-content",
                                "title": "Protected Content",
                                "version": "1.0.5",
                                "base": "https://protected-content-host-production.up.railway.app/",
                                "files": ["manifest.json", "plugin.js"],
                            }
                        ],
                        "catalogs": [],
                    }
                ),
                encoding="utf-8",
            )

            whitelist = build_catalog.load_whitelist(path)

        self.assertEqual(
            whitelist["release_asset_repositories"],
            ["readest/readest"],
        )
        self.assertEqual(whitelist["direct_plugins"][0]["name"], "protected-content")

    def test_release_asset_repository_uses_latest_stable_release_with_matching_zip(self):
        manifest = {
            "title": "Readest",
            "description": "Readest for CrossPoint.",
            "author": "Readest",
            "version": "0.12.10",
            "compatibility": {
                "plugin_api_min": 1,
            },
            "files": ["manifest.json", "device.json", "plugin.js", "README.md"],
        }
        payload = plugin_zip(manifest, prefix="readest/")
        releases = [
            {
                "tag_name": "v0.13.0",
                "assets": [{"name": "Readest-0.13.0-windows.zip"}],
            },
            {
                "tag_name": "v0.12.10",
                "html_url": "https://github.com/readest/readest/releases/tag/v0.12.10",
                "published_at": "2026-09-21T00:00:00Z",
                "assets": [
                    {
                        "name": "Readest-0.12.10.crosspoint-plugin.zip",
                        "browser_download_url": "memory://readest",
                    }
                ],
            },
        ]
        client = ReleaseAssetClient(releases, {"memory://readest": payload})

        with tempfile.TemporaryDirectory() as temp_dir:
            mirror_root = Path(temp_dir) / "release-assets"
            plugins = build_catalog.release_asset_plugins(
                client,
                ["readest/readest"],
                "crosspoint-reader/crosspoint-plugin-hub",
                mirror_root,
            )
            mirrored_manifest = mirror_root / "readest" / "0.12.10" / "manifest.json"
            self.assertTrue(mirrored_manifest.exists())
            self.assertEqual(json.loads(mirrored_manifest.read_text())["version"], "0.12.10")

        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0]["name"], "readest")
        self.assertEqual(plugins[0]["version"], "0.12.10")
        self.assertEqual(plugins[0]["release"], "v0.12.10")
        self.assertEqual(
            plugins[0]["release_asset"],
            "Readest-0.12.10.crosspoint-plugin.zip",
        )
        self.assertEqual(
            plugins[0]["base"],
            "https://raw.githubusercontent.com/crosspoint-reader/crosspoint-plugin-hub/main/release-assets/readest/0.12.10/",
        )
        self.assertEqual(
            plugins[0]["compatibility"],
            {"plugin_api_min": 1},
        )

    def test_release_asset_repository_processes_multiple_matching_zips(self):
        first_manifest = {
            "name": "first-plugin",
            "version": "1.0.0",
            "files": ["manifest.json", "device.json"],
        }
        second_manifest = {
            "name": "second-plugin",
            "version": "2.0.0",
            "files": ["manifest.json", "plugin.js"],
        }
        releases = [
            {
                "tag_name": "v9.9.9",
                "assets": [
                    {
                        "name": "First.crosspoint-plugin.zip",
                        "browser_download_url": "memory://first",
                    },
                    {
                        "name": "Second.crosspoint-plugin.zip",
                        "browser_download_url": "memory://second",
                    },
                ],
            }
        ]
        client = ReleaseAssetClient(
            releases,
            {
                "memory://first": plugin_zip(first_manifest),
                "memory://second": plugin_zip(second_manifest),
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            plugins = build_catalog.release_asset_plugins(
                client,
                ["owner/monorepo"],
                "crosspoint-reader/crosspoint-plugin-hub",
                Path(temp_dir) / "release-assets",
            )

        self.assertEqual([plugin["name"] for plugin in plugins], ["first-plugin", "second-plugin"])
        self.assertEqual([plugin["version"] for plugin in plugins], ["1.0.0", "2.0.0"])
        self.assertTrue(all(plugin["release"] == "v9.9.9" for plugin in plugins))

    def test_release_asset_duplicate_ids_are_quarantined_before_mirroring(self):
        first_manifest = {
            "name": "duplicate-plugin",
            "version": "1.0.0",
            "files": ["manifest.json", "device.json"],
        }
        second_manifest = {
            "name": "duplicate-plugin",
            "version": "2.0.0",
            "files": ["manifest.json", "plugin.js"],
        }
        releases = [
            {
                "tag_name": "v9.9.9",
                "assets": [
                    {
                        "name": "First.crosspoint-plugin.zip",
                        "browser_download_url": "memory://first",
                    },
                    {
                        "name": "Second.crosspoint-plugin.zip",
                        "browser_download_url": "memory://second",
                    },
                ],
            }
        ]
        client = ReleaseAssetClient(
            releases,
            {
                "memory://first": plugin_zip(first_manifest),
                "memory://second": plugin_zip(second_manifest),
            },
        )
        duplicate_reports = []

        with tempfile.TemporaryDirectory() as temp_dir:
            mirror_root = Path(temp_dir) / "release-assets"
            plugins = build_catalog.release_asset_plugins(
                client,
                ["owner/monorepo"],
                "crosspoint-reader/crosspoint-plugin-hub",
                mirror_root,
                duplicate_reports=duplicate_reports,
            )
            self.assertFalse(mirror_root.exists())

        self.assertEqual(plugins, [])
        self.assertEqual(len(duplicate_reports), 1)
        self.assertEqual(duplicate_reports[0]["plugin_id"], "duplicate-plugin")
        self.assertEqual(duplicate_reports[0]["scope"], "release-assets")
        self.assertEqual(
            [source["release_asset"] for source in duplicate_reports[0]["sources"]],
            ["First.crosspoint-plugin.zip", "Second.crosspoint-plugin.zip"],
        )

    def test_release_asset_rejects_unsafe_archive_paths(self):
        manifest = {
            "name": "unsafe",
            "version": "1.0.0",
            "files": ["manifest.json", "device.json"],
        }
        payload = plugin_zip(manifest, extras={"../secret.txt": b"nope"})

        with self.assertRaises(build_catalog.CatalogError):
            build_catalog.inspect_release_asset(payload, "owner/repo", "unsafe.crosspoint-plugin.zip")

    def test_release_asset_rejects_missing_declared_files(self):
        manifest = {
            "name": "broken",
            "version": "1.0.0",
            "files": ["manifest.json", "device.json", "assets/icon.bin"],
        }
        payload = plugin_zip(manifest, missing={"assets/icon.bin"})

        with self.assertRaises(build_catalog.CatalogError):
            build_catalog.inspect_release_asset(payload, "owner/repo", "broken.crosspoint-plugin.zip")

    def test_mirror_rejects_same_version_payload_mutation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "release-assets"
            build_catalog.mirror_plugin_payload(
                root,
                "example",
                "1.0.0",
                {"manifest.json": b"one", "device.json": b"{}"},
            )
            with self.assertRaises(build_catalog.CatalogError):
                build_catalog.mirror_plugin_payload(
                    root,
                    "example",
                    "1.0.0",
                    {"manifest.json": b"two", "device.json": b"{}"},
                )

    def test_configured_release_asset_repository_without_matching_zip_fails(self):
        client = ReleaseAssetClient(
            [{"tag_name": "v1.0.0", "assets": [{"name": "desktop.zip"}]}],
            {},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(build_catalog.CatalogError):
                build_catalog.release_asset_plugins(
                    client,
                    ["owner/monorepo"],
                    "crosspoint-reader/crosspoint-plugin-hub",
                    Path(temp_dir) / "release-assets",
                )

    def test_blacklist_loader_deduplicates_repositories_case_insensitively(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "blacklist.json"
            path.write_text(
                json.dumps({"repositories": ["Owner/Repo", "owner/repo", "other/plugin"]}),
                encoding="utf-8",
            )
            blacklist = build_catalog.load_blacklist(path)

        self.assertEqual(blacklist["repositories"], ["Owner/Repo", "other/plugin"])

    def test_blacklisted_repository_is_skipped_before_release_lookup(self):
        class BlacklistedClient:
            def search_repositories(self, query):
                return [{"full_name": "owner/blocked", "name": "blocked", "owner": {"login": "owner"}}]

            def latest_stable_release(self, full_name):
                raise AssertionError("blacklisted repository must not reach release lookup")

        plugins = build_catalog.discover_plugins(BlacklistedClient(), {"owner/blocked"})
        self.assertEqual(plugins, [])

    def test_blacklisted_release_asset_repository_is_skipped(self):
        class BlacklistedAssetClient:
            def repository(self, full_name):
                raise AssertionError("blacklisted release-asset repository must not be queried")

        with tempfile.TemporaryDirectory() as temp_dir:
            plugins = build_catalog.release_asset_plugins(
                BlacklistedAssetClient(),
                ["owner/blocked"],
                "crosspoint-reader/crosspoint-plugin-hub",
                Path(temp_dir) / "release-assets",
                {"owner/blocked"},
            )
        self.assertEqual(plugins, [])

    def test_blacklist_blocks_curated_catalog_source_and_plugin_base(self):
        class CuratedClient:
            def fetch_json_url(self, url):
                raise AssertionError("blacklisted curated catalog must not be fetched")

        whitelist = {
            "catalogs": [
                {
                    "url": "https://raw.githubusercontent.com/owner/blocked/main/catalog.json",
                    "plugins": ["blocked"],
                }
            ]
        }
        self.assertEqual(
            build_catalog.curated_catalog_plugins(CuratedClient(), whitelist, {"owner/blocked"}),
            [],
        )

        curated_entry = {
            "name": "blocked-base",
            "title": "Blocked Base",
            "version": "1.0.0",
            "source_catalog": "https://raw.githubusercontent.com/owner/catalog/main/catalog.json",
            "base": "https://raw.githubusercontent.com/owner/blocked/main/blocked-base/",
            "files": ["manifest.json", "plugin.js"],
        }
        plugins = build_catalog.merge_plugins([], [curated_entry], [])
        self.assertEqual(len(plugins), 1)
        self.assertTrue(build_catalog.plugin_entry_is_blacklisted(plugins[0], {"owner/blocked"}))

    def test_rate_limit_aborts_catalog_build_instead_of_publishing_partial_results(self):
        class RateLimitedClient:
            def search_repositories(self, query):
                return [
                    {
                        "full_name": "owner/example.xp-plugin",
                        "name": "example.xp-plugin",
                        "owner": {"login": "owner"},
                    }
                ]

            def latest_stable_release(self, full_name):
                raise build_catalog.GitHubRateLimitError("rate limited")

        with self.assertRaises(build_catalog.GitHubRateLimitError):
            build_catalog.discover_plugins(RateLimitedClient())

    def test_write_duplicate_report_is_deterministic_and_clears_resolved_duplicates(self):
        duplicate_reports = [
            {
                "plugin_id": "example",
                "scope": "catalog-sources",
                "sources": [
                    {"repository": "owner/two", "version": "2.0.0"},
                    {"repository": "owner/one", "version": "1.0.0"},
                ],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "duplicate-plugin-ids.json"
            self.assertTrue(build_catalog.write_duplicate_report(path, duplicate_reports))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["duplicates"][0]["plugin_id"], "example")
            self.assertFalse(build_catalog.write_duplicate_report(path, duplicate_reports))
            self.assertTrue(build_catalog.write_duplicate_report(path, []))
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"schema_version": 1, "duplicates": []},
            )

    def test_write_catalog_does_not_churn_timestamp_when_plugins_are_unchanged(self):
        plugins = [{"name": "example", "title": "Example"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "catalog.json"
            path.write_text(
                json.dumps(
                    {
                        "name": "Plugin Hub",
                        "schema_version": 1,
                        "generated_at": "2026-10-01T00:00:00Z",
                        "plugins": plugins,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            changed = build_catalog.write_catalog(path, plugins)
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertTrue(changed)
            self.assertEqual(payload["generated_at"], "2026-10-01T00:00:00Z")
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)

            changed_again = build_catalog.write_catalog(path, plugins)
            self.assertFalse(changed_again)


    def _synthetic_community_plugins(self):
        plugins = []
        for code in range(ord("A"), ord("Z") + 1):
            letter = chr(code)
            plugins.append(
                {
                    "name": f"{letter.lower()}-plugin",
                    "title": f"{letter} Plugin",
                    "description": "x" * 240,
                    "author": "Stress Author",
                    "version": "1.0.0",
                    "base": f"https://example.invalid/{letter.lower()}/",
                    "files": ["manifest.json", "device.json", "plugin.js"],
                }
            )
        return plugins

    def test_partition_community_plugins_uses_minimum_balanced_letter_ranges(self):
        plugins = self._synthetic_community_plugins()
        full_size = build_catalog.rendered_catalog_size(plugins, "Community Plugins")
        max_bytes = int(full_size * 0.60)

        partitions = build_catalog.partition_community_plugins(plugins, max_bytes)

        self.assertEqual(len(partitions), 2)
        self.assertEqual(
            [plugin["name"] for part in partitions for plugin in part.plugins],
            [plugin["name"] for plugin in plugins],
        )
        for part in partitions:
            self.assertLessEqual(
                build_catalog.rendered_catalog_size(part.plugins, part.title),
                max_bytes,
            )
        self.assertNotEqual(partitions[0].label, "")
        self.assertNotEqual(partitions[1].label, "")

    def test_partition_community_plugins_expands_to_three_ranges_when_needed(self):
        plugins = self._synthetic_community_plugins()
        full_size = build_catalog.rendered_catalog_size(plugins, "Community Plugins")
        max_bytes = int(full_size * 0.40)

        partitions = build_catalog.partition_community_plugins(plugins, max_bytes)

        self.assertEqual(len(partitions), 3)
        for part in partitions:
            self.assertLessEqual(
                build_catalog.rendered_catalog_size(part.plugins, part.title),
                max_bytes,
            )

    def test_dynamic_list_index_repeats_community_notice_for_every_partition(self):
        plugins = self._synthetic_community_plugins()
        full_size = build_catalog.rendered_catalog_size(plugins, "Community Plugins")
        partitions = build_catalog.partition_community_plugins(plugins, int(full_size * 0.60))

        entries = build_catalog.list_index_entries(
            "crosspoint-reader/crosspoint-plugin-hub",
            "main",
            "community-catalog.json",
            partitions,
        )

        self.assertEqual(len(entries), len(partitions))
        for entry in entries:
            self.assertTrue(entry["title"].startswith("Community Plugins ["))
            self.assertEqual(entry["notice"]["message"], "Third-party plugins. Not vetted by Dev Team.")
            self.assertEqual(entry["notice"]["confirm"], "Continue")
            self.assertEqual(entry["notice"]["cancel"], "Go Back")

    def test_write_community_catalogs_removes_stale_partition_files(self):
        plugins = self._synthetic_community_plugins()
        full_size = build_catalog.rendered_catalog_size(plugins, "Community Plugins")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            community = root / "community-catalog.json"
            index = root / "catalog-lists.json"
            stale = root / "community-catalog-a-z.json"
            stale.write_text("stale", encoding="utf-8")

            build_catalog.write_community_catalogs(
                community,
                index,
                plugins,
                "crosspoint-reader/crosspoint-plugin-hub",
                "main",
                int(full_size * 0.60),
            )

            self.assertFalse(stale.exists())
            self.assertFalse(community.exists())
            payload = json.loads(index.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(payload["lists"]), 2)
            for entry in payload["lists"]:
                filename = entry["url"].rsplit("/", 1)[-1]
                self.assertTrue((root / filename).exists())



if __name__ == "__main__":
    unittest.main()
