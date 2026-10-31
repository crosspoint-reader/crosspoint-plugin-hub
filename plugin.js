// Plugin Hub browser UI — manage CrossPoint plugins from the generated Hub
// catalog plus optional user-supplied catalogs.
CrossPoint.registerPlugin(async (container, api) => {
  const LEGACY_CONFIG_PATH = '/.crosspoint/plugin-hub.json';
  const PLUGIN_DIR =
    api && typeof api.dir === 'string' && api.dir.startsWith('/')
      ? api.dir.replace(/\/+$/, '')
      : null;
  const CONFIG_PATH = PLUGIN_DIR ? PLUGIN_DIR + '/config.json' : LEGACY_CONFIG_PATH;
  const PLUGIN_ROOTS = ['/.crosspoint/plugins', '/plugins', '/.plugins'];
  const PLUGINS_DIR = PLUGIN_ROOTS[0];
  const RELEASE_API_URL = 'https://api.github.com/repos/crosspoint-reader/crosspoint-plugin-hub/releases/latest';
  const UNION_CATALOG =
    'https://raw.githubusercontent.com/crosspoint-reader/crosspoint-plugin-hub/main/catalog.json';
  const COMMUNITY_CATALOG =
    'https://raw.githubusercontent.com/crosspoint-reader/crosspoint-plugin-hub/main/community-catalog.json';
  const LIST_INDEX_URL =
    'https://raw.githubusercontent.com/crosspoint-reader/crosspoint-plugin-hub/main/catalog-lists.json';

  function defaultBuiltInCatalogs() {
    return [
      {
        title: 'Community Plugins',
        description: 'Third-party plugins from CrossPoint community developers.',
        url: COMMUNITY_CATALOG
      }
    ];
  }

  let BUILT_IN_CATALOGS = defaultBuiltInCatalogs();

  let selectedCatalog = "";
  let extraCatalogs = [];

  container.innerHTML =
    '<style>' +
    '#ph-list .setting-row{display:grid;grid-template-columns:minmax(0,1fr) max-content;align-items:center;gap:12px;width:100%;box-sizing:border-box}' +
    '#ph-list .setting-name{min-width:0;overflow-wrap:anywhere}' +
    '#ph-list .setting-control{display:flex;justify-content:flex-end;gap:8px;margin-left:0;flex-wrap:nowrap}' +
    '@media(max-width:600px){#ph-list .setting-row{grid-template-columns:minmax(0,1fr)}' +
    '#ph-list .setting-control{justify-self:end}}' +
    '#ph-list .ph-btn-reinstall{background:#e8bf42!important;border-color:#b18d20!important;color:#202020!important}' +
    '#ph-list .ph-btn-remove,.ph-btn-remove{background:#bc3636!important;border-color:#922727!important;color:#fff!important}' +
    '</style>' +
    '<h2>Plugin Hub</h2>' +
    '<p id="ph-version" style="color:#666">Version: checking...</p>' +
    '<h3 style="margin:0.5em 0 0.2em">Browse plugins</h3>' +
    '<div id="ph-catalogs"></div>' +
    '<details style="margin-top:0.8em"><summary>Custom catalogs</summary>' +
    '<div id="ph-custom-catalogs"></div>' +
    '<div class="setting-row">' +
    '<span class="setting-control"><input type="text" id="ph-new" placeholder="https://.../catalog.json" style="width:100%"></span>' +
    '<button type="button" class="btn-small btn-add" id="ph-add">Add catalog</button></div>' +
    '</details>' +
    '<div class="setting-row"><button type="button" class="btn-small btn-add" id="ph-refresh">Refresh selected catalog</button></div>' +
    '<p id="ph-status"></p>' +
    '<div id="ph-list"></div>';

  const catalogsEl = document.getElementById('ph-catalogs');
  const customCatalogsEl = document.getElementById('ph-custom-catalogs');
  const listEl = document.getElementById('ph-list');
  const wallpapersEl = document.createElement('div');
  wallpapersEl.id = 'ph-wallpapers';
  const manageParams = typeof location !== 'undefined' && typeof URLSearchParams !== 'undefined'
    ? new URLSearchParams(location.search) : null;
  const requestedPlugin = String(manageParams?.get('manage') || '');
  let pendingReinstall = manageParams?.get('action') === 'reinstall' &&
                         /^[a-zA-Z0-9_-]{1,64}$/.test(requestedPlugin);
  function clearManagementIntent() {
    pendingReinstall = false;
    if (typeof history !== 'undefined' && history.replaceState) {
      history.replaceState(null, '', '/plugins?plugin=pluginhub');
    }
  }
  const status = (text) => {
    document.getElementById('ph-status').textContent = text;
  };

  function escapeHtml(value) {
    return String(value).replace(/[&<>"]/g, (c) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;'
    }[c]));
  }

  function hostOf(url) {
    try {
      return new URL(url).host;
    } catch (e) {
      return url;
    }
  }

  function b64(str) {
    const bytes = new TextEncoder().encode(str);
    let bin = '';
    for (const byte of bytes) bin += String.fromCharCode(byte);
    return btoa(bin);
  }

  function isReservedCatalog(url) {
    return (
      url === UNION_CATALOG ||
      url === COMMUNITY_CATALOG ||
      BUILT_IN_CATALOGS.some((catalog) => catalog.url === url)
    );
  }

  function normalizeExtraCatalogs(urls) {
    const seen = new Set();
    const normalized = [];
    for (const url of urls || []) {
      const trimmed = String(url || '').trim();
      if (!trimmed || isReservedCatalog(trimmed) || seen.has(trimmed)) continue;
      seen.add(trimmed);
      normalized.push(trimmed);
    }
    return normalized;
  }

  function selectedCatalogLabel() {
    const builtIn = BUILT_IN_CATALOGS.find((catalog) => catalog.url === selectedCatalog);
    return builtIn ? builtIn.title : hostOf(selectedCatalog);
  }

  async function readJsonFile(path) {
    try {
      const response = await fetch('/download?path=' + encodeURIComponent(path));
      if (!response.ok) return null;
      return JSON.parse(await response.text());
    } catch (e) {
      return null;
    }
  }

  // Discovery advisory: if firmware does not advertise hardware details,
  // preserve legacy behavior. Never consult this during installation.
  async function hardwareStatus() {
    try {
      const response = await fetch('/api/status');
      if (!response.ok) return null;
      const info = await response.json();
      if (typeof info.deviceModel !== 'string' || !Number.isFinite(info.psramBytes)) return null;
      return { model: info.deviceModel, psramBytes: info.psramBytes };
    } catch (_) {
      return null;
    }
  }

  function recommendedForHardware(plugin, hardware) {
    const advisory = plugin && plugin.compatibility && plugin.compatibility.advisory;
    if (!hardware || typeof advisory !== 'string' || !advisory) return true;
    for (const clause of advisory.split(';')) {
      const pos = clause.indexOf('=');
      if (pos < 0) continue;
      const field = clause.slice(0, pos);
      const value = clause.slice(pos + 1);
      if (field === 'models' && !value.split('|').includes(hardware.model)) return false;
      if (field === 'exclude' && value.split('|').includes(hardware.model)) return false;
      if (field === 'psram_mb') {
        const threshold = Number(value);
        if (!Number.isInteger(threshold) || threshold < 0 ||
            hardware.psramBytes < threshold * 1024 * 1024) return false;
      }
    }
    return true;
  }

  async function loadConfig() {
    const current = await readJsonFile(CONFIG_PATH);
    if (current) return current;

    if (CONFIG_PATH !== LEGACY_CONFIG_PATH) {
      const legacy = await readJsonFile(LEGACY_CONFIG_PATH);
      if (legacy) return legacy;
    }
    return {};
  }

  function saveConfig() {
    extraCatalogs = normalizeExtraCatalogs(extraCatalogs);
    if (
      !BUILT_IN_CATALOGS.some((catalog) => catalog.url === selectedCatalog) &&
      !extraCatalogs.includes(selectedCatalog)
    ) {
      selectedCatalog = BUILT_IN_CATALOGS[0]?.url || "";
    }
    return api.writeFile(
      CONFIG_PATH,
      b64(JSON.stringify({ extraCatalogs }, null, 2))
    );
  }

  async function installedPlugins() {
    const installed = new Map();
    for (const root of PLUGIN_ROOTS) {
      try {
        const response = await fetch('/api/files?path=' + encodeURIComponent(root));
        if (!response.ok) continue;
        const entries = await response.json();
        for (const entry of entries || []) {
          if (!entry || !entry.isDirectory || !entry.name || installed.has(entry.name)) continue;
          installed.set(entry.name, root + '/' + entry.name);
        }
      } catch (e) {}
    }
    return installed;
  }

  async function installedVersion(dir) {
    const manifest = await readJsonFile(dir + '/manifest.json');
    return manifest && manifest.version ? manifest.version : null;
  }

  async function hubInstalledVersion() {
    if (PLUGIN_DIR) {
      const manifest = await readJsonFile(PLUGIN_DIR + '/manifest.json');
      if (manifest && manifest.version) return manifest.version;
    }
    const installed = await installedPlugins();
    const dir = installed.get('pluginhub');
    return dir ? installedVersion(dir) : null;
  }

  function numericVersion(version) {
    const match = String(version || '').trim().match(/^v?(\d+(?:\.\d+){1,3})$/i);
    if (!match) return null;
    const parts = match[1].split('.').map((part) => Number(part));
    while (parts.length < 4) parts.push(0);
    return parts;
  }

  function compareVersions(left, right) {
    const a = numericVersion(left);
    const b = numericVersion(right);
    if (!a || !b) return null;
    for (let i = 0; i < 4; i++) {
      if (a[i] !== b[i]) return a[i] > b[i] ? 1 : -1;
    }
    return 0;
  }

  function hasUpdate(localVersion, remoteVersion) {
    if (!remoteVersion) return false;
    if (!localVersion) return true;

    const comparison = compareVersions(remoteVersion, localVersion);
    if (comparison !== null) return comparison > 0;

    // Unknown legacy formats cannot be ordered safely, so retain the old
    // mismatch behavior rather than silently hiding a possible update.
    return String(remoteVersion) !== String(localVersion);
  }

  function installedLabel(localVersion, remoteVersion) {
    if (!localVersion) return 'Installed';

    const comparison = compareVersions(localVersion, remoteVersion);
    if (remoteVersion && comparison !== null && comparison > 0) {
      return 'Installed v' + localVersion + ' (catalog v' + remoteVersion + ')';
    }
    return 'Installed v' + localVersion;
  }

  async function checkHubVersion() {
    const versionEl = document.getElementById('ph-version');
    const installed = String((await hubInstalledVersion()) || '').trim();
    if (!numericVersion(installed)) {
      versionEl.textContent = 'Version: unavailable';
      return;
    }

    versionEl.textContent = 'Version: v' + installed;
    versionEl.style.color = '#666';

    try {
      const response = await api.relay(
        'GET',
        RELEASE_API_URL,
        {
          Accept: 'application/vnd.github+json',
          'User-Agent': 'PluginHub-CrossPoint'
        },
        ''
      );
      if (response.error || (response.status && (response.status < 200 || response.status >= 300))) {
        return;
      }

      const release = response.body ? JSON.parse(response.body) : {};
      const latest = String(release.tag_name || '').trim().replace(/^v/i, '');
      const comparison = compareVersions(latest, installed);
      if (comparison > 0) {
        versionEl.textContent =
          'Version: v' + installed + ' — Update available: v' + latest;
        versionEl.style.color = '#c0392b';
      }
    } catch (e) {}
  }

  async function fetchLargeText(url) {
    const cachePath = (PLUGIN_DIR || PLUGINS_DIR + '/pluginhub') + '/.catalog-cache.json';
    const response = await api.fetchToSd(url, cachePath, {});
    if (response.error || (response.status && (response.status < 200 || response.status >= 300))) {
      throw new Error('download failed (' + (response.status || response.error) + ')');
    }
    try {
      const downloaded = await fetch('/download?path=' + encodeURIComponent(cachePath));
      if (!downloaded.ok) throw new Error('could not read downloaded catalog');
      return await downloaded.text();
    } finally {
      try {
        await fetch('/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: 'path=' + encodeURIComponent(cachePath)
        });
      } catch (e) {}
    }
  }

  async function relayText(url) {
    let response;
    try {
      response = await api.relay('GET', url, {}, '');
    } catch (error) {
      const detail = String(error && error.message ? error.message : error);
      if (detail.includes('large bodies need /api/fetch') || detail.includes('/api/relay 502')) {
        return fetchLargeText(url);
      }
      throw error;
    }
    if (response.error || (response.status && (response.status < 200 || response.status >= 300))) {
      const detail = String(response.error || response.body || '');
      if (response.status === 502 || detail.includes('large bodies need /api/fetch')) {
        return fetchLargeText(url);
      }
      throw new Error('HTTP ' + (response.status || response.error));
    }
    return response.body;
  }

  async function loadBuiltInCatalogs() {
    const payload = JSON.parse(await relayText(LIST_INDEX_URL));
    const lists = Array.isArray(payload.lists) ? payload.lists : [];
    const normalized = lists
      .filter((entry) => entry && entry.title && entry.url)
      .map((entry) => ({
        title: String(entry.title),
        description: String(entry.title).startsWith('Community Plugins')
          ? 'Third-party plugins from CrossPoint community developers.'
          : 'Curated and recognized for the CrossPoint ecosystem.',
        url: String(entry.url)
      }));
    if (!normalized.length) throw new Error('catalog list index is empty');
    BUILT_IN_CATALOGS = normalized;
    if (!BUILT_IN_CATALOGS.some((catalog) => catalog.url === selectedCatalog)) {
      selectedCatalog = BUILT_IN_CATALOGS[0].url;
    }
  }

  async function mkdir(path) {
    try {
      await fetch('/mkdir', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'path=' + encodeURIComponent(path)
      });
    } catch (e) {}
  }

  function validatePlugin(plugin) {
    if (!plugin || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(String(plugin.name || ''))) {
      throw new Error('invalid plugin id');
    }
    if (!plugin.base || !Array.isArray(plugin.files) || plugin.files.length === 0) {
      throw new Error('catalog entry is missing base/files');
    }
  }

  function safeRelativePath(path) {
    const rel = String(path || '').replace(/^\/+/, '');
    if (
      !rel ||
      rel.includes('\\') ||
      rel.split('/').some((part) => part === '' || part === '.' || part === '..')
    ) {
      throw new Error('unsafe plugin file path: ' + path);
    }
    return rel;
  }

  async function installPlugin(plugin, onProgress, installedDir = null) {
    validatePlugin(plugin);
    const dir = installedDir || PLUGINS_DIR + '/' + plugin.name;
    const base = String(plugin.base).replace(/\/*$/, '/');
    // Validate every catalog path before touching the SD card. Runtime
    // credentials are private reader state, never part of a distributable
    // plugin package.
    const files = plugin.files.map(safeRelativePath);
    // SdFat resolves paths without regard to case and may ignore leading
    // spaces and trailing dots/spaces in *each* path component. Validate
    // against those resolved names, not the manifest's literal spelling.
    function fatKey(rel) {
      const parts = rel.split('/').map((part) =>
        part.replace(/^ +/, '').replace(/[. ]+$/, '').toLowerCase()
      );
      if (parts.some((part) => !part || part === '.' || part === '..')) {
        throw new Error('unsafe FAT plugin file path: ' + rel);
      }
      return parts.join('/');
    }
    const normalized = files.map(fatKey);
    // FAT short 8.3 names may refer to long filenames already on the card
    // (CONFIG~1.JSO, TOKEN~1.JSO, CONFI~10.JSO, etc.). Reject rather than
    // assuming that /api/fetch will create a new independent file.
    function protectedFatShortAlias(rel) {
      const parts = rel.split('/');
      const leaf = parts.pop();
      const match = /^([a-z]{1,6})~([0-9]+)\.jso$/.exec(leaf);
      if (!match || match[1].length + match[2].length + 1 > 8) return false;
      return 'token'.startsWith(match[1]) ||
        (parts.length === 0 && 'config'.startsWith(match[1]));
    }
    if (normalized.some(protectedFatShortAlias)) {
      throw new Error('plugin packages must not overwrite protected FAT short names');
    }
    if (normalized.some((rel) => rel.split('/').pop() === 'token.json')) {
      throw new Error('plugin packages must not overwrite token.json');
    }
    if (new Set(normalized).size !== files.length) {
      throw new Error('duplicate plugin path (FAT-normalized filesystem)');
    }
    // Plugin Hub reinstalls and updates in-place. Preserve locally modified
    // config.json even when it appears in manifest.files; first installs
    // (HTTP 404) still receive the packaged defaults. A failed lookup must
    // not be mistaken for a missing file, or user settings could be lost.
    const preserve = new Set();
    if (normalized.includes('config.json')) {
      const path = dir + '/config.json';
      let response;
      try {
        response = await fetch('/download?path=' + encodeURIComponent(path));
      } catch (error) {
        throw new Error('cannot check existing config.json: ' + error.message);
      }
      if (response.ok) preserve.add('config.json');
      else if (response.status !== 404) {
        throw new Error('cannot check existing config.json (HTTP ' + response.status + ')');
      }
    }

    await mkdir(dir);
    for (let i = 0; i < files.length; i++) {
      if (onProgress) onProgress(i, files.length);
      const rel = files[i];
      if (preserve.has(normalized[i])) continue;

      const segments = rel.split('/');
      segments.pop();
      let current = dir;
      for (const segment of segments) {
        current += '/' + segment;
        await mkdir(current);
      }

      const response = await api.fetchToSd(base + rel, dir + '/' + rel, {});
      if (response.error || (response.status && (response.status < 200 || response.status >= 300))) {
        throw new Error(
          'download failed for ' + rel + ' (' + (response.status || response.error) + ')'
        );
      }
    }

    if (onProgress) onProgress(files.length, files.length);
  }

  async function uninstallPlugin(plugin, installedDir = null) {
    validatePlugin(plugin);
    const dir = installedDir || PLUGINS_DIR + '/' + plugin.name;
    if (!PLUGIN_ROOTS.some(root => dir === root + '/' + plugin.name)) {
      throw new Error('unsafe plugin installation directory');
    }
    let examined = 0;
    async function deleteOne(path) {
      const response = await fetch('/delete', {
        method: 'POST',
        headers: {'Content-Type':'application/x-www-form-urlencoded'},
        body: 'path=' + encodeURIComponent(path)
      });
      if (!response.ok) throw new Error('cannot remove ' + path + ' (HTTP ' + response.status + ')');
    }
    async function removeTree(path, depth) {
      if (++examined > 1024 || depth > 12) throw new Error('plugin directory too large to remove safely');
      const response = await fetch('/api/files?path=' + encodeURIComponent(path));
      if (!response.ok) throw new Error('cannot inspect ' + path);
      const contents = await response.json();
      if (!Array.isArray(contents)) throw new Error('invalid plugin directory listing');
      for (const item of contents) {
        const name = String(item?.name || '');
        if (!name || name === '.' || name === '..' || name.includes('/') ||
            name.includes('\\') || name.includes('\0')) {
          throw new Error('unsafe file name returned by device');
        }
        const child = path + '/' + name;
        if (item.isDirectory) await removeTree(child, depth + 1);
        else await deleteOne(child);
      }
      await deleteOne(path);
    }
    // This removes files that aren't in the currently published catalog too,
    // and supports nested plugin assets. Configuration in the separate
    // /.crosspoint/plugin-data/<id> namespace is deliberately untouched.
    await removeTree(dir, 0);
  }

  function renderCatalogs() {
    catalogsEl.innerHTML = '';
    customCatalogsEl.innerHTML = '';

    BUILT_IN_CATALOGS.forEach((catalog) => {
      const row = document.createElement('div');
      row.className = 'setting-row';

      const meta = document.createElement('span');
      meta.className = 'setting-name';
      meta.innerHTML =
        '<strong>' + escapeHtml(catalog.title) + '</strong>' +
        '<br><span style="color:#666">' + escapeHtml(catalog.description) + '</span>';

      const browse = document.createElement('button');
      browse.type = 'button';
      browse.className = 'btn-small btn-add';
      browse.textContent = selectedCatalog === catalog.url ? 'Selected' : 'Browse';
      browse.disabled = selectedCatalog === catalog.url;
      browse.onclick = async () => {
        selectedCatalog = catalog.url;
        renderCatalogs();
        await refresh();
      };

      row.appendChild(meta);
      row.appendChild(browse);
      catalogsEl.appendChild(row);
    });

    extraCatalogs.forEach((url, index) => {
      const row = document.createElement('div');
      row.className = 'setting-row';

      const input = document.createElement('input');
      input.type = 'text';
      input.value = url;
      input.style.width = '100%';
      input.oninput = () => {
        const previous = extraCatalogs[index];
        const next = input.value.trim();
        extraCatalogs[index] = next;
        if (selectedCatalog === previous) selectedCatalog = next;
      };

      const controls = document.createElement('span');
      controls.className = 'setting-control';

      const browse = document.createElement('button');
      browse.type = 'button';
      browse.className = 'btn-small btn-add';
      browse.textContent = selectedCatalog === url ? 'Selected' : 'Browse';
      browse.disabled = selectedCatalog === url;
      browse.onclick = async () => {
        selectedCatalog = url;
        renderCatalogs();
        await refresh();
      };

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'btn-small ph-btn-remove';
      remove.textContent = 'Remove';
      remove.onclick = async () => {
        const removed = extraCatalogs[index];
        extraCatalogs.splice(index, 1);
        if (selectedCatalog === removed) selectedCatalog = BUILT_IN_CATALOGS[0]?.url || COMMUNITY_CATALOG;
        renderCatalogs();
        await saveConfig();
        if (selectedCatalog === BUILT_IN_CATALOGS[0]?.url) await refresh();
      };

      const inputControl = document.createElement('span');
      inputControl.className = 'setting-name';
      inputControl.appendChild(input);
      controls.appendChild(browse);
      controls.appendChild(document.createTextNode(' '));
      controls.appendChild(remove);

      row.appendChild(inputControl);
      row.appendChild(controls);
      customCatalogsEl.appendChild(row);
    });
  }

  document.getElementById('ph-add').onclick = async () => {
    const input = document.getElementById('ph-new');
    const url = input.value.trim();
    if (!url || isReservedCatalog(url) || extraCatalogs.includes(url)) return;
    extraCatalogs.push(url);
    extraCatalogs = normalizeExtraCatalogs(extraCatalogs);
    input.value = '';
    renderCatalogs();
    await saveConfig();
  };

  function pluginCard(plugin, installed) {
    const installedState = installed.get(plugin.name) || null;
    const isInstalled = installedState !== null;
    const localVersion = installedState ? installedState.version : null;
    const updateAvailable =
      isInstalled && hasUpdate(localVersion, plugin.version);

    const card = document.createElement('div');
    card.className = 'setting-row';
    card.id = 'ph-plugin-' + plugin.name;
    // Use an actual full-width two-column grid. justify-content alone
    // aligned the group internally, not the actions against the list edge.
    card.style.display = 'grid';
    card.style.gridTemplateColumns = 'minmax(0, 1fr) max-content';
    card.style.width = '100%';
    card.style.boxSizing = 'border-box';
    card.style.alignItems = 'center';
    card.style.gap = '12px';

    let state = '';
    if (updateAvailable) {
      state =
        ' <span style="color:#c0392b">Update available (v' +
        escapeHtml(localVersion || '?') +
        ' → v' +
        escapeHtml(plugin.version) +
        ')</span>';
    } else if (isInstalled) {
      state =
        ' <span style="color:#27ae60">' +
        escapeHtml(installedLabel(localVersion, plugin.version)) +
        '</span>';
    } else if (plugin.version) {
      state =
        ' <span style="color:#888">v' +
        escapeHtml(plugin.version) +
        '</span>';
    }

    const meta = document.createElement('span');
    meta.className = 'setting-name';
    meta.style.minWidth = '0';
    meta.style.overflowWrap = 'anywhere';
    meta.innerHTML =
      '<strong>' +
      escapeHtml(plugin.title || plugin.name) +
      '</strong>' +
      (plugin.author
        ? ' <span style="color:#888">by ' +
          escapeHtml(plugin.author) +
          '</span>'
        : '') +
      state +
      '<br><span style="color:#666">' +
      escapeHtml(plugin.description || '') +
      '</span>';

    const controls = document.createElement('span');
    controls.className = 'setting-control';
    controls.style.display = 'flex';
    controls.style.justifyContent = 'flex-end';
    controls.style.marginLeft = '0';
    controls.style.justifySelf = 'end';
    controls.style.flexWrap = 'nowrap';
    controls.style.gap = '8px';

    const install = document.createElement('button');
    install.type = 'button';
    install.className = 'btn-small btn-add' + (isInstalled && !updateAvailable ? ' ph-btn-reinstall' : '');
    const originalLabel = updateAvailable
      ? 'Update'
      : (isInstalled ? 'Reinstall' : 'Install');
    install.textContent = originalLabel;
    install.onclick = async () => {
      install.disabled = true;
      const verb = updateAvailable ? 'Updating' : 'Installing';
      status(verb + ' ' + (plugin.title || plugin.name) + '…');

      try {
        await installPlugin(plugin, (done, total) => {
          install.textContent = verb + '… ' + done + '/' + total;
        }, installedState ? installedState.dir : null);
        status(
          (updateAvailable ? 'Updated ' : 'Installed ') +
          (plugin.title || plugin.name) +
          '. Reconnect or reopen Settings to use it.'
        );
        await refresh();
      } catch (e) {
        status('Error: ' + e.message);
        install.textContent = originalLabel;
        install.disabled = false;
      }
    };
    controls.appendChild(install);

    if (isInstalled) {
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'btn-small ph-btn-remove';
      remove.textContent = 'Remove';
      remove.onclick = async () => {
        if (typeof confirm === 'function' && !confirm('Remove ' + (plugin.title || plugin.name) + ' from the SD card?')) return;
        remove.disabled = true;
        status('Removing ' + (plugin.title || plugin.name) + '…');

        try {
          await uninstallPlugin(plugin, installedState ? installedState.dir : null);
          status('Removed ' + (plugin.title || plugin.name) + '.');
          await refresh();
        } catch (e) {
          status('Error: ' + e.message);
          remove.disabled = false;
        }
      };
      controls.appendChild(document.createTextNode(' '));
      controls.appendChild(remove);
    }

    card.appendChild(meta);
    card.appendChild(controls);
    return card;
  }

  // Wallpaper packs are native data collections, not browser plugins.
  // Only show this section when the connected firmware exposes the API.
  const WALLPAPER_PACKS_TIMEOUT_MS = 3000;
  let wallpaperListGeneration = 0;
  async function renderInstalledWallpaperPacks() {
    const generation = ++wallpaperListGeneration;
    wallpapersEl.innerHTML = '';
    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    let timeoutId;
    let packs;
    try {
      const request = (async () => {
        const response = await fetch('/api/wallpaper-packs',
          controller ? {signal: controller.signal} : undefined);
        if (response.status === 404) return null;
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      })();
      packs = await Promise.race([
        request,
        new Promise(resolve => {
          timeoutId = setTimeout(() => {
            if (controller) controller.abort();
            resolve(null);
          }, WALLPAPER_PACKS_TIMEOUT_MS);
        })
      ]);
      if (generation !== wallpaperListGeneration || !Array.isArray(packs)) return;
    } catch (e) {
      // Older firmware or a timed-out API must not block ordinary plugin management.
      return;
    } finally {
      clearTimeout(timeoutId);
    }

    const installedPacks = packs.filter(pack =>
      pack && typeof pack.id === 'string' && pack.id &&
      typeof pack.title === 'string');
    if (!installedPacks.length) return;

    const heading = document.createElement('h3');
    heading.textContent = 'Installed Wallpaper Packs';
    heading.style.margin = '0.8em 0 0.2em';

    wallpapersEl.appendChild(heading);

    for (const pack of installedPacks) {
      const row = document.createElement('div');
      row.className = 'setting-row';

      const meta = document.createElement('span');
      meta.className = 'setting-name';
      const title = document.createElement('strong');
      title.textContent = pack.title;
      meta.appendChild(title);
      if (typeof pack.author === 'string' && pack.author) {
        const author = document.createElement('span');
        author.style.color = '#888';
        author.textContent = ' by ' + pack.author;
        meta.appendChild(author);
      }
      const state = document.createElement('span');
      state.style.color = '#27ae60';
      const version = typeof pack.version === 'string' && pack.version ? ' v' + pack.version : '';
      state.textContent = ' Installed' + version + (pack.selected ? ' · Selected' : '');
      meta.appendChild(state);
      if (typeof pack.description === 'string' && pack.description) {
        const description = document.createElement('span');
        description.style.color = '#666';
        description.textContent = pack.description;
        meta.append(document.createElement('br'), description);
      }

      const controls = document.createElement('span');
      controls.className = 'setting-control';
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'btn-small ph-btn-remove';
      remove.textContent = 'Remove';
      remove.onclick = async () => {
        if (typeof confirm === 'function' &&
            !confirm('Remove wallpaper pack ' + pack.title + ' from the SD card?')) return;
        remove.disabled = true;
        try {
          const response = await fetch('/api/wallpaper-packs/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: pack.id})
          });
          if (!response.ok) throw new Error('HTTP ' + response.status);
          status('Removed wallpaper pack ' + pack.title + '.');
          await renderInstalledWallpaperPacks();
        } catch (e) {
          status('Error removing wallpaper pack: ' + e.message);
          remove.disabled = false;
        }
      };
      controls.appendChild(remove);
      row.append(meta, controls);
      wallpapersEl.appendChild(row);
    }
  }

  async function refresh() {
    await saveConfig();
    renderCatalogs();
    listEl.innerHTML = '';
    // Wallpaper metadata is optional; never delay catalog loading for it.
    void renderInstalledWallpaperPacks();

    const url = selectedCatalog;
    status('Loading ' + selectedCatalogLabel() + '…');

    let catalog;
    try {
      catalog = JSON.parse(await relayText(url));
    } catch (e) {
      listEl.appendChild(wallpapersEl);
      status('Error loading ' + selectedCatalogLabel() + ': ' + e.message);
      return;
    }

    const locations = await installedPlugins();
    const installed = new Map();
    for (const [name, dir] of locations) {
      installed.set(name, { dir, version: await installedVersion(dir) });
    }

    const hardware = await hardwareStatus();
    const catalogName = catalog.name || selectedCatalogLabel();
    const plugins = (Array.isArray(catalog.plugins) ? catalog.plugins : [])
      .filter(plugin => installed.has(plugin.name) || recommendedForHardware(plugin, hardware));
    let updates = 0;

    if (plugins.length) {
      const header = document.createElement('h3');
      header.textContent = catalogName;
      header.style.margin = '0.8em 0 0.2em';
      listEl.appendChild(header);
    }

    let requestedCard = null;
    for (const plugin of plugins) {
      if (
        installed.has(plugin.name) &&
        hasUpdate(installed.get(plugin.name).version, plugin.version)
      ) {
        updates += 1;
      }
      const card = pluginCard(plugin, installed);
      listEl.appendChild(card);
      if (pendingReinstall && plugin.name === requestedPlugin) requestedCard = card;
    }

    listEl.appendChild(wallpapersEl);

    if (pendingReinstall) {
      if (!requestedCard || !installed.has(requestedPlugin)) {
        status('Reinstall unavailable: ' + requestedPlugin +
          ' is not installed or is absent from this catalog. Choose the correct Plugin Hub catalog.');
        clearManagementIntent();
        return;
      }
      clearManagementIntent();
      const action = requestedCard.children[1].children[0];
      if (requestedCard.scrollIntoView) requestedCard.scrollIntoView({block:'center'});
      if (typeof confirm === 'function' && !confirm('Reinstall ' + requestedPlugin +
          ' from the selected Plugin Hub catalog?')) {
        status('Reinstallation cancelled.');
        return;
      }
      await action.onclick();
      return;
    }

    let message =
      plugins.length +
      ' plugin' +
      (plugins.length === 1 ? '' : 's') +
      ' available';
    if (updates) {
      message +=
        ', ' +
        updates +
        ' update' +
        (updates === 1 ? '' : 's');
    }
    status(message + '.');
  }

  document.getElementById('ph-refresh').onclick = refresh;

  try {
    await loadBuiltInCatalogs();
  } catch (e) {
    BUILT_IN_CATALOGS = defaultBuiltInCatalogs();
    selectedCatalog = BUILT_IN_CATALOGS[0].url;
    status('Catalog index unavailable; using built-in catalog URLs.');
  }

  const config = await loadConfig();
  if (Array.isArray(config.extraCatalogs)) {
    extraCatalogs = normalizeExtraCatalogs(config.extraCatalogs);
  } else if (Array.isArray(config.catalogs)) {
    // Accept an early/legacy multi-catalog shape without surfacing any built-in
    // or compatibility feed as a removable custom catalog.
    extraCatalogs = normalizeExtraCatalogs(config.catalogs);
  } else if (config.catalog) {
    extraCatalogs = normalizeExtraCatalogs([config.catalog]);
  }

  renderCatalogs();
  await checkHubVersion();
  await refresh();
});
