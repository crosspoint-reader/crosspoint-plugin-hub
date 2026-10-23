import io
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_extension_catalog as ext


def bmp(w, h):
    rowbytes = ((w * 24 + 31) // 32) * 4
    body = bytes(rowbytes * h)
    header = struct.pack("<2sIHHI", b"BM", 54 + len(body), 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(body), 2835, 2835, 0, 0)
    return header + dib + body


def payload(name, kind, collection=None, resolution=(2, 3)):
    manifest = {"kind": kind, "name": name, "title": name, "description": "19 unique e-ink wallpapers for <CrossPoint>.", "author": "Tester",
                "version": "0.1.1", "files": ["manifest.json", "README.md", "DETAILS.md"]}
    files = {"README.md": b"test", "DETAILS.md": b"# Pack\n\n19 unique e-ink wallpapers for <CrossPoint>."}
    if kind == "wallpaper-pack":
        manifest["collection"] = collection
        manifest["target_resolution"] = {"width": resolution[0], "height": resolution[1]}
        manifest["images"] = ["wallpapers/test.bmp"]
        manifest["files"].append("wallpapers/test.bmp")
        files["wallpapers/test.bmp"] = bmp(*resolution)
    else:
        manifest["themes"] = [{
            "id": name, "title": name.upper(),
            "path": f"themes/{name}/theme.json",
            "requires": ["theme.sd.v1","theme.images.v1"]
        }]
        manifest["files"].append(f"themes/{name}/theme.json")
        files[f"themes/{name}/theme.json"] = b"{}"
    files["manifest.json"] = json.dumps(manifest).encode()
    return manifest, files


def archive(name, kind, collection=None, resolution=(2, 3), tamper=None):
    manifest, files = payload(name,kind,collection,resolution)
    suffix = ext.KINDS[kind][0]
    stream = io.BytesIO()
    with zipfile.ZipFile(stream,"w",compression=zipfile.ZIP_DEFLATED) as out:
        for rel, data in files.items():
            out.writestr(f"{name}.{suffix}/{rel}",data)
        if tamper:
            out.writestr(tamper,b"rogue")
    return manifest, stream.getvalue()


class ExtensionCatalogTests(unittest.TestCase):
    def test_device_manifest_keeps_legacy_and_opt_in_v2_indexes(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        device = json.loads((root / "device.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], device["version"])
        browse = device["browse"]
        self.assertEqual(browse["lists_url"].rsplit("/", 1)[-1], "catalog-lists.json")
        self.assertEqual(browse["capability_lists_url"].rsplit("/", 1)[-1],
                         "catalog-lists-capabilities.json")
        self.assertEqual(browse["items"], "plugins")

    def test_validate_wallpaper_release_and_size(self):
        _, raw = archive("starwars-x3", "wallpaper-pack", "starwars", (528,792))
        result = ext.check_asset(raw,"starwars-x3","wallpaper-pack","v0.1.1")
        self.assertEqual(result["collection"], "starwars")
        self.assertEqual(result["target_resolution"],{"width":528,"height":792})

    def test_reject_traversal_and_multiple_payload_roots(self):
        _, raw = archive("starwars-x3","wallpaper-pack","starwars",tamper="../bad")
        with self.assertRaisesRegex(ext.CatalogError,"unsafe"):
            ext.check_asset(raw,"starwars-x3","wallpaper-pack","v0.1.1")

    def test_reject_wrong_release_version(self):
        _, raw = archive("starwars-x3","wallpaper-pack","starwars")
        with self.assertRaisesRegex(ext.CatalogError,"release tag/version"):
            ext.check_asset(raw,"starwars-x3","wallpaper-pack","v0.1.2")

    def test_duplicate_resolution_allowed_for_different_collections(self):
        src = []
        for name, group, size in (("starwars-x3","starwars",(528,792)),
                                  ("starwars-x4","starwars",(480,800)),
                                  ("yoda-x3","yoda",(528,792)),
                                  ("yoda-x4","yoda",(480,800))):
            manifest, _ = archive(name,"wallpaper-pack",group,size)
            src.append({"name":name,"manifest":manifest,"repository":"someone/wallpapers",
                        "title":name,"author":"Tester","tag":"v0.1.1",
                        "asset_url":f"https://github.com/example/{name}.zip",
                        "sha256":"0"*64,"bytes":512,"release_url":""})
        items, conflicts = ext.catalog_items(src,"wallpaper-pack")
        self.assertEqual(len(items),2)
        self.assertEqual(conflicts,[])
        self.assertEqual(sorted(len(i["variants"]) for i in items),[2,2])

    def test_duplicate_resolution_rejected_inside_collection(self):
        first, _ = archive("starwars-x3","wallpaper-pack","starwars",(528,792))
        second, _ = archive("starwars-alt","wallpaper-pack","starwars",(528,792))
        src = [{"name":ident,"manifest":manifest,"repository":"someone/wallpapers",
                "title":ident,"author":"Tester","tag":"v0.1.1",
                "asset_url":"","sha256":"0"*64,"bytes":512,"release_url":""}
               for ident,manifest in (("starwars-x3",first),("starwars-alt",second))]
        items, conflicts = ext.catalog_items(src,"wallpaper-pack")
        self.assertEqual(items,[])
        self.assertEqual(len(conflicts),1)

    def test_variant_metadata_disagreement_quarantines_collection(self):
        x, _ = archive("starwars-x3", "wallpaper-pack", "starwars", (528, 792))
        y, _ = archive("starwars-x4", "wallpaper-pack", "starwars", (480, 800))
        y["description"] = "Conflicting publisher details"
        packages = [{"name": ident, "manifest": m, "repository": "someone/wallpapers",
                     "title": m["title"], "author": m["author"], "tag": "v0.1.1",
                     "asset_url": "", "sha256": "a"*64, "bytes": 512, "release_url": ""}
                    for ident, m in (("starwars-x3", x), ("starwars-x4", y))]
        items, errors = ext.catalog_items(packages, "wallpaper-pack")
        self.assertEqual(items, [])
        self.assertEqual(len(errors), 1)

    def test_theme_manifest(self):
        _, raw = archive("halo","theme-pack")
        m = ext.check_asset(raw,"halo","theme-pack","v0.1.1")
        self.assertEqual(len(m["themes"]),1)

    def test_extension_details_publish_and_remain_immutable(self):
        manifest, _ = archive("starwars-x3", "wallpaper-pack", "starwars", (528, 792))
        item = {"name": "starwars-x3", "manifest": manifest, "repository": "artist/wallpapers",
                "title": manifest["title"], "author": "Tester", "tag": "v0.1.1",
                "release_url": "", "asset_url": "https://example.test/pack.zip",
                "bytes": 500, "sha256": "a" * 64,
                "_details_markdown": "# Pack\n\n19 unique e-ink wallpapers for <CrossPoint>."}
        entries, conflicts = ext.catalog_items([item], "wallpaper-pack")
        self.assertEqual(conflicts, [])
        self.assertEqual(entries[0]["description"], "19 unique e-ink wallpapers for <CrossPoint>.")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertTrue(ext.publish_extension_details(
                entries, "wallpaper-pack", root, "crosspoint-reader/crosspoint-plugin-hub", "main"))
            html_path = root / "details" / "extensions" / "wallpapers" / "starwars" / "0.1.1.html"
            self.assertIn("&lt;CrossPoint&gt;", html_path.read_text(encoding="utf-8"))
            self.assertNotIn("_details_markdown", entries[0])
            self.assertEqual(entries[0]["details"]["format"], "html")
            self.assertIn("/details/extensions/wallpapers/starwars/0.1.1.html",
                          entries[0]["details"]["url"])
            self.assertFalse(ext.publish_extension_details(
                entries, "wallpaper-pack", root, "crosspoint-reader/crosspoint-plugin-hub", "main"))
            entries[0]["_details_markdown"] = "# Pack\n\nModified existing release"
            with self.assertRaisesRegex(ext.CatalogError, "version bump"):
                ext.publish_extension_details(
                    entries, "wallpaper-pack", root, "crosspoint-reader/crosspoint-plugin-hub", "main")

    def test_theme_catalog_preserves_author_and_description(self):
        manifest, _ = archive("halo", "theme-pack")
        manifest["author"] = "Jadehawk + IOSDEC"
        manifest["description"] = "HALO-inspired CrossPoint UI theme"
        entry = {"name": "halo", "manifest": manifest, "repository": "artist/halo",
                 "title": "HALO", "author": manifest["author"], "tag": "v0.1.1",
                 "release_url": "", "asset_url": "https://example.test/theme.zip",
                 "bytes": 500, "sha256": "a" * 64,
                 "_details_markdown": "# HALO\n\nTheme description"}
        entries, errors = ext.catalog_items([entry], "theme-pack")
        self.assertFalse(errors)
        self.assertEqual(entries[0]["author"], "Jadehawk + IOSDEC")
        self.assertEqual(entries[0]["description"], manifest["description"])
        with tempfile.TemporaryDirectory() as temp:
            self.assertTrue(ext.publish_extension_details(
                entries, "theme-pack", Path(temp), "crosspoint-reader/crosspoint-plugin-hub", "main"))
            self.assertIn("/details/extensions/themes/halo/0.1.1.html",
                          entries[0]["details"]["url"])

    def test_extension_rich_details_come_from_release_zip_not_repository(self):
        _, raw = archive("starwars-x3", "wallpaper-pack", "starwars", (528, 792))
        url = ("https://github.com/author/wallpapers/releases/download/"
               "v0.1.1/starwars-x3-0.1.1.crosspoint-wallpaper.zip")

        class ReleaseClient:
            def latest_stable_release(self, name):
                return {"tag_name": "v0.1.1", "html_url": "https://example.test/release",
                        "assets": [{"name": "starwars-x3-0.1.1.crosspoint-wallpaper.zip",
                                    "browser_download_url": url, "size": len(raw)}]}
            def fetch_bytes_url(self, address, max_bytes):
                return raw
            def text_file(self, *args, **kwargs):
                raise AssertionError("repository-root documentation must not be queried")

        packages = ext.stable_assets(ReleaseClient(), {"full_name": "author/wallpapers"}, "wallpaper-pack")
        self.assertEqual(len(packages), 1)
        self.assertIn("19 unique e-ink", packages[0]["_details_markdown"])
        items, errors = ext.catalog_items(packages, "wallpaper-pack")
        self.assertFalse(errors)
        self.assertEqual(items[0]["author"], "Tester")
        self.assertEqual(items[0]["description"], packages[0]["manifest"]["description"])
        with tempfile.TemporaryDirectory() as temp:
            self.assertTrue(ext.publish_extension_details(
                items, "wallpaper-pack", Path(temp), "crosspoint-reader/crosspoint-plugin-hub", "main"))
            self.assertEqual(items[0]["details"]["format"], "html")

    def test_extension_payload_cannot_omit_description_or_declared_details(self):
        manifest, raw = archive("starwars-x3", "wallpaper-pack", "starwars", (528, 792))
        missing_description = dict(manifest)
        missing_description.pop("description")
        with self.assertRaisesRegex(ext.CatalogError, "short description"):
            ext.safe_manifest(missing_description, "starwars-x3", "wallpaper-pack", "v0.1.1")
        missing_details = dict(manifest)
        missing_details["files"] = [p for p in manifest["files"] if p != "DETAILS.md"]
        with self.assertRaisesRegex(ext.CatalogError, "files"):
            ext.safe_manifest(missing_details, "starwars-x3", "wallpaper-pack", "v0.1.1")

    def test_capability_index_does_not_modify_legacy_index(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            legacy = root / "catalog-lists.json"
            legacy.write_text(json.dumps({"schema_version":1,"lists":[
                {"title":"Community Plugins","url":"https://example.org/community-catalog.json"}
            ]}),encoding="utf-8")
            original = legacy.read_bytes()
            with patch.object(ext,"discover",return_value=[]):
                result = ext.build(object(),root,legacy)
            self.assertEqual(result["theme-pack"],0)
            self.assertEqual(legacy.read_bytes(),original)
            index = json.loads((root/"catalog-lists-capabilities.json").read_text())
            self.assertEqual([l["kind"] for l in index["lists"]],
                             ["plugin","theme-pack","wallpaper-pack"])
            self.assertEqual(index["lists"][2]["requires"],["wallpaper.packs.v1"])
            old_time = (root/"catalog-lists-capabilities.json").read_bytes()
            with patch.object(ext,"discover",return_value=[]):
                ext.build(object(),root,legacy)
            self.assertEqual(old_time,(root/"catalog-lists-capabilities.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
