# CrossPoint SD-plugin firmware API reference

This document is maintained locally by Plugin Hub. It describes the SD-plugin interface used by the current CrossPoint firmware. It is **not** the Plugin Hub publishing contract. Confirm capabilities against the firmware version you target; supported endpoints and limits may evolve.

## Manual plugin installation and execution

Put plugin files in one of these SD-card directories:

- `/.crosspoint/plugins/<plugin-id>/` (first priority)
- `/plugins/<plugin-id>/`
- `/.plugins/<plugin-id>/`

When an ID exists under multiple roots, the first root takes precedence. A `manifest.json` can define a display `title` and browser `mount` (`settings` or `files`). For manual loading the manifest is optional. A `plugin.js` mounts into the browser WebUI; a `device.json` creates an on-reader catalog screen. Neither requires a GitHub Release for manual installation.

## Browser plugin interface

```js
CrossPoint.registerPlugin(async (container, api) => {
  container.textContent = "Ready";
  // Register UI event handlers and use the firmware-provided api.
});
```

| Member | Behavior and return value |
| --- | --- |
| `api.name` | Installed plugin identifier |
| `api.relay(method, url, headers, body)` | Device-mediated outbound HTTP(S); returns `{status, headers, body}` |
| `api.fetchToSd(url, dest, headers)` | Streams a URL to SD; returns `{status, bytes, complete, total}` |
| `api.writeFile(path, dataB64)` | Writes a small base64-encoded file to SD; returns `{ok, bytes}` |
| `api.crypto(op, fields)` | Device cryptography; operation-specific result or `{error}` |
| `api.pluginFile(file)` | URL for an asset within the installed plugin directory |
| `api.registerAction(name, fn)` | Registers a browser-side action callable via the device job queue |

`relay` bypasses browser CORS by making the request on the device. Its response body is capped at about **32 KB**. Headers returned from `relay` are ordered `[name, value]` pairs, including duplicate names. It does **not** follow HTTP redirects. `fetchToSd` also does **not** follow redirects; resolve them before streaming. `fetchToSd` uses resumable, approximately 2 MB range segments. `writeFile` handles small requests only (roughly 32–64 KB request limit) and creates parent directories; it accepts absolute paths without traversal. Use UTF-8-aware base64 encoding:

```js
function encodeBase64Utf8(value) {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}
```

`crypto` supports random bytes, SHA-1, AES-128-CBC encryption/decryption, RSA-2048 key generation, RSA certificate encryption/signatures, and PKCS#12 parsing, using base64-encoded inputs/outputs. Treat these as low-level primitives, not a replacement for careful authentication design.

## Browser-accessible device endpoints

| Endpoint | Role |
| --- | --- |
| `GET /api/plugins` | Enumerate discovered plugins |
| `GET /plugin?name=...&file=...` | Serve installed plugin file |
| `POST /api/relay` | Generic HTTP(S) relay |
| `POST /api/fetch` | Download a URL to SD |
| `POST /api/plugin-fs` | Write a small file to SD |
| `POST /api/crypto` | Cryptographic operations |
| `POST /api/plugin-jobs` | Queue browser plugin actions; related claim/complete/status endpoints |
| `GET /plugins-run` | Browser page that services queued plugin actions while open |
| `GET /api/files?path=...` | File Manager directory entries |
| `GET /download?path=...` | Read an SD file |
| `POST /upload?path=...` | Upload to an SD directory |
| `POST /mkdir` | Create directory (form fields: `name`, `path`) |
| `POST /move`, `/rename`, `/delete` | File Manager operations |
| `GET/POST /api/settings` | Read/update settings exposed by JSON keys |

Some file-management operations reject protected dot-prefixed names. Existing paths, HTTP response handling and privilege boundaries must be checked before writing code that moves/deletes user files.

## On-reader `device.json`

This JSON file is interpreted by a generic firmware catalog activity and is limited to **less than 8 KB**. It supports authentication, catalog browsing, searching and downloading.

- `title`: label in the device Plugins screen.
- `config.file`: local JSON configuration, interpolated with `{cfg.KEY}`.
- `token.file` and `token.path`: extract an access token for `{token}`.
- `auth`: password or OAuth device-code authentication with `request` and optional `poll` definitions.
- `browse`: `format` (`json` or `xml`), `url`, `method`, `headers`, `body`, `fields`, `page_size`, optional named `lists`, and optional `search`.
- `download`: destination directory, target filename, request method/headers/body, optional `url_path` indirection, optional JSON `bundle`, and optional metadata `sidecar`.
- `events`: supported firmware lifecycle handlers such as `reader.open`, `reader.exit`, `book.downloaded`, and `sleep.enter` on firmware that implements them; handlers can request network actions or downloads and may retry.

Example browsing/search template:

```json
{
  "title": "Example Library",
  "browse": {
    "format": "json",
    "url": "https://example.invalid/books?page={page}&limit={limit}",
    "items": "books",
    "page_size": 8,
    "fields": {"title": "title", "id": "id"},
    "search": {"url": "https://example.invalid/search?q={query}&page={page}"}
  },
  "download": {
    "url": "https://example.invalid/books/{id}.epub",
    "dest_dir": "/Example",
    "filename": "{title}.epub"
  }
}
```

Template variables include `{page}`, `{limit}`, `{token}`, `{cfg.KEY}`, `{id}`, `{title}`, `{author}`, `{url}`, `{query}` (URL-encoded), `{query_raw}` (unescaped search text), and sidecar metadata variables as supported. **Never directly splice untrusted `query_raw` into JSON without validating/escaping it.**

The maximum browse page size is **16**. Paging uses `{page}` and a lookahead `{limit}` of `page_size + 1`; the device does not automatically slice a huge JSON array. JSON search requires a server capable of answering the query; `search.url` and `search.body` can each override their browse equivalents. XML supports folder-style navigation and extension filters, but not JSON search/bundle semantics. JSON browse responses have an approximate **1 MB** cap; authentication and download-URL resolution hops have a smaller roughly **48 KB** limit.

JSON bundle downloads can fetch multiple loose files to subdirectories and support redirects, unlike browser `fetchToSd`. Firmware has **no on-device ZIP/TAR extraction**; publish loose assets when using bundle download.

## Distribution catalog versus installed manifest

An upstream-style `catalog.json` is a distribution index specifying `name`, `title`, `version`, `base` URL and the list of files to install. It is not the firmware's installed `manifest.json`. Plugin Hub generates its own catalogs from validated released plugin repositories according to [PLUGIN_HUB_CONTRACT.md](../PLUGIN_HUB_CONTRACT.md). Its required release tags, repository structure, explicit `files`, and GitHub discovery topic apply to **Hub publication**, not manual loading.

## Security

Browser plugins run as JavaScript in the reader WebUI, **not isolated iframes or sandboxes**. They can access privileged same-origin endpoints, including outbound networking and SD data. Treat third-party plugin code as trusted code with device access. Never commit real API keys, authentication tokens, or configuration secrets; warn users that some plugin credentials are persisted on the SD card. Validate all URLs and filesystem paths before destructive operations.

This reference is a locally maintained summary derived from the public CrossPoint SD-plugin behavior; use firmware source and tests as the final authority when firmware APIs change.
