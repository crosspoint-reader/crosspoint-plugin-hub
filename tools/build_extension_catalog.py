#!/usr/bin/env python3
"""Build capability-gated theme and wallpaper catalogs without changing legacy plugin catalogs.

Only published, stable GitHub release assets are indexed. Each asset is downloaded,
validated against its embedded manifest and scanned for ZIP traversal/bombs.
Nothing here adds themes/wallpapers to legacy plugin catalogs or installation paths.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import struct
import sys
import zlib
import urllib.parse
import zipfile
from collections import defaultdict
from pathlib import Path

from build_catalog import (GitHubClient, GitHubRateLimitError, CatalogError,
                           load_blacklist, is_blacklisted_repository,
                           markdown_details_to_html, DETAILS_OUTPUT_DIR,
                           MAX_DETAILS_SOURCE_BYTES, normalize_compatibility)

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
CAP = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
MAX_ZIP_BYTES = 32 * 1024 * 1024
MAX_PACK_BYTES = 64 * 1024 * 1024
MAX_MEMBERS = 128
KINDS = {
    "theme-pack": ("crosspoint-theme", "theme", "community-themes.json", "Community Themes", "theme.sd.v1"),
    "wallpaper-pack": ("crosspoint-wallpaper", "wallpaper", "community-wallpapers.json", "Community Wallpaper Packs", "wallpaper.packs.v1"),
}
SEEDS = {
    "theme-pack": ("jadehawk/halo.crosspoint-theme",),
    "wallpaper-pack": ("jadehawk/starwars.crosspoint-wallpaper",),
}
BASE_URL = "https://raw.githubusercontent.com/crosspoint-reader/crosspoint-plugin-hub/main/"
DETAILS_BY_KIND = {"theme-pack": "themes", "wallpaper-pack": "wallpapers"}


def require(condition, message):
    if not condition:
        raise CatalogError(message)


def safe_path(path):
    return (isinstance(path, str) and path and len(path) <= 180 and
            "\\" not in path and not path.startswith("/") and
            all(part not in ("", ".", "..") for part in path.split("/")) and
            all(ord(c) >= 32 and ord(c) < 127 for c in path))


def safe_manifest(manifest, ident, kind, tag):
    require(isinstance(manifest, dict), "manifest must be an object")
    require(manifest.get("kind") == kind and manifest.get("name") == ident and
            ID.fullmatch(ident) is not None, "invalid package identity or kind")
    version = manifest.get("version")
    require(isinstance(version, str) and VERSION.fullmatch(version) is not None and
            tag == "v" + version, "release tag/version mismatch")
    require(isinstance(manifest.get("title"), str) and
            0 < len(manifest["title"]) <= 60, "invalid package title")
    require(isinstance(manifest.get("author"), str) and
            0 < len(manifest["author"]) <= 120, "invalid author")
    require(isinstance(manifest.get("description"), str) and
            0 < len(manifest["description"]) <= 180, "missing or invalid short description")
    normalize_compatibility(manifest.get("compatibility"))
    declared = manifest.get("files")
    require(isinstance(declared, list) and 2 <= len(declared) <= MAX_MEMBERS and
            all(safe_path(n) for n in declared) and len(set(declared)) == len(declared) and
            {"manifest.json", "README.md", "DETAILS.md"}.issubset(declared), "unsafe or invalid manifest files")
    if kind == "wallpaper-pack":
        require(len(set(manifest) - {"kind", "name", "collection", "title", "description", "author", "version", "target_resolution", "images", "files", "compatibility"}) == 0,
                "unknown wallpaper manifest keys")
        images = manifest.get("images")
        require(isinstance(images, list) and 1 <= len(images) <= 32 and
                len(images) == len(set(images)) and all(
                    isinstance(n, str) and re.fullmatch(r"wallpapers/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,79}\.bmp", n)
                    for n in images), "invalid wallpaper images")
        require(set(declared) == set(images) | {"manifest.json", "README.md", "DETAILS.md"},
                "wallpaper files list not exact")
        collection = manifest.get("collection")
        require(isinstance(collection, str) and ID.fullmatch(collection) is not None,
                "wallpaper collection identifier required")
        resolution = manifest.get("target_resolution")
        require(isinstance(resolution, dict) and set(resolution) == {"width", "height"} and
                all(type(resolution[k]) is int and 0 < resolution[k] <= 3072 for k in ("width", "height")),
                "wallpaper variant requires target_resolution")
    else:
        resolution = manifest.get("target_resolution")
        require(isinstance(resolution, dict) and set(resolution) == {"width", "height"} and
                all(type(resolution[k]) is int and 0 < resolution[k] <= 3072 for k in ("width", "height")),
                "theme variant requires target_resolution")
        themes = manifest.get("themes")
        require(isinstance(themes, list) and 1 <= len(themes) <= 16, "missing or invalid themes")
        for theme in themes:
            require(isinstance(theme, dict), "theme metadata invalid")
            theme_id = theme.get("id")
            require(isinstance(theme_id, str) and ID.fullmatch(theme_id) is not None,
                    "invalid theme ID")
            require(theme.get("path") == f"themes/{theme_id}/theme.json" and
                    theme["path"] in declared, "invalid theme entry path")
            requires = theme.get("requires")
            require(isinstance(requires, list) and all(isinstance(x, str) and
                    CAP.fullmatch(x) for x in requires), "invalid theme requirements")
    return declared


def verify_bmp(raw, dimensions):
    import struct
    require(54 <= len(raw) <= 8 * 1024 * 1024 and raw[:2] == b"BM", "invalid BMP data")
    offset = struct.unpack_from("<I", raw, 10)[0]
    dib_size, w, h, planes, bpp, compression = struct.unpack_from("<IiiHHI", raw, 14)
    require(dib_size >= 40 and w > 0 and h != 0 and planes == 1 and
            bpp in (1, 2, 4, 8, 24, 32) and
            (compression == 0 or (bpp == 32 and compression == 3)),
            "unsupported BMP")
    require(w == dimensions["width"] and abs(h) == dimensions["height"],
            "BMP dimensions mismatch target resolution")
    require(54 <= offset <= len(raw) and ((w * bpp + 31) // 32) * 4 * abs(h) <= len(raw) - offset,
            "truncated BMP")


def sleep_image_path(relative, theme_id):
    prefix = f"themes/{theme_id}/sleep/"
    if not relative.startswith(prefix):
        return False
    name = relative[len(prefix):]
    return (5 <= len(name) <= 84 and not name.startswith(".") and ".." not in name and
            re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*\.(?:cpb|bmp)", name) is not None)


def verify_sleep_cpb(raw, resolution):
    require(len(raw) >= 20, "theme sleep CPB header missing")
    magic, version, flags, width, height, stride, size, checksum = struct.unpack_from("<4sBBHHHII", raw)
    require(magic == b"CPTB" and version == 1 and flags == 1 and
            width == resolution["width"] and height == resolution["height"] and
            stride == (width + 7) // 8 and size == len(raw) - 20 and
            size == stride * height and (zlib.crc32(raw[20:]) & 0xffffffff) == checksum,
            "theme sleep bitmap CRC or resolution invalid")


def check_asset(raw: bytes, ident: str, kind: str, tag: str):
    suffix = KINDS[kind][0]
    expected_prefix = f"{ident}.{suffix}/"
    require(len(raw) <= MAX_ZIP_BYTES, "release ZIP too large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        infos = archive.infolist()
        require(len(infos) >= 2 and (kind == "theme-pack" or len(infos) <= MAX_MEMBERS),
                "invalid ZIP member count")
        names = [i.filename for i in infos]
        require(len(names) == len(set(names)), "duplicate archive member paths")
        require(all(n.startswith(expected_prefix) and safe_path(n) and not n.endswith("/") for n in names),
                "archive contains unsafe paths or another package")
        require(all(not (i.external_attr >> 16) & 0o170000 == 0o120000 for i in infos),
                "ZIP symlinks not allowed")
        require(sum(i.file_size for i in infos) <= MAX_PACK_BYTES and
                all(0 <= i.file_size <= 8 * 1024 * 1024 for i in infos),
                "ZIP expands beyond safety limits")
        contents = {i.filename[len(expected_prefix):]: archive.read(i) for i in infos}
        manifest = json.loads(contents["manifest.json"].decode("utf-8"))
        declared = safe_manifest(manifest, ident, kind, tag)
        unexpected = set(contents) - set(declared)
        if kind == "theme-pack":
            for theme in manifest["themes"]:
                meta = json.loads(contents[theme["path"]].decode("utf-8"))
                assets = meta.get("assets", {})
                gallery = assets.get("sleep_art")
                prefix = f"themes/{theme['id']}/sleep"
                if gallery is None:
                    continue
                require(gallery == prefix, "theme sleep gallery must be a scoped directory")
                members = {f for f in unexpected if sleep_image_path(f, theme["id"])}
                require(bool(members), "theme sleep directory cannot be empty")
                types = {name.rsplit('.', 1)[-1] for name in members}
                require(len(types) == 1, "theme sleep gallery cannot mix BMP and CPB images")
                require(("bmp" in types) == ("theme.sleep-grayscale.v1" in theme["requires"]),
                        "theme grayscale gallery capability mismatch")
                for member in members:
                    if member.endswith(".bmp"):
                        verify_bmp(contents[member], manifest["target_resolution"])
                    else:
                        verify_sleep_cpb(contents[member], manifest["target_resolution"])
                unexpected -= members
        require(not unexpected and set(declared).issubset(contents),
                "release ZIP contains unrecognized files or omits required metadata")
        details_bytes = contents["DETAILS.md"]
        require(0 < len(details_bytes) <= MAX_DETAILS_SOURCE_BYTES,
                "DETAILS.md missing or exceeds size limit")
        require(bool(details_bytes.decode("utf-8").strip()), "DETAILS.md cannot be blank")
        if kind == "wallpaper-pack":
            for image in manifest["images"]:
                verify_bmp(contents[image], manifest["target_resolution"])
        else:
            for theme in manifest["themes"]:
                meta = json.loads(contents[theme["path"]].decode("utf-8"))
                require(isinstance(meta, dict), "invalid theme.json")
        return manifest
    except (zipfile.BadZipFile, KeyError, ValueError, UnicodeDecodeError) as exc:
        raise CatalogError(f"corrupt or malformed release asset: {exc}") from exc


def stable_assets(client, repo, kind):
    """All and only manifest-matched ZIP variants from newest stable release."""
    full_name = repo["full_name"]
    release = client.latest_stable_release(full_name)
    if not release:
        return []
    tag = release.get("tag_name")
    require(isinstance(tag, str) and re.fullmatch(r"v\d+\.\d+\.\d+", tag),
            "latest stable release tag must be vMAJOR.MINOR.PATCH")
    suffix = KINDS[kind][0]
    matched = [a for a in release.get("assets", []) if
               isinstance(a, dict) and isinstance(a.get("name"), str) and
               a["name"].endswith(f".{suffix}.zip")]
    require(1 <= len(matched) <= 8, "expected 1–8 install-only ZIP assets")
    results = []
    # Source details exclusively from the verified release ZIP, like plugins.
    for asset in matched:
        filename = asset["name"]
        version = tag[1:]
        ending = f"-{version}.{suffix}.zip"
        require(filename.endswith(ending), "release asset naming/version mismatch")
        ident = filename[:-len(ending)]
        require(ID.fullmatch(ident) is not None, "unsafe package ID in release asset name")
        # Theme release filename carries a resolution variant suffix, while
        # the ZIP root and embedded name carry the *stable* theme identity.
        # Never assume that only two device sizes can ever exist.
        package_id = ident
        url = asset.get("browser_download_url")
        require(isinstance(url, str) and url.startswith(
                f"https://github.com/{full_name}/releases/download/{urllib.parse.quote(tag, safe='')}/"),
                "release asset URL is not GitHub release download")
        require(type(asset.get("size")) is int and
                0 < asset["size"] <= MAX_ZIP_BYTES, "release asset too large")
        raw = client.fetch_bytes_url(url, MAX_ZIP_BYTES)
        require(len(raw) == asset["size"], "downloaded ZIP size mismatch")
        if kind == "theme-pack":
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    roots = {i.filename.split("/", 1)[0] for i in archive.infolist()}
            except zipfile.BadZipFile as exc:
                raise CatalogError("corrupt theme ZIP") from exc
            require(len(roots) == 1, "theme variant has ambiguous ZIP roots")
            root_name = next(iter(roots))
            require(root_name.endswith(".crosspoint-theme"), "missing theme ZIP root")
            package_id = root_name[:-len(".crosspoint-theme")]
            require(ID.fullmatch(package_id) is not None and
                    ident.startswith(package_id + "-") and len(ident) > len(package_id) + 1,
                    "theme release asset identity must extend the stable collection ID")
        manifest = check_asset(raw, package_id, kind, tag)
        with zipfile.ZipFile(io.BytesIO(raw)) as verified_zip:
            member = f"{package_id}.{suffix}/DETAILS.md"
            details_markdown = verified_zip.read(member).decode("utf-8")
        results.append({
            "name": package_id, "variant_name": ident, "title": manifest["title"], "author": manifest["author"],
            "manifest": manifest, "asset_url": url, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "tag": tag,
            "release_url": release.get("html_url", ""), "repository": full_name,
            "_details_markdown": details_markdown,
        })
    return results


def discover(client, kind, seeds=None, excluded=None):
    topic = KINDS[kind][0]
    repos = {}
    for item in client.search_repositories("topic:" + topic):
        if isinstance(item.get("full_name"), str):
            repos[item["full_name"].lower()] = item
    for full_name in (seeds if seeds is not None else SEEDS[kind]):
        if full_name.lower() not in repos:
            repos[full_name.lower()] = client.repository(full_name)
    found = []
    for repo in sorted(repos.values(), key=lambda x: x["full_name"].casefold()):
        if repo.get("archived") or repo.get("disabled") or repo.get("private") or is_blacklisted_repository(repo["full_name"], excluded or set()):
            continue
        try:
            found.extend(stable_assets(client, repo, kind))
        except GitHubRateLimitError:
            raise
        except CatalogError as exc:
            print(f"skip {repo['full_name']} ({kind}): {exc}", file=sys.stderr)
    return found


def catalog_items(packages, kind):
    collisions = []
    if kind == "wallpaper-pack":
        groups = defaultdict(list)
        for package in packages:
            key = (package["repository"].lower(), package["manifest"]["collection"])
            groups[key].append(package)
        items = []
        for (_, collection), variants in groups.items():
            names = [p["name"] for p in variants]
            resolutions = [(p["manifest"]["target_resolution"]["width"],
                            p["manifest"]["target_resolution"]["height"]) for p in variants]
            # One catalog collection must not combine conflicting publisher
            # identity or metadata across display variants.
            metadata = {
                (v["manifest"]["version"], v["author"], v["manifest"]["description"],
                 json.dumps(normalize_compatibility(v["manifest"].get("compatibility")), sort_keys=True))
                for v in variants
            }
            if len(metadata) != 1 or len(set(names)) != len(names) or len(set(resolutions)) != len(resolutions):
                collisions.append({"kind":kind,"collection":collection,"repository":variants[0]["repository"],
                                   "reason":"duplicate package ID or resolution in collection"})
                continue
            first = sorted(variants, key=lambda p: p["name"])[0]
            items.append({
                "name":collection, "title":re.sub(r"\s*\((?:X3|X4|X4\+|X4Pro)\)$","",first["title"],flags=re.I),
                "kind":kind, "author":first["author"], "version":first["manifest"]["version"],
                "description": first["manifest"]["description"],
                "_details_markdown":first.get("_details_markdown", ""),
                "repository":first["repository"], "release":first["tag"],
                "release_url":first["release_url"], "requires":["wallpaper.packs.v1"],
                **({"compatibility":normalize_compatibility(first["manifest"]["compatibility"])}
                   if first["manifest"].get("compatibility") else {}),
                "variants":[{"name":p["name"],"target_resolution":p["manifest"]["target_resolution"],
                             "asset_url":p["asset_url"],"sha256":p["sha256"],"bytes":p["bytes"]}
                            for p in sorted(variants,key=lambda v:v["name"])],
            })
    else:
        grouped = defaultdict(list)
        for package in packages:
            grouped[(package["repository"].lower(), package["name"])].append(package)
        items = []
        for (_, collection), variants in grouped.items():
            resolutions = [(v["manifest"]["target_resolution"]["width"],
                            v["manifest"]["target_resolution"]["height"]) for v in variants]
            metadata = {
                (v["manifest"]["version"], v["author"], v["title"],
                 v["manifest"]["description"],
                 json.dumps(v["manifest"]["themes"], sort_keys=True),
                 json.dumps(normalize_compatibility(v["manifest"].get("compatibility")), sort_keys=True),
                 v["_details_markdown"])
                for v in variants
            }
            if len(metadata) != 1 or len(set(resolutions)) != len(resolutions):
                collisions.append({"kind": kind, "collection": collection, "repository": variants[0]["repository"],
                                   "reason": "theme variant metadata or resolution conflict"})
                continue
            first = variants[0]
            m = first["manifest"]
            items.append({
                "name": collection, "title": first["title"], "kind": kind, "author": first["author"],
                "description": m["description"],
                "_details_markdown": first.get("_details_markdown", ""), "version": m["version"],
                "repository": first["repository"], "release": first["tag"],
                "release_url": first["release_url"], "requires": ["theme.sd.v1"],
                **({"compatibility": normalize_compatibility(m["compatibility"])}
                   if m.get("compatibility") else {}),
                "themes": [{"id": t["id"], "title": t.get("title", t["id"]),
                            "requires": t["requires"]} for t in m["themes"]],
                "variants": [
                    {"name": p["variant_name"], "target_resolution": p["manifest"]["target_resolution"],
                     "asset_url": p["asset_url"], "sha256": p["sha256"], "bytes": p["bytes"]}
                    for p in sorted(variants, key=lambda v: v["variant_name"])
                ],
            })
    # Ambiguous identities across repositories are quarantined, not arbitrarily chosen.
    by_name = defaultdict(list)
    for item in items:
        by_name[item["name"]].append(item)
    unique = []
    for name, group in by_name.items():
        if len(group) != 1:
            collisions.append({"kind":kind,"collection":name,
                               "repositories":sorted(x["repository"] for x in group),
                               "reason":"duplicate catalog identity"})
        else:
            unique.append(group[0])
    unique.sort(key=lambda x:(x["title"].casefold(),x["name"]))
    return unique, collisions


def publish_extension_details(items, kind, output, catalog_repository, catalog_ref):
    """Publish release-pinned, sanitized and immutable HTML details pages."""
    changed = False
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", catalog_repository):
        raise CatalogError("unsafe catalog repository")
    for item in items:
        markdown = item.pop("_details_markdown", "")
        if not isinstance(markdown, str) or not markdown.strip():
            continue
        ident, version = item["name"], item["version"]
        require(ID.fullmatch(ident) is not None and VERSION.fullmatch(version) is not None,
                "invalid extension details identity")
        relative = Path(DETAILS_OUTPUT_DIR) / "extensions" / DETAILS_BY_KIND[kind] / ident / (version + ".html")
        destination = output / relative
        rendered = markdown_details_to_html(markdown)
        if destination.exists():
            require(destination.read_text(encoding="utf-8") == rendered,
                    "published extension details changed without a version bump")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered, encoding="utf-8", newline="\n")
            changed = True
        url = (f"https://raw.githubusercontent.com/{catalog_repository}/"
               f"{urllib.parse.quote(catalog_ref, safe='')}/"
               f"{relative.as_posix()}")
        item["details"] = {"url": url, "format": "html"}
    return changed


def write_if_changed(path, payload):
    prior = None
    if path.is_file():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    if isinstance(prior, dict) and {k:v for k,v in prior.items() if k != "generated_at"} == payload:
        return False
    payload = {**payload,
               "generated_at":dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
                               .isoformat().replace("+00:00","Z")}
    path.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n",
                    encoding="utf-8",newline="\n")
    return True


def build(client, output:Path, legacy_index:Path, catalog_repository="crosspoint-reader/crosspoint-plugin-hub",
          catalog_ref="main", seeds=None, excluded=None):
    output.mkdir(parents=True,exist_ok=True)
    collected = {}
    collisions = []
    for kind, (_,_, filename,_,_) in KINDS.items():
        packages = discover(client, kind, None if seeds is None else seeds.get(kind, []), excluded)
        items, duplicate = catalog_items(packages, kind)
        publish_extension_details(items, kind, output, catalog_repository, catalog_ref)
        collected[kind] = items
        collisions.extend(duplicate)
        write_if_changed(output/filename, {
            "schema_version":2, "kind":kind, "name":KINDS[kind][3], "items":items
        })
    require(legacy_index.is_file(), "legacy catalog index missing: run the existing plugin scan first")
    previous = json.loads(legacy_index.read_text(encoding="utf-8"))
    require(isinstance(previous.get("lists"), list), "invalid legacy catalog index")
    lists = [dict(legacy, kind="plugin",items="plugins",requires=["catalog.lists"])
             for legacy in previous["lists"]]
    for kind, (_,_,filename,title,capability) in KINDS.items():
        lists.append({
            "title": title, "url":f"https://raw.githubusercontent.com/{catalog_repository}/{catalog_ref}/{filename}",
            "kind":kind, "items":"items", "requires":[capability],
            "notice":{"title":title,"message":"Third-party community content. Verify the source before installation.",
                      "confirm":"Continue","cancel":"Go Back"}
        })
    write_if_changed(output/"catalog-lists-capabilities.json",{"schema_version":2,"lists":lists})
    write_if_changed(output/"duplicate-extension-ids.json",{
        "schema_version":1,"duplicates":sorted(collisions,key=lambda x:(x["kind"],x["collection"]))
    })
    return {kind:len(items) for kind,items in collected.items()} | {"duplicates":len(collisions)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir",default=".")
    p.add_argument("--legacy-index",default="catalog-lists.json")
    p.add_argument("--blacklist",default="blacklist.json")
    p.add_argument("--catalog-repository",default=os.getenv("GITHUB_REPOSITORY","crosspoint-reader/crosspoint-plugin-hub"))
    p.add_argument("--catalog-ref",default="main")
    args=p.parse_args()
    client=GitHubClient(os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN"))
    try:
        exclusions = {repo.lower() for repo in load_blacklist(Path(args.blacklist))["repositories"]}
        result=build(client,Path(args.output_dir),Path(args.legacy_index),
                     args.catalog_repository,args.catalog_ref,excluded=exclusions)
    except (CatalogError, OSError, ValueError) as e:
        print(f"extension catalog build failed: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
