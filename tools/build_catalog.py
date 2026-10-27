#!/usr/bin/env python3
"""Build Plugin Hub's CrossPoint catalog from GitHub repositories and releases."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog_partitions import (
    COMMUNITY_CATALOG_MAX_BYTES,
    COMMUNITY_LIST_INDEX,
    compact_json,
    list_index_entries,
    partition_community_plugins,
    rendered_catalog_size,
    shard_filename,
)

API_BASE = "https://api.github.com"
SEARCH_QUERIES = (
    "topic:crosspoint-plugin",
    'in:name "crosspoint-plugin"',
)
CONVENTIONAL_FILES = ("manifest.json", "device.json", "plugin.js", "README.md")
DETAILS_FILE = "DETAILS.md"
DETAILS_OUTPUT_DIR = "details"
MAX_DETAILS_SOURCE_BYTES = 16 * 1024
MAX_DETAILS_HTML_BYTES = 24 * 1024
PLUGIN_DIRECTORY_SUFFIX = ".crosspoint-plugin"
ROOT_LAYOUT_EXCEPTIONS = {"crosspoint-reader/crosspoint-plugin-hub"}
VERSION_RE = re.compile(r"^[vV]?(\d+\.\d+\.\d+)$")
PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RAW_GITHUB_BASE_RE = re.compile(
    r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/(.+)$"
)
RELEASE_ASSET_SUFFIX = ".crosspoint-plugin.zip"
RELEASE_ASSET_MIRROR_DIR = "release-assets"
DUPLICATE_REPORT_OUTPUT = "duplicate-plugin-ids.json"
MAX_RELEASE_ASSET_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 256
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_PLUGIN_FILE_BYTES = 8 * 1024 * 1024
MAX_PLUGIN_TOTAL_BYTES = 16 * 1024 * 1024


class CatalogError(RuntimeError):
    pass


class GitHubRateLimitError(CatalogError):
    pass


class GitHubClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self._commit_sha_cache: dict[tuple[str, str], str] = {}

    def _request_json(self, path: str, params: dict[str, str | int] | None = None) -> Any:
        url = f"{API_BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "crosspoint-plugin-hub catalog builder",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            error_type = GitHubRateLimitError if exc.code in (403, 429) else CatalogError
            raise error_type(f"GitHub API {exc.code} for {url}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise CatalogError(f"GitHub request failed for {url}: {exc}") from exc

    def search_repositories(self, query: str, max_pages: int = 10) -> list[dict[str, Any]]:
        repositories: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            payload = self._request_json(
                "/search/repositories",
                {"q": query, "sort": "stars", "order": "desc", "per_page": 100, "page": page},
            )
            items = payload.get("items", [])
            if not isinstance(items, list):
                raise CatalogError(f"GitHub search returned an invalid items list for {query!r}")
            repositories.extend(item for item in items if isinstance(item, dict))
            if len(items) < 100:
                break
        return repositories

    def stable_releases(self, full_name: str, max_pages: int = 3) -> list[dict[str, Any]]:
        stable: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            releases = self._request_json(
                f"/repos/{full_name}/releases",
                {"per_page": 100, "page": page},
            )
            if not isinstance(releases, list):
                raise CatalogError(f"GitHub releases response is invalid for {full_name}")
            stable.extend(
                release
                for release in releases
                if isinstance(release, dict)
                and not release.get("draft")
                and not release.get("prerelease")
            )
            if len(releases) < 100:
                break
        return stable

    def latest_stable_release(self, full_name: str) -> dict[str, Any] | None:
        releases = self.stable_releases(full_name, max_pages=1)
        return releases[0] if releases else None

    def directory_contents(self, full_name: str, ref: str, path: str) -> list[dict[str, Any]]:
        payload = self._request_json(
            f"/repos/{full_name}/contents/{urllib.parse.quote(path, safe='/')}",
            {"ref": ref},
        )
        if not isinstance(payload, list):
            raise CatalogError(f"{path} is not a directory for {full_name}@{ref}")
        return [item for item in payload if isinstance(item, dict)]

    def root_contents(self, full_name: str, ref: str) -> list[dict[str, Any]]:
        payload = self._request_json(f"/repos/{full_name}/contents", {"ref": ref})
        if not isinstance(payload, list):
            raise CatalogError(f"Repository root is not a directory for {full_name}@{ref}")
        return [item for item in payload if isinstance(item, dict)]

    def json_file(self, full_name: str, ref: str, path: str) -> dict[str, Any]:
        payload = self._request_json(
            f"/repos/{full_name}/contents/{urllib.parse.quote(path, safe='/')}",
            {"ref": ref},
        )
        if not isinstance(payload, dict) or payload.get("type") != "file":
            raise CatalogError(f"{path} is not a file in {full_name}@{ref}")
        if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
            raise CatalogError(f"{path} has an unsupported GitHub API encoding in {full_name}@{ref}")
        try:
            raw = base64.b64decode(payload["content"]).decode("utf-8")
            parsed = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise CatalogError(f"{path} is not valid UTF-8 JSON in {full_name}@{ref}") from exc
        if not isinstance(parsed, dict):
            raise CatalogError(f"{path} must contain a JSON object in {full_name}@{ref}")
        return parsed

    def text_file(self, full_name: str, ref: str, path: str, max_bytes: int = MAX_DETAILS_SOURCE_BYTES) -> str:
        payload = self._request_json(
            f"/repos/{full_name}/contents/{urllib.parse.quote(path, safe='/')}",
            {"ref": ref},
        )
        if not isinstance(payload, dict) or payload.get("type") != "file":
            raise CatalogError(f"{path} is not a file in {full_name}@{ref}")
        size = payload.get("size")
        if isinstance(size, int) and size > max_bytes:
            raise CatalogError(f"{path} is too large in {full_name}@{ref}")
        if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
            raise CatalogError(f"{path} has an unsupported GitHub API encoding in {full_name}@{ref}")
        try:
            raw = base64.b64decode(payload["content"])
            if len(raw) > max_bytes:
                raise CatalogError(f"{path} is too large in {full_name}@{ref}")
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CatalogError(f"{path} is not valid UTF-8 in {full_name}@{ref}") from exc

    def repository(self, full_name: str) -> dict[str, Any]:
        payload = self._request_json(f"/repos/{full_name}")
        if not isinstance(payload, dict):
            raise CatalogError(f"GitHub repository response is invalid for {full_name}")
        return payload

    def commit_sha(self, full_name: str, ref: str) -> str:
        cache_key = (full_name.lower(), ref)
        cached = self._commit_sha_cache.get(cache_key)
        if cached is not None:
            return cached

        payload = self._request_json(
            f"/repos/{full_name}/commits/{urllib.parse.quote(ref, safe='')}"
        )
        sha = payload.get("sha") if isinstance(payload, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            raise CatalogError(f"GitHub commit response is invalid for {full_name}@{ref}")

        normalized = sha.lower()
        self._commit_sha_cache[cache_key] = normalized
        return normalized

    def fetch_json_url(self, url: str) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "crosspoint-plugin-hub catalog builder",
        }
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise CatalogError(f"HTTP {exc.code} for {url}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise CatalogError(f"Request failed for {url}: {exc}") from exc
        except ValueError as exc:
            raise CatalogError(f"Response is not valid JSON: {url}") from exc
        if not isinstance(payload, dict):
            raise CatalogError(f"JSON root must be an object: {url}")
        return payload

    def fetch_bytes_url(self, url: str, max_bytes: int = MAX_RELEASE_ASSET_BYTES) -> bytes:
        headers = {
            "Accept": "application/octet-stream",
            "User-Agent": "crosspoint-plugin-hub catalog builder",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            raise CatalogError(f"release asset exceeds {max_bytes} bytes: {url}")
                    except ValueError:
                        pass
                payload = response.read(max_bytes + 1)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            error_type = GitHubRateLimitError if exc.code in (403, 429) else CatalogError
            raise error_type(f"HTTP {exc.code} for {url}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise CatalogError(f"Request failed for {url}: {exc}") from exc
        if len(payload) > max_bytes:
            raise CatalogError(f"release asset exceeds {max_bytes} bytes: {url}")
        return payload


def normalize_version(tag: str) -> str | None:
    match = VERSION_RE.fullmatch(tag.strip())
    return match.group(1) if match else None


def normalize_compatibility_csv_field(value: Any, field: str) -> str | None:
    if value is None:
        return None
    raw_values = [value] if isinstance(value, str) else value
    if not isinstance(raw_values, list) or not all(isinstance(item, str) for item in raw_values):
        raise CatalogError(f"compatibility.{field} must be a string or string array")

    tokens: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        for part in raw.split(","):
            token = part.strip()
            if not token:
                raise CatalogError(f"compatibility.{field} contains an empty value")
            if token not in seen:
                seen.add(token)
                tokens.append(token)
    return ",".join(tokens) if tokens else None


def normalize_compatibility(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CatalogError("compatibility must be a JSON object")

    normalized: dict[str, Any] = {}
    for field in ("firmware_family", "requires"):
        tokens = normalize_compatibility_csv_field(value.get(field), field)
        if tokens is not None:
            normalized[field] = tokens

    # Advisory hardware preferences affect catalog visibility, not installation.
    ids: dict[str, str] = {}
    for field in ("devices", "exclude_devices"):
        csv = normalize_compatibility_csv_field(value.get(field), field)
        if csv is not None:
            values = csv.split(",")
            if len(values) > 20 or any(not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", item) for item in values):
                raise CatalogError(f"compatibility.{field} has invalid device IDs")
            ids[field] = csv
            normalized[field] = csv
    preferred = value.get("recommended")
    psram_mb = None
    if preferred is not None:
        if not isinstance(preferred, dict) or set(preferred) - {"min_psram_mb"}:
            raise CatalogError("compatibility.recommended has unknown fields")
        psram_mb = preferred.get("min_psram_mb")
        if psram_mb is not None:
            if type(psram_mb) is not int or not 0 <= psram_mb <= 64:
                raise CatalogError("compatibility.recommended.min_psram_mb must be 0..64")
            normalized["recommended"] = {"min_psram_mb": psram_mb}
    clauses = []
    if "devices" in ids:
        clauses.append("models=" + ids["devices"].replace(",", "|"))
    if "exclude_devices" in ids:
        clauses.append("exclude=" + ids["exclude_devices"].replace(",", "|"))
    if psram_mb is not None:
        clauses.append("psram_mb=" + str(psram_mb))
    if clauses:
        advisory = ";".join(clauses)
        if len(advisory) > 240:
            raise CatalogError("compatibility advisory exceeds 240 bytes")
        normalized["advisory"] = advisory

    api_min = value.get("plugin_api_min")
    if api_min is not None:
        if isinstance(api_min, bool):
            raise CatalogError("compatibility.plugin_api_min must be a non-negative integer")
        if isinstance(api_min, int):
            parsed_api = api_min
        elif isinstance(api_min, str) and api_min.strip().isdigit():
            parsed_api = int(api_min.strip())
        else:
            raise CatalogError("compatibility.plugin_api_min must be a non-negative integer")
        if parsed_api < 0:
            raise CatalogError("compatibility.plugin_api_min must be a non-negative integer")
        normalized["plugin_api_min"] = parsed_api

    return normalized or None


def _details_inline(text: str) -> str:
    rendered = html.escape(text.strip(), quote=False)
    rendered = re.sub(r"`([^`]+)`", r"\1", rendered)
    rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", rendered)
    return rendered


def markdown_details_to_html(markdown: str) -> str:
    if len(markdown.encode("utf-8")) > MAX_DETAILS_SOURCE_BYTES:
        raise CatalogError("DETAILS.md exceeds the supported source size")

    output: list[str] = []
    paragraph: list[str] = []
    in_list = False

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            output.append(f"<p>{_details_inline(' '.join(paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            output.append("</ul>")
            in_list = False

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            close_list()
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            output.append(f"<h{level}>{_details_inline(heading.group(2))}</h{level}>")
            continue

        if line.startswith("- "):
            flush_paragraph()
            if not in_list:
                output.append("<ul>")
                in_list = True
            output.append(f"<li>{_details_inline(line[2:])}</li>")
            continue

        close_list()
        paragraph.append(line)

    flush_paragraph()
    close_list()
    rendered = "\n".join(output).strip() + "\n"
    if len(rendered.encode("utf-8")) > MAX_DETAILS_HTML_BYTES:
        raise CatalogError("rendered plugin details exceed the supported HTML size")
    return rendered


def publish_details_assets(
    plugins: list[dict[str, Any]],
    output_root: Path,
    repository: str,
    ref: str,
) -> bool:
    if REPOSITORY_RE.fullmatch(repository) is None:
        raise CatalogError("catalog repository must be an owner/repository string")
    changed = False
    encoded_ref = urllib.parse.quote(ref, safe="")

    for plugin in plugins:
        markdown = plugin.pop("_details_markdown", None)
        if not isinstance(markdown, str) or not markdown.strip():
            continue
        plugin_id = plugin.get("name")
        version = plugin.get("version")
        if not isinstance(plugin_id, str) or PLUGIN_ID_RE.fullmatch(plugin_id) is None:
            raise CatalogError("plugin details require a safe plugin id")
        if not isinstance(version, str) or normalize_version(version) is None:
            raise CatalogError(f"plugin details require a valid version for {plugin_id}")

        rendered = markdown_details_to_html(markdown)
        relative = Path(plugin_id) / f"{version}.html"
        target = output_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            if existing != rendered:
                raise CatalogError(
                    f"refusing to rewrite details for {plugin_id} {version}; publish a new plugin version"
                )
        else:
            target.write_text(rendered, encoding="utf-8", newline="\n")
            changed = True

        raw_path = (Path(DETAILS_OUTPUT_DIR) / relative).as_posix()
        plugin["details"] = {
            "url": (
                f"https://raw.githubusercontent.com/{repository}/{encoded_ref}/"
                f"{urllib.parse.quote(raw_path, safe='/')}"
            ),
            "format": "html",
        }

    return changed


def derive_plugin_id(repo_name: str, manifest: dict[str, Any]) -> str | None:
    declared = manifest.get("name")
    if isinstance(declared, str) and PLUGIN_ID_RE.fullmatch(declared):
        return declared

    name = repo_name
    for suffix in (".crosspoint-plugin", "-crosspoint-plugin", ".xp-plugin"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    name = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return name if PLUGIN_ID_RE.fullmatch(name) else None


def safe_runtime_files(manifest: dict[str, Any], root_names: set[str]) -> list[str] | None:
    declared = manifest.get("files")
    if declared is None:
        files = [name for name in CONVENTIONAL_FILES if name in root_names]
    elif isinstance(declared, list) and all(isinstance(item, str) for item in declared):
        files = list(dict.fromkeys(declared))
    else:
        return None

    if not files or len(files) > 64:
        return None
    for path in files:
        if (
            not path
            or path.startswith("/")
            or "\\" in path
            or ".." in path.split("/")
            or len(path) > 180
        ):
            return None
    if "manifest.json" not in files:
        return None
    if "device.json" not in files and "plugin.js" not in files:
        return None
    return files


def load_whitelist(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "repositories": [],
            "release_asset_repositories": [],
            "direct_plugins": [],
            "catalogs": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"whitelist is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CatalogError("whitelist root must be an object")

    repositories = payload.get("repositories", [])
    release_asset_repositories = payload.get("release_asset_repositories", [])
    direct_plugins = payload.get("direct_plugins", [])
    catalogs = payload.get("catalogs", [])
    if not isinstance(repositories, list) or not all(
        isinstance(item, str) and REPOSITORY_RE.fullmatch(item) for item in repositories
    ):
        raise CatalogError("whitelist repositories must be owner/repository strings")
    if not isinstance(release_asset_repositories, list) or not all(
        isinstance(item, str) and REPOSITORY_RE.fullmatch(item)
        for item in release_asset_repositories
    ):
        raise CatalogError(
            "whitelist release_asset_repositories must be owner/repository strings"
        )
    if not isinstance(direct_plugins, list) or not all(
        isinstance(item, dict) for item in direct_plugins
    ):
        raise CatalogError("whitelist direct_plugins must be objects")
    if not isinstance(catalogs, list) or not all(isinstance(item, dict) for item in catalogs):
        raise CatalogError("whitelist catalogs must be objects")

    return {
        "repositories": repositories,
        "release_asset_repositories": release_asset_repositories,
        "direct_plugins": direct_plugins,
        "catalogs": catalogs,
    }


def load_blacklist(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {"repositories": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"blacklist is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CatalogError("blacklist root must be an object")

    repositories = payload.get("repositories", [])
    if not isinstance(repositories, list) or not all(
        isinstance(item, str) and REPOSITORY_RE.fullmatch(item) for item in repositories
    ):
        raise CatalogError("blacklist repositories must be owner/repository strings")

    normalized: list[str] = []
    seen: set[str] = set()
    for repository in repositories:
        key = repository.lower()
        if key not in seen:
            normalized.append(repository)
            seen.add(key)
    return {"repositories": normalized}


def github_repository_from_url(url: str) -> str | None:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split("/") if part]
    if host == "raw.githubusercontent.com" and len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    if host in {"github.com", "www.github.com"} and len(parts) >= 2:
        repo = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
        return f"{parts[0]}/{repo}"
    return None


def is_blacklisted_repository(repository: str | None, blacklisted: set[str]) -> bool:
    return isinstance(repository, str) and repository.lower() in blacklisted


def plugin_entry_is_blacklisted(plugin: dict[str, Any], blacklisted: set[str]) -> bool:
    repository = plugin.get("repository")
    if is_blacklisted_repository(repository if isinstance(repository, str) else None, blacklisted):
        return True
    for key in ("base", "source_catalog"):
        value = plugin.get(key)
        if isinstance(value, str) and is_blacklisted_repository(github_repository_from_url(value), blacklisted):
            return True
    return False


def pin_raw_github_base(client: GitHubClient, base: str) -> str:
    match = RAW_GITHUB_BASE_RE.fullmatch(base)
    if match is None:
        return base

    owner, repo, remainder = match.groups()
    parts = [part for part in remainder.split("/") if part]
    if len(parts) < 2:
        return base

    if len(parts) >= 3 and parts[0] == "refs" and parts[1] == "heads":
        ref = parts[2]
        subpath_parts = parts[3:]
    else:
        ref = parts[0]
        subpath_parts = parts[1:]

    if re.fullmatch(r"[0-9a-fA-F]{40}", ref):
        sha = ref.lower()
    else:
        sha = client.commit_sha(f"{owner}/{repo}", ref)

    suffix = "/".join(subpath_parts)
    if suffix:
        suffix += "/"
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{suffix}"


def curated_catalog_plugins(
    client: GitHubClient,
    whitelist: dict[str, Any],
    blacklisted_repositories: set[str] | None = None,
) -> list[dict[str, Any]]:
    imported: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    blacklisted = blacklisted_repositories or set()

    def normalized_entry(
        source_entry: dict[str, Any],
        plugin_id: str,
        source_catalog: str | None = None,
    ) -> dict[str, Any]:
        version_value = source_entry.get("version")
        base = source_entry.get("base")
        files_value = source_entry.get("files")
        if not isinstance(version_value, str) or normalize_version(version_value) is None:
            raise CatalogError(f"whitelisted plugin {plugin_id!r} has invalid version")
        if not isinstance(base, str) or not base.startswith(("https://", "http://")):
            raise CatalogError(f"whitelisted plugin {plugin_id!r} has invalid base")
        files = safe_runtime_files({"files": files_value}, set())
        if files is None:
            raise CatalogError(f"whitelisted plugin {plugin_id!r} has invalid files")

        title = source_entry.get("title")
        description = source_entry.get("description")
        author = source_entry.get("author")
        compatibility = normalize_compatibility(source_entry.get("compatibility"))
        entry: dict[str, Any] = {
            "name": plugin_id,
            "title": title if isinstance(title, str) and title else plugin_id,
            "description": description if isinstance(description, str) else "",
            "author": author if isinstance(author, str) else "",
            "version": normalize_version(version_value),
        }
        if source_catalog is not None:
            entry["source_catalog"] = source_catalog
        entry["base"] = pin_raw_github_base(client, base)
        entry["files"] = files
        if compatibility is not None:
            entry["compatibility"] = compatibility
        return entry

    for source_entry in whitelist.get("direct_plugins", []):
        plugin_id = source_entry.get("name")
        if not isinstance(plugin_id, str) or PLUGIN_ID_RE.fullmatch(plugin_id) is None:
            raise CatalogError("whitelist direct plugin ids are invalid")
        if plugin_id in seen_ids:
            raise CatalogError(f"duplicate whitelisted plugin id: {plugin_id}")
        imported.append(normalized_entry(source_entry, plugin_id))
        seen_ids.add(plugin_id)

    for source in whitelist.get("catalogs", []):
        url = source.get("url")
        plugin_ids = source.get("plugins")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise CatalogError("whitelist catalog url must be http(s)")
        if is_blacklisted_repository(github_repository_from_url(url), blacklisted):
            continue
        if not isinstance(plugin_ids, list) or not all(
            isinstance(item, str) and PLUGIN_ID_RE.fullmatch(item) for item in plugin_ids
        ):
            raise CatalogError(f"whitelist plugin ids are invalid for {url}")

        payload = client.fetch_json_url(url)
        source_plugins = payload.get("plugins")
        if not isinstance(source_plugins, list):
            raise CatalogError(f"catalog has no plugins list: {url}")

        by_id = {
            item.get("name"): item
            for item in source_plugins
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }

        for plugin_id in plugin_ids:
            if plugin_id in seen_ids:
                raise CatalogError(f"duplicate whitelisted plugin id: {plugin_id}")
            source_entry = by_id.get(plugin_id)
            if not isinstance(source_entry, dict):
                raise CatalogError(f"whitelisted plugin {plugin_id!r} not found in {url}")
            imported.append(normalized_entry(source_entry, plugin_id, url))
            seen_ids.add(plugin_id)

    imported.sort(key=lambda item: (item["title"].casefold(), item["name"]))
    return imported


def matching_release_assets(release: dict[str, Any]) -> list[dict[str, Any]]:
    assets = release.get("assets", [])
    if not isinstance(assets, list):
        raise CatalogError("GitHub release assets must be a list")
    matching = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and isinstance(asset.get("name"), str)
        and asset["name"].lower().endswith(RELEASE_ASSET_SUFFIX)
    ]
    return sorted(matching, key=lambda asset: asset["name"].casefold())


def _safe_archive_member_name(name: str) -> str | None:
    candidate = name[:-1] if name.endswith("/") else name
    if not candidate or candidate.startswith("/") or "\\" in candidate:
        return None
    parts = candidate.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return candidate


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    if info.create_system != 3:
        return False
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def inspect_release_asset(
    archive_bytes: bytes,
    repository: str,
    asset_name: str,
) -> tuple[dict[str, Any], list[str], dict[str, bytes]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise CatalogError(f"{repository} asset {asset_name!r} is not a valid ZIP") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_MEMBERS:
            raise CatalogError(
                f"{repository} asset {asset_name!r} has too many archive members"
            )

        members: dict[str, zipfile.ZipInfo] = {}
        casefolded: set[str] = set()
        total_uncompressed = 0
        for info in infos:
            safe_name = _safe_archive_member_name(info.filename)
            if safe_name is None:
                raise CatalogError(
                    f"{repository} asset {asset_name!r} contains an unsafe path {info.filename!r}"
                )
            if info.flag_bits & 0x1:
                raise CatalogError(
                    f"{repository} asset {asset_name!r} contains encrypted files"
                )
            if _is_zip_symlink(info):
                raise CatalogError(
                    f"{repository} asset {asset_name!r} contains a symbolic link"
                )
            if info.is_dir():
                continue
            folded = safe_name.casefold()
            if safe_name in members or folded in casefolded:
                raise CatalogError(
                    f"{repository} asset {asset_name!r} contains duplicate paths"
                )
            members[safe_name] = info
            casefolded.add(folded)
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise CatalogError(
                    f"{repository} asset {asset_name!r} is too large after extraction"
                )

        candidates: list[tuple[str, str]] = []
        for path in members:
            if path == "manifest.json":
                root = ""
            elif path.endswith("/manifest.json"):
                root = path[: -len("manifest.json")]
            else:
                continue
            if f"{root}device.json" in members or f"{root}plugin.js" in members:
                candidates.append((path, root))

        if len(candidates) != 1:
            raise CatalogError(
                f"{repository} asset {asset_name!r} must contain exactly one CrossPoint plugin root"
            )

        manifest_path, root = candidates[0]
        manifest_info = members[manifest_path]
        if manifest_info.file_size > MAX_PLUGIN_FILE_BYTES:
            raise CatalogError(
                f"{repository} asset {asset_name!r} manifest is unexpectedly large"
            )
        try:
            manifest = json.loads(archive.read(manifest_info).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CatalogError(
                f"{repository} asset {asset_name!r} has an invalid manifest.json"
            ) from exc
        if not isinstance(manifest, dict):
            raise CatalogError(
                f"{repository} asset {asset_name!r} manifest.json must be an object"
            )

        manifest_version = manifest.get("version")
        if not isinstance(manifest_version, str) or normalize_version(manifest_version) is None:
            raise CatalogError(
                f"{repository} asset {asset_name!r} has an invalid manifest version"
            )

        plugin_id = manifest.get("name")
        if not isinstance(plugin_id, str) or PLUGIN_ID_RE.fullmatch(plugin_id) is None:
            root_name = root.rstrip("/").split("/")[-1] if root else ""
            plugin_id = derive_plugin_id(root_name, {}) if root_name else None
            if plugin_id is None:
                raise CatalogError(
                    f"{repository} asset {asset_name!r} must declare a safe manifest name "
                    "or use a safe plugin directory name"
                )
            manifest = dict(manifest)
            manifest["name"] = plugin_id

        relative_members = {
            path[len(root) :]
            for path in members
            if path.startswith(root) and len(path) > len(root)
        }
        root_names = {path for path in relative_members if "/" not in path}
        files = safe_runtime_files(manifest, root_names)
        if files is None:
            raise CatalogError(
                f"{repository} asset {asset_name!r} manifest files are missing or unsafe"
            )

        payloads: dict[str, bytes] = {}
        total_plugin_bytes = 0
        for relative_path in files:
            member_path = f"{root}{relative_path}"
            info = members.get(member_path)
            if info is None:
                raise CatalogError(
                    f"{repository} asset {asset_name!r} is missing declared file {relative_path!r}"
                )
            if info.file_size > MAX_PLUGIN_FILE_BYTES:
                raise CatalogError(
                    f"{repository} asset {asset_name!r} file {relative_path!r} is too large"
                )
            total_plugin_bytes += info.file_size
            if total_plugin_bytes > MAX_PLUGIN_TOTAL_BYTES:
                raise CatalogError(
                    f"{repository} asset {asset_name!r} plugin payload is too large"
                )
            payloads[relative_path] = archive.read(info)

    return manifest, files, payloads


def mirror_plugin_payload(
    mirror_root: Path,
    plugin_id: str,
    version: str,
    payloads: dict[str, bytes],
) -> Path:
    target = mirror_root / plugin_id / version
    if target.exists():
        existing = {
            path.relative_to(target).as_posix(): path.read_bytes()
            for path in target.rglob("*")
            if path.is_file()
        }
        if existing != payloads:
            raise CatalogError(
                f"refusing to rewrite mirrored {plugin_id} {version}; publish a new plugin version"
            )
        return target

    for relative_path, payload in payloads.items():
        destination = target.joinpath(*relative_path.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    return target


def duplicate_source(plugin: dict[str, Any]) -> dict[str, str]:
    source: dict[str, str] = {}
    for key in ("repository", "source_catalog", "release", "release_asset", "base", "version", "title"):
        value = plugin.get(key)
        if isinstance(value, str) and value:
            source[key] = value
    return source


def quarantine_duplicate_plugins(
    plugins: list[dict[str, Any]],
    duplicate_reports: list[dict[str, Any]] | None = None,
    scope: str = "catalog",
) -> list[dict[str, Any]]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    for plugin in plugins:
        candidates.setdefault(plugin["name"], []).append(plugin)

    unique_plugins: list[dict[str, Any]] = []
    for plugin_id, entries in candidates.items():
        if len(entries) != 1:
            sources = [duplicate_source(entry) for entry in entries]
            sources.sort(key=lambda item: json.dumps(item, sort_keys=True))
            if duplicate_reports is not None:
                duplicate_reports.append(
                    {
                        "plugin_id": plugin_id,
                        "scope": scope,
                        "sources": sources,
                    }
                )
            print(
                f"skip duplicate plugin id {plugin_id!r} across {len(entries)} sources ({scope})",
                file=sys.stderr,
            )
            continue
        unique_plugins.append(entries[0])

    unique_plugins.sort(key=lambda item: (item["title"].casefold(), item["name"]))
    return unique_plugins


def release_asset_plugins(
    client: GitHubClient,
    repositories: list[str],
    catalog_repository: str,
    mirror_root: Path,
    blacklisted_repositories: set[str] | None = None,
    duplicate_reports: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not repositories:
        return []
    if REPOSITORY_RE.fullmatch(catalog_repository) is None:
        raise CatalogError("catalog repository must be an owner/repository string")

    candidates: list[dict[str, Any]] = []
    blacklisted = blacklisted_repositories or set()
    for full_name in repositories:
        if is_blacklisted_repository(full_name, blacklisted):
            continue
        repo = client.repository(full_name)
        if repo.get("archived") or repo.get("disabled"):
            raise CatalogError(f"configured release-asset repository is unavailable: {full_name}")

        selected_release: dict[str, Any] | None = None
        selected_assets: list[dict[str, Any]] = []
        for release in client.stable_releases(full_name):
            assets = matching_release_assets(release)
            if assets:
                selected_release = release
                selected_assets = assets
                break
        if selected_release is None:
            raise CatalogError(
                f"configured release-asset repository has no stable release containing *{RELEASE_ASSET_SUFFIX}: {full_name}"
            )

        tag = selected_release.get("tag_name")
        if not isinstance(tag, str) or not tag:
            raise CatalogError(f"selected GitHub release has no tag for {full_name}")

        for asset in selected_assets:
            asset_name = asset.get("name")
            download_url = asset.get("browser_download_url")
            if not isinstance(asset_name, str) or not isinstance(download_url, str):
                raise CatalogError(f"matching release asset metadata is incomplete for {full_name}")
            archive_bytes = client.fetch_bytes_url(download_url)
            manifest, files, payloads = inspect_release_asset(
                archive_bytes,
                full_name,
                asset_name,
            )
            plugin_id = manifest["name"]
            version = normalize_version(manifest["version"])
            assert version is not None

            mirror_rel = f"{RELEASE_ASSET_MIRROR_DIR}/{plugin_id}/{version}/"
            title = manifest.get("title")
            description = manifest.get("description")
            author = manifest.get("author")
            compatibility = normalize_compatibility(manifest.get("compatibility"))
            entry: dict[str, Any] = {
                "name": plugin_id,
                "title": title if isinstance(title, str) and title else plugin_id,
                "description": (
                    description
                    if isinstance(description, str)
                    else (repo.get("description") or "")
                ),
                "author": (
                    author
                    if isinstance(author, str)
                    else repo.get("owner", {}).get("login", "")
                ),
                "version": version,
                "repository": full_name,
                "release": tag,
                "release_url": selected_release.get("html_url", ""),
                "release_asset": asset_name,
                "published_at": selected_release.get("published_at", ""),
                "base": (
                    f"https://raw.githubusercontent.com/{catalog_repository}/main/"
                    f"{urllib.parse.quote(mirror_rel, safe='/')}"
                ),
                "files": files,
                "_mirror_payloads": payloads,
            }
            if compatibility is not None:
                entry["compatibility"] = compatibility
            if DETAILS_FILE in files:
                details_payload = payloads.get(DETAILS_FILE)
                if details_payload is not None:
                    if len(details_payload) > MAX_DETAILS_SOURCE_BYTES:
                        raise CatalogError(
                            f"{full_name} asset {asset_name!r} DETAILS.md is too large"
                        )
                    try:
                        entry["_details_markdown"] = details_payload.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise CatalogError(
                            f"{full_name} asset {asset_name!r} DETAILS.md is not valid UTF-8"
                        ) from exc
            candidates.append(entry)

    plugins = quarantine_duplicate_plugins(candidates, duplicate_reports, "release-assets")
    for entry in plugins:
        payloads = entry.pop("_mirror_payloads")
        assert isinstance(payloads, dict)
        mirror_plugin_payload(
            mirror_root,
            entry["name"],
            entry["version"],
            payloads,
        )
    return plugins


def merge_plugins(
    release_plugins: list[dict[str, Any]],
    curated_plugins: list[dict[str, Any]],
    asset_plugins: list[dict[str, Any]],
    duplicate_reports: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return quarantine_duplicate_plugins(
        [*curated_plugins, *release_plugins, *asset_plugins],
        duplicate_reports,
        "catalog-sources",
    )


def build_entry(
    client: GitHubClient,
    repo: dict[str, Any],
    release: dict[str, Any],
) -> dict[str, Any] | None:
    full_name = repo.get("full_name")
    repo_name = repo.get("name")
    tag = release.get("tag_name")
    if not all(isinstance(value, str) and value for value in (full_name, repo_name, tag)):
        return None

    version = normalize_version(tag)
    if version is None:
        print(f"skip {full_name}: release tag {tag!r} is not a three-part numeric version", file=sys.stderr)
        return None

    root = client.root_contents(full_name, tag)
    plugin_directories = sorted(
        item["name"]
        for item in root
        if item.get("type") == "dir"
        and isinstance(item.get("name"), str)
        and item["name"].endswith(PLUGIN_DIRECTORY_SUFFIX)
    )

    if plugin_directories:
        if len(plugin_directories) != 1:
            print(
                f"skip {full_name}: automatic discovery requires exactly one root-level *{PLUGIN_DIRECTORY_SUFFIX} directory",
                file=sys.stderr,
            )
            return None
        plugin_root = plugin_directories[0]
        expected_plugin_id = plugin_root[: -len(PLUGIN_DIRECTORY_SUFFIX)]
        if PLUGIN_ID_RE.fullmatch(expected_plugin_id) is None:
            print(f"skip {full_name}: plugin directory {plugin_root!r} has an unsafe plugin id", file=sys.stderr)
            return None
        runtime_root = client.directory_contents(full_name, tag, plugin_root)
        root_names = {
            item.get("name")
            for item in runtime_root
            if item.get("type") == "file" and isinstance(item.get("name"), str)
        }
        manifest_path = f"{plugin_root}/manifest.json"
        base_suffix = f"{urllib.parse.quote(plugin_root, safe='')}/"
    else:
        if full_name.lower() not in ROOT_LAYOUT_EXCEPTIONS:
            print(
                f"skip {full_name}: release {tag} has no root-level *{PLUGIN_DIRECTORY_SUFFIX} plugin directory",
                file=sys.stderr,
            )
            return None
        expected_plugin_id = None
        root_names = {
            item.get("name")
            for item in root
            if item.get("type") == "file" and isinstance(item.get("name"), str)
        }
        manifest_path = "manifest.json"
        base_suffix = ""
    # root_names now refers to the installable plugin directory (or the Plugin Hub root exception).
    if "manifest.json" not in root_names:
        print(f"skip {full_name}: plugin payload has no manifest.json", file=sys.stderr)
        return None

    try:
        manifest = client.json_file(full_name, tag, manifest_path)
    except CatalogError as exc:
        print(f"skip {full_name}: {exc}", file=sys.stderr)
        return None

    manifest_version = manifest.get("version")
    if not isinstance(manifest_version, str) or normalize_version(manifest_version) != version:
        print(
            f"skip {full_name}: manifest version {manifest_version!r} does not match release {tag!r}",
            file=sys.stderr,
        )
        return None

    if expected_plugin_id is not None:
        manifest_name = manifest.get("name")
        if not isinstance(manifest_name, str) or PLUGIN_ID_RE.fullmatch(manifest_name) is None:
            print(f"skip {full_name}: payload manifest must declare a safe plugin name", file=sys.stderr)
            return None
        if manifest_name != expected_plugin_id:
            print(
                f"skip {full_name}: plugin directory {plugin_root!r} does not match manifest plugin id {manifest_name!r}",
                file=sys.stderr,
            )
            return None

    plugin_id = derive_plugin_id(repo_name, manifest)
    if plugin_id is None:
        print(f"skip {full_name}: cannot derive a safe plugin id", file=sys.stderr)
        return None

    files = safe_runtime_files(manifest, root_names)
    if files is None:
        print(f"skip {full_name}: manifest files are missing or unsafe", file=sys.stderr)
        return None

    title = manifest.get("title") if isinstance(manifest.get("title"), str) else repo_name
    description = manifest.get("description") if isinstance(manifest.get("description"), str) else (repo.get("description") or "")
    author = manifest.get("author") if isinstance(manifest.get("author"), str) else repo.get("owner", {}).get("login", "")
    compatibility = normalize_compatibility(manifest.get("compatibility"))

    entry = {
        "name": plugin_id,
        "title": title,
        "description": description,
        "author": author,
        "version": version,
        "repository": full_name,
        "release": tag,
        "release_url": release.get("html_url", ""),
        "published_at": release.get("published_at", ""),
        "base": f"https://raw.githubusercontent.com/{full_name}/{urllib.parse.quote(tag, safe='')}/{base_suffix}",
        "files": files,
    }
    if compatibility is not None:
        entry["compatibility"] = compatibility
    if DETAILS_FILE in files and DETAILS_FILE in root_names:
        details_path = (
            f"{manifest_path.rsplit('/', 1)[0]}/{DETAILS_FILE}"
            if "/" in manifest_path
            else DETAILS_FILE
        )
        entry["_details_markdown"] = client.text_file(full_name, tag, details_path)
    return entry


def discover_plugins(
    client: GitHubClient,
    excluded_repositories: set[str] | None = None,
    max_repositories: int | None = None,
    included_repositories: list[str] | None = None,
) -> list[dict[str, Any]]:
    blacklisted = excluded_repositories or set()
    discovered: dict[str, dict[str, Any]] = {}
    for query in SEARCH_QUERIES:
        for repo in client.search_repositories(query):
            full_name = repo.get("full_name")
            if not isinstance(full_name, str):
                continue
            key = full_name.lower()
            if key not in discovered:
                discovered[key] = repo

    for full_name in included_repositories or []:
        if is_blacklisted_repository(full_name, blacklisted):
            continue
        key = full_name.lower()
        if key not in discovered:
            discovered[key] = client.repository(full_name)

    plugins: list[dict[str, Any]] = []
    for repo in discovered.values():
        full_name = repo.get("full_name", "")
        if is_blacklisted_repository(full_name, blacklisted):
            continue
        if repo.get("archived") or repo.get("disabled"):
            continue
        if max_repositories is not None and len(plugins) >= max_repositories:
            break

        try:
            release = client.latest_stable_release(full_name)
            if release is None:
                print(f"skip {full_name}: no stable GitHub release", file=sys.stderr)
                continue
            entry = build_entry(client, repo, release)
        except GitHubRateLimitError:
            raise
        except CatalogError as exc:
            print(f"skip {full_name}: {exc}", file=sys.stderr)
            continue
        if entry is None:
            continue
        plugins.append(entry)

    plugins.sort(key=lambda item: (item["title"].casefold(), item["name"]))
    return plugins


def load_existing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_duplicate_report(path: Path, duplicate_reports: list[dict[str, Any]]) -> bool:
    duplicates = sorted(
        duplicate_reports,
        key=lambda item: (item["plugin_id"], item["scope"]),
    )
    rendered = compact_json({"schema_version": 1, "duplicates": duplicates})
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    if previous == rendered:
        return False
    path.write_text(rendered, encoding="utf-8", newline="\n")
    return True


def write_catalog(
    path: Path,
    plugins: list[dict[str, Any]],
    name: str = "Plugin Hub",
) -> bool:
    existing = load_existing(path)
    old_plugins = existing.get("plugins")
    old_name = existing.get("name")
    generated_at = existing.get("generated_at")
    changed = old_plugins != plugins or old_name != name
    if changed or not isinstance(generated_at, str):
        generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    payload = {
        "name": name,
        "schema_version": 1,
        "generated_at": generated_at,
        "plugins": plugins,
    }
    rendered = compact_json(payload)
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    if previous == rendered:
        return False
    path.write_text(rendered, encoding="utf-8", newline="\n")
    return True


def write_list_index(path: Path, lists: list[dict[str, Any]]) -> bool:
    existing = load_existing(path)
    generated_at = existing.get("generated_at")
    changed = existing.get("lists") != lists
    if changed or not isinstance(generated_at, str):
        generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {"schema_version": 1, "generated_at": generated_at, "lists": lists}
    rendered = compact_json(payload)
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    if previous == rendered:
        return False
    path.write_text(rendered, encoding="utf-8", newline="\n")
    return True


def write_community_catalogs(
    community_path: Path,
    index_path: Path,
    plugins: list[dict[str, Any]],
    repository: str,
    ref: str,
    max_bytes: int,
) -> dict[str, bool]:
    try:
        partitions = partition_community_plugins(plugins, max_bytes)
    except ValueError as exc:
        raise CatalogError(str(exc)) from exc

    changes: dict[str, bool] = {}
    desired: set[Path] = set()
    for partition in partitions:
        filename = shard_filename(community_path.name, partition)
        path = community_path.with_name(filename)
        desired.add(path)
        key = "community" if not partition.label else f"community-{partition.label.lower()}"
        changes[key] = write_catalog(path, partition.plugins, partition.title)

    stale_candidates = set(community_path.parent.glob(f"{community_path.stem}-*{community_path.suffix}"))
    stale_candidates.add(community_path)
    for stale in sorted(stale_candidates - desired):
        if stale.exists():
            stale.unlink()
            changes[f"removed-{stale.name}"] = True

    lists = list_index_entries(repository, ref, community_path.name, partitions)
    changes["list-index"] = write_list_index(index_path, lists)
    return changes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="catalog.json", help="compatibility union catalog path")
    parser.add_argument("--community-output", default="community-catalog.json", help="community catalog path")
    parser.add_argument("--list-index-output", default=COMMUNITY_LIST_INDEX, help="dynamic native catalog list index path")
    parser.add_argument("--catalog-ref", default=os.environ.get("PLUGINHUB_CATALOG_REF", "main"), help="git ref used by generated raw catalog URLs")
    parser.add_argument("--community-max-bytes", type=int, default=COMMUNITY_CATALOG_MAX_BYTES, help="maximum serialized bytes per Community catalog shard")
    parser.add_argument("--whitelist", default="whitelist.json", help="curated plugin whitelist")
    parser.add_argument("--blacklist", default="blacklist.json", help="repositories omitted from all generated catalogs")
    parser.add_argument("--duplicates-output", default=DUPLICATE_REPORT_OUTPUT, help="duplicate plugin ID report path")
    parser.add_argument(
        "--exclude-repository",
        default=None,
        help="optional additional owner/repository to exclude for this run",
    )
    parser.add_argument(
        "--catalog-repository",
        default=os.environ.get("GITHUB_REPOSITORY", "crosspoint-reader/crosspoint-plugin-hub"),
        help="owner/repository used for generated release-asset mirror URLs",
    )
    parser.add_argument("--max-repositories", type=int, default=None, help="optional accepted-plugin limit for testing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    client = GitHubClient(token)
    duplicate_reports: list[dict[str, Any]] = []
    try:
        whitelist = load_whitelist(Path(args.whitelist))
        blacklist = load_blacklist(Path(args.blacklist))
        blacklisted_repositories = {repository.lower() for repository in blacklist["repositories"]}
        if args.exclude_repository:
            if REPOSITORY_RE.fullmatch(args.exclude_repository) is None:
                raise CatalogError("exclude-repository must be an owner/repository string")
            blacklisted_repositories.add(args.exclude_repository.lower())
        release_plugins = discover_plugins(
            client,
            blacklisted_repositories,
            args.max_repositories,
            whitelist.get("repositories", []),
        )
        asset_plugins = release_asset_plugins(
            client,
            whitelist.get("release_asset_repositories", []),
            args.catalog_repository,
            Path(RELEASE_ASSET_MIRROR_DIR),
            blacklisted_repositories,
            duplicate_reports,
        )
        curated_plugins = curated_catalog_plugins(client, whitelist, blacklisted_repositories)
        plugins = merge_plugins(
            release_plugins,
            curated_plugins,
            asset_plugins,
            duplicate_reports,
        )
        plugins = [plugin for plugin in plugins if not plugin_entry_is_blacklisted(plugin, blacklisted_repositories)]
        details_changed = publish_details_assets(
            plugins,
            Path(DETAILS_OUTPUT_DIR),
            args.catalog_repository,
            args.catalog_ref,
        )
    except CatalogError as exc:
        print(f"catalog build failed: {exc}", file=sys.stderr)
        return 1

    changes = {
        "details": details_changed,
        "duplicates": write_duplicate_report(Path(args.duplicates_output), duplicate_reports),
        "compatibility": write_catalog(Path(args.output), plugins, "Plugin Hub"),
    }
    try:
        changes.update(
            write_community_catalogs(
                Path(args.community_output),
                Path(args.list_index_output),
                plugins,
                args.catalog_repository,
                args.catalog_ref,
                args.community_max_bytes,
            )
        )
    except CatalogError as exc:
        print(f"catalog build failed: {exc}", file=sys.stderr)
        return 1
    changed_names = [name for name, changed in changes.items() if changed]
    print(
        f"catalogs {'updated: ' + ', '.join(changed_names) if changed_names else 'unchanged'}; "
        f"{len(plugins)} community plugins "
        f"({len(release_plugins)} release-discovered, {len(asset_plugins)} release-asset, "
        f"{len(curated_plugins)} curated, {len(duplicate_reports)} duplicate IDs quarantined)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
