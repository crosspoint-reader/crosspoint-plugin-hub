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
    manifest = {"kind": kind, "name": name, "title": name, "author": "Tester",
                "version": "0.1.1", "files": ["manifest.json", "README.md"]}
    files = {"README.md": b"test"}
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

    def test_theme_manifest(self):
        _, raw = archive("halo","theme-pack")
        m = ext.check_asset(raw,"halo","theme-pack","v0.1.1")
        self.assertEqual(len(m["themes"]),1)

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
