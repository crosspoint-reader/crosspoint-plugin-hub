import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const root = new URL('../', import.meta.url);
const UNION_CATALOG =
  'https://raw.githubusercontent.com/crosspoint-reader/crosspoint-plugin-hub/main/catalog.json';
const COMMUNITY_CATALOG =
  'https://raw.githubusercontent.com/crosspoint-reader/crosspoint-plugin-hub/main/community-catalog.json';
const LIST_INDEX =
  'https://raw.githubusercontent.com/crosspoint-reader/crosspoint-plugin-hub/main/catalog-lists.json';
const PRIVATE_CATALOG = 'https://example.test/private/catalog.json';

class Element {
  constructor(tag = 'div', id = '') {
    this.tagName = tag;
    this.id = id;
    this.children = [];
    this.className = '';
    this._innerHTML = '';
    this.textContent = '';
    this.value = '';
    this.style = {};
    this.disabled = false;
    this.onclick = null;
    this.oninput = null;
    this.type = '';
  }

  set innerHTML(value) {
    this._innerHTML = value;
    if (value === '') this.children = [];
  }

  get innerHTML() {
    return this._innerHTML;
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  querySelectorAll(tag) {
    const matches = [];
    for (const child of this.children) {
      if (child.tagName === tag) matches.push(child);
      matches.push(...child.querySelectorAll(tag));
    }
    return matches;
  }
}

function fakeDocument() {
  const ids = [
    'ph-version',
    'ph-catalogs',
    'ph-custom-catalogs',
    'ph-new',
    'ph-add',
    'ph-refresh',
    'ph-status',
    'ph-list',
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, new Element('div', id)]));
  return {
    elements,
    getElementById(id) {
      assert.ok(elements[id], 'unexpected element lookup: ' + id);
      return elements[id];
    },
    createElement(tag) {
      return new Element(tag);
    },
    createTextNode(text) {
      const node = new Element('#text');
      node.textContent = text;
      return node;
    },
  };
}

function response({ status = 200, json, text = '' } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return json;
    },
    async text() {
      return text;
    },
  };
}

async function loadPlugin(globals = {}) {
  let render;
  const context = vm.createContext({
    CrossPoint: {
      registerPlugin(fn) {
        render = fn;
      },
    },
    URL,
    TextEncoder,
    Set,
    Map,
    Array,
    String,
    Number,
    Object,
    Promise,
    JSON,
    encodeURIComponent,
    btoa: (value) => Buffer.from(value, 'binary').toString('base64'),
    ...globals,
  });

  const source = await readFile(new URL('../plugin.js', import.meta.url), 'utf8');
  vm.runInContext(source, context, { filename: 'plugin.js' });
  assert.equal(typeof render, 'function');
  return render;
}

test('browser hub loads custom catalogs and only offers directional updates', async () => {
  const document = fakeDocument();
  const writes = [];
  const relayCalls = [];
  const fetchToSdCalls = [];
  let deletedCache = false;

  const communityCatalog = {
    name: 'Community Plugins',
    plugins: [
      {
        name: 'sample-newer',
        compatibility: { advisory: 'psram_mb=2' },
        title: 'Sample Newer',
        version: '1.0.0',
        base: 'https://example.test/newer/',
        files: ['manifest.json', 'plugin.js'],
      },
      {
        name: 'sampleplugin',
        title: 'Sample Plugin',
        version: '0.1.2.2',
        base: 'https://example.test/send/',
        files: ['manifest.json', 'device.json', 'plugin.js'],
      },
      {
        name: 'second-update',
        title: 'Aardvark Update',
        version: '1.1.0',
        base: 'https://example.test/second-update/',
        files: ['manifest.json', 'plugin.js'],
      },
      {
        name: 'x4-only',
        title: 'X4 Only',
        version: '1.0.0',
        base: 'https://example.test/x4/',
        files: ['manifest.json'],
        compatibility: { advisory: 'models=x4|x4pro' },
      },
      {
        name: 'z-alpha',
        title: 'alpha',
        version: '1.0.0',
        base: 'https://example.test/z-alpha/',
        files: ['manifest.json', 'plugin.js'],
      },
      {
        name: 'a-alpha',
        title: 'ALPHA',
        version: '1.0.0',
        base: 'https://example.test/a-alpha/',
        files: ['manifest.json', 'plugin.js'],
      },
      {
        name: 'community-only',
        title: 'Community Only',
        version: '1.0.0',
        base: 'https://example.test/community/',
        files: ['manifest.json', 'plugin.js'],
      },
    ],
  };
  const privateCatalog = {
    name: 'Private Test Plugins',
    plugins: [
      {
        name: 'private-test',
        title: 'Private Test',
        version: '0.0.1',
        base: 'https://example.test/private/',
        files: ['manifest.json', 'plugin.js'],
      },
    ],
  };

  async function fetch(url) {
    if (url === '/api/status') return response({ json: { deviceModel: 'x3', psramBytes: 0 } });
    if (url.startsWith('/download?path=')) {
      const path = new URL(url, 'http://device').searchParams.get('path');
      // Like the firmware, refuse file names that start with a dot.
      if (path.split('/').pop().startsWith('.')) return response({ status: 403 });
      if (path === '/.crosspoint/plugin-hub.json') {
        return response({
          text: JSON.stringify({ extraCatalogs: [PRIVATE_CATALOG] }),
        });
      }
      if (path === '/.crosspoint/plugins/pluginhub/manifest.json') {
        return response({ text: JSON.stringify({ version: '0.1.1' }) });
      }
      if (path === '/.crosspoint/plugins/sample-newer/manifest.json') {
        return response({ text: JSON.stringify({ version: '1.1.0' }) });
      }
      if (path === '/.crosspoint/plugins/sampleplugin/manifest.json') {
        return response({ text: JSON.stringify({ version: '0.1.2.1' }) });
      }
      if (path === '/.crosspoint/plugins/second-update/manifest.json') {
        return response({ text: JSON.stringify({ version: '1.0.0' }) });
      }
      if (path === '/.crosspoint/plugins/pluginhub/catalog-cache.json') {
        return response({ text: JSON.stringify(communityCatalog) });
      }
      return response({ status: 404 });
    }

    if (url.startsWith('/api/files?path=')) {
      const path = new URL(url, 'http://device').searchParams.get('path');
      if (path === '/.crosspoint/plugins') {
        return response({
          json: [
            { name: 'pluginhub', isDirectory: true },
            { name: 'sample-newer', isDirectory: true },
            { name: 'sampleplugin', isDirectory: true },
            { name: 'second-update', isDirectory: true },
          ],
        });
      }
      return response({ json: [] });
    }

    if (url === '/delete') {
      deletedCache = true;
      return response({});
    }

    throw new Error('unexpected fetch: ' + url);
  }

  const api = {
    async writeFile(path, dataB64) {
      writes.push({
        path,
        data: Buffer.from(dataB64, 'base64').toString('utf8'),
      });
      return { ok: true };
    },
    async relay(method, url) {
      assert.equal(method, 'GET');
      relayCalls.push(url);
      if (url === LIST_INDEX) {
        return {
          status: 200,
          body: JSON.stringify({
            lists: [{ title: 'Community Plugins', url: COMMUNITY_CATALOG }],
          }),
        };
      }
      if (url === COMMUNITY_CATALOG) {
        return { status: 502, error: 'relay failed; large bodies need /api/fetch' };
      }
      if (url === PRIVATE_CATALOG) {
        return { status: 200, body: JSON.stringify(privateCatalog) };
      }
      return { status: 404, body: '' };
    },
    async fetchToSd(url, dest) {
      fetchToSdCalls.push({ url, dest });
      return { status: 200 };
    },
  };

  const render = await loadPlugin({ document, fetch });
  await render({ innerHTML: '' }, api);

  // No GitHub API call: the update check reads the catalog.
  assert.deepEqual(relayCalls, [LIST_INDEX, COMMUNITY_CATALOG]);
  assert.equal(document.elements['ph-version'].textContent, 'Version: v0.1.1');

  const catalogRows = document.elements['ph-catalogs'].children;
  assert.equal(catalogRows.length, 1);
  assert.match(catalogRows[0].children[0].innerHTML, /Community Plugins/);
  assert.equal(catalogRows[0].children[1].textContent, 'Selected');
  assert.equal(catalogRows[0].children[1].disabled, true);

  const customRows = document.elements['ph-custom-catalogs'].children;
  assert.equal(customRows.length, 1);
  assert.equal(customRows[0].children[0].children[0].value, PRIVATE_CATALOG);
  assert.equal(customRows[0].children[1].children[0].textContent, 'Browse');

  assert.equal(writes.length, 1);
  assert.equal(writes[0].path, '/.crosspoint/plugin-hub.json');
  assert.deepEqual(JSON.parse(writes[0].data), {
    extraCatalogs: [PRIVATE_CATALOG],
  });

  let cards = document.elements['ph-list'].children.filter(
    (child) => child.className === 'setting-row'
  );
  assert.equal(cards.length, 6);
  assert.ok(cards.some((card) => card.id === 'ph-plugin-sample-newer'));
  assert.ok(!cards.some((card) => card.id === 'ph-plugin-x4-only'));
  // Updates sort by title, then other entries by title and name (case-insensitive).
  assert.deepEqual(cards.map((card) => card.id), [
    'ph-plugin-second-update',
    'ph-plugin-sampleplugin',
    'ph-plugin-a-alpha',
    'ph-plugin-z-alpha',
    'ph-plugin-community-only',
    'ph-plugin-sample-newer',
  ]);
  assert.equal(cards[0].children[1].children[0].textContent, 'Update');
  assert.equal(cards[1].children[1].children[0].textContent, 'Update');
  for (const card of cards.slice(2, 5)) {
    assert.equal(card.children[1].children[0].textContent, 'Install');
  }
  assert.equal(cards[5].children[1].children[0].textContent, 'Reinstall');
  assert.match(cards[5].children[1].children[0].className, /ph-btn-reinstall/);
  assert.match(cards[5].children[1].children.find(child => child.textContent === 'Remove').className, /ph-btn-remove/);
  for (const card of cards) {
    assert.equal(card.style.display, 'grid');
    assert.equal(card.style.gridTemplateColumns, 'minmax(0, 1fr) max-content');
    assert.equal(card.style.width, '100%');
    assert.equal(card.children[0].style.minWidth, '0');
    assert.equal(card.children[1].style.justifyContent, 'flex-end');
    assert.equal(card.children[1].style.justifySelf, 'end');
    assert.equal(card.children[1].style.marginLeft, '0');
  }
  assert.match(document.elements['ph-status'].textContent, /6 plugins available, 2 updates/);

  assert.deepEqual(fetchToSdCalls, [
    { url: COMMUNITY_CATALOG, dest: '/.crosspoint/plugins/pluginhub/catalog-cache.json' },
  ]);
  assert.equal(deletedCache, true);

  const privateBrowse = document.elements['ph-custom-catalogs'].children[0].children[1].children[0];
  await privateBrowse.onclick();
  assert.equal(relayCalls.at(-1), PRIVATE_CATALOG);
  cards = document.elements['ph-list'].children.filter(
    (child) => child.className === 'setting-row'
  );
  assert.equal(cards.length, 1);
  assert.equal(cards[0].children[1].children[0].textContent, 'Install');

  const selectedPrivateInput = document.elements['ph-custom-catalogs'].children[0].children[0].children[0];
  selectedPrivateInput.value = UNION_CATALOG;
  selectedPrivateInput.oninput();
  await document.elements['ph-refresh'].onclick();
  assert.deepEqual(JSON.parse(writes.at(-1).data), { extraCatalogs: [] });
  assert.equal(document.elements['ph-custom-catalogs'].children.length, 0);
  assert.equal(relayCalls.at(-1), COMMUNITY_CATALOG);
});

test('browser hub adopts api.dir while migrating legacy config', async () => {
  const document = fakeDocument();
  const writes = [];
  const downloadPaths = [];
  const relayCalls = [];

  async function fetch(url) {
    if (url === '/api/status') return response({ json: { deviceModel: 'x3', psramBytes: 0 } });
    if (url.startsWith('/download?path=')) {
      const path = new URL(url, 'http://device').searchParams.get('path');
      // Like the firmware, refuse file names that start with a dot.
      if (path.split('/').pop().startsWith('.')) return response({ status: 403 });
      downloadPaths.push(path);
      if (path === '/plugins/pluginhub/config.json') {
        return response({ status: 404 });
      }
      if (path === '/.crosspoint/plugin-hub.json') {
        return response({
          text: JSON.stringify({
            catalogs: [
              UNION_CATALOG,
              COMMUNITY_CATALOG,
              PRIVATE_CATALOG,
            ],
          }),
        });
      }
      if (path === '/plugins/pluginhub/manifest.json') {
        return response({ text: JSON.stringify({ version: '0.1.4' }) });
      }
      return response({ status: 404 });
    }

    if (url.startsWith('/api/files?path=')) {
      return response({ json: [] });
    }

    throw new Error('unexpected fetch: ' + url);
  }

  const api = {
    dir: '/plugins/pluginhub/',
    async writeFile(path, dataB64) {
      writes.push({
        path,
        data: Buffer.from(dataB64, 'base64').toString('utf8'),
      });
      return { ok: true };
    },
    async relay(method, url) {
      assert.equal(method, 'GET');
      relayCalls.push(url);
      if (url === LIST_INDEX) {
        return {
          status: 200,
          body: JSON.stringify({
            lists: [{ title: 'Community Plugins', url: COMMUNITY_CATALOG }],
          }),
        };
      }
      if (url === COMMUNITY_CATALOG) {
        return { status: 200, body: JSON.stringify({ name: 'Community Plugins', plugins: [] }) };
      }
      if (url === PRIVATE_CATALOG) {
        return { status: 200, body: JSON.stringify({ name: 'Private', plugins: [] }) };
      }
      return { status: 404, body: '' };
    },
    async fetchToSd() {
      return { status: 200 };
    },
  };

  const render = await loadPlugin({ document, fetch });
  await render({ innerHTML: '' }, api);

  assert.deepEqual(downloadPaths.slice(0, 3), [
    '/plugins/pluginhub/config.json',
    '/.crosspoint/plugin-hub.json',
    '/plugins/pluginhub/manifest.json',
  ]);
  assert.equal(document.elements['ph-version'].textContent, 'Version: v0.1.4');
  assert.equal(writes.length, 1);
  assert.equal(writes[0].path, '/plugins/pluginhub/config.json');
  assert.deepEqual(JSON.parse(writes[0].data), {
    extraCatalogs: [PRIVATE_CATALOG],
  });
  assert.deepEqual(relayCalls, [LIST_INDEX, COMMUNITY_CATALOG]);
  const customRows = document.elements['ph-custom-catalogs'].children;
  assert.equal(customRows.length, 1);
  assert.equal(customRows[0].children[0].children[0].value, PRIVATE_CATALOG);
});

test('browser hub falls back to built-in catalog URLs when list index is unavailable', async () => {
  const document = fakeDocument();
  const relayCalls = [];

  async function fetch(url) {
    if (url === '/api/status') return response({ json: { deviceModel: 'x3', psramBytes: 0 } });
    if (url.startsWith('/download?path=')) {
      const path = new URL(url, 'http://device').searchParams.get('path');
      // Like the firmware, refuse file names that start with a dot.
      if (path.split('/').pop().startsWith('.')) return response({ status: 403 });
      if (path === '/.crosspoint/plugins/pluginhub/manifest.json') {
        return response({ text: JSON.stringify({ version: '0.1.6' }) });
      }
      return response({ status: 404 });
    }
    if (url.startsWith('/api/files?path=')) {
      return response({ json: [] });
    }
    throw new Error('unexpected fetch: ' + url);
  }

  const api = {
    dir: '/.crosspoint/plugins/pluginhub',
    async writeFile() {
      return { ok: true };
    },
    async relay(method, url) {
      assert.equal(method, 'GET');
      relayCalls.push(url);
      if (url === LIST_INDEX) {
        return { status: 503, error: 'index unavailable' };
      }
      if (url === COMMUNITY_CATALOG) {
        return { status: 200, body: JSON.stringify({ name: 'Community Plugins', plugins: [] }) };
      }
      return { status: 404, body: '' };
    },
    async fetchToSd() {
      return { status: 200 };
    },
  };

  const render = await loadPlugin({ document, fetch });
  await render({ innerHTML: '' }, api);

  assert.equal(relayCalls[0], LIST_INDEX);
  assert.ok(relayCalls.includes(COMMUNITY_CATALOG));
  const catalogRows = document.elements['ph-catalogs'].children;
  assert.equal(catalogRows.length, 1);
  assert.match(catalogRows[0].children[0].innerHTML, /Community Plugins/);
  assert.equal(catalogRows[0].children[1].textContent, 'Selected');
  assert.match(document.elements['ph-status'].textContent, /0 plugins available/);
});

test('browser hub preserves alternate plugin root for updates and removal', async () => {
  const document = fakeDocument();
  const fetchToSdCalls = [];
  const deletedPaths = [];
  const confirms = [];
  const changedLocations = [];
  const communityCatalog = {
    name: 'Community Plugins',
    plugins: [
      {
        name: 'altplugin',
        title: 'Alternate Root Plugin',
        version: '1.1.0',
        base: 'https://example.test/altplugin/',
        files: ['manifest.json', 'plugin.js'],
      },
    ],
  };

  async function fetch(url, options = {}) {
    if (url.startsWith('/download?path=')) {
      const path = new URL(url, 'http://device').searchParams.get('path');
      // Like the firmware, refuse file names that start with a dot.
      if (path.split('/').pop().startsWith('.')) return response({ status: 403 });
      if (path === '/.crosspoint/plugins/pluginhub/manifest.json') {
        return response({ text: JSON.stringify({ version: '0.1.6' }) });
      }
      if (path === '/plugins/altplugin/manifest.json') {
        return response({ text: JSON.stringify({ version: '1.0.0' }) });
      }
      return response({ status: 404 });
    }
    if (url.startsWith('/api/files?path=')) {
      const path = new URL(url, 'http://device').searchParams.get('path');
      if (path === '/plugins') {
        return response({ json: [{ name: 'altplugin', isDirectory: true }] });
      }
      if (path === '/plugins/altplugin') {
        return response({ json: [
          {name:'manifest.json', isDirectory:false},
          {name:'plugin.js', isDirectory:false},
        ]});
      }
      return response({ json: [] });
    }
    if (url === '/mkdir') {
      return response({});
    }
    if (url === '/delete') {
      deletedPaths.push(new URLSearchParams(options.body || '').get('path'));
      return response({});
    }
    throw new Error('unexpected fetch: ' + url);
  }

  const api = {
    dir: '/.crosspoint/plugins/pluginhub',
    async writeFile() {
      return { ok: true };
    },
    async relay(method, url) {
      assert.equal(method, 'GET');
      if (url === LIST_INDEX) {
        return {
          status: 200,
          body: JSON.stringify({
            lists: [{ title: 'Community Plugins', url: COMMUNITY_CATALOG }],
          }),
        };
      }
      if (url === COMMUNITY_CATALOG) {
        return { status: 200, body: JSON.stringify(communityCatalog) };
      }
      return { status: 404, body: '' };
    },
    async fetchToSd(url, dest) {
      fetchToSdCalls.push({ url, dest });
      return { status: 200 };
    },
  };

  const render = await loadPlugin({
    document, fetch, URLSearchParams,
    location: {search: '?plugin=pluginhub&manage=altplugin&action=reinstall'},
    history: {replaceState: (...args) => changedLocations.push(args.at(-1))},
    confirm: (message) => {confirms.push(message); return true;}
  });
  await render({ innerHTML: '' }, api);

  let cards = document.elements['ph-list'].children.filter(
    (child) => child.className === 'setting-row'
  );
  assert.equal(cards.length, 1);
  assert.equal(cards[0].children[1].children[0].textContent, 'Update');
  assert.match(confirms[0], /Reinstall altplugin/);
  assert.deepEqual(changedLocations, ['/plugins?plugin=pluginhub']);
  assert.deepEqual(fetchToSdCalls, [
    { url: 'https://example.test/altplugin/manifest.json', dest: '/plugins/altplugin/manifest.json' },
    { url: 'https://example.test/altplugin/plugin.js', dest: '/plugins/altplugin/plugin.js' },
  ]);

  cards = document.elements['ph-list'].children.filter(
    (child) => child.className === 'setting-row'
  );
  const remove = cards[0].children[1].children.find((child) => child.textContent === 'Remove');
  assert.ok(remove);
  await remove.onclick();
  assert.match(confirms.at(-1), /Remove Alternate Root Plugin/);
  assert.deepEqual(deletedPaths, [
    '/plugins/altplugin/manifest.json',
    '/plugins/altplugin/plugin.js',
    '/plugins/altplugin',
  ]);
});

function fakeStorage(entries = {}) {
  const data = new Map(Object.entries(entries));
  return {
    data,
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
  };
}

// A device with Plugin Hub 0.1.1 and one other plugin installed, and the given
// community catalog and config text.
function hubDevice({ catalog, configText = null }) {
  const calls = { relay: [], fetchToSd: [], writes: [] };
  async function fetch(url) {
    if (url === '/api/status') return response({ json: { deviceModel: 'x4', psramBytes: 0 } });
    if (url.startsWith('/download?path=')) {
      const path = new URL(url, 'http://device').searchParams.get('path');
      if (path === '/.crosspoint/plugins/pluginhub/config.json') {
        return configText === null ? response({ status: 404 }) : response({ text: configText });
      }
      if (path === '/.crosspoint/plugins/pluginhub/manifest.json') {
        return response({ text: JSON.stringify({ version: '0.1.1' }) });
      }
      if (path === '/.crosspoint/plugins/pluginhub/catalog-cache.json') {
        return response({ text: JSON.stringify(catalog) });
      }
      return response({ status: 404 });
    }
    if (url.startsWith('/api/files?path=')) {
      const path = new URL(url, 'http://device').searchParams.get('path');
      return response({ json: path === '/.crosspoint/plugins' ? [{ name: 'pluginhub', isDirectory: true }] : [] });
    }
    if (url === '/delete') return response({});
    throw new Error('unexpected fetch: ' + url);
  }
  const api = {
    dir: '/.crosspoint/plugins/pluginhub',
    async writeFile(path, dataB64) {
      calls.writes.push({ path, data: Buffer.from(dataB64, 'base64').toString('utf8') });
      return { ok: true };
    },
    async relay(method, url) {
      calls.relay.push(url);
      if (url === LIST_INDEX) {
        return { status: 200, body: JSON.stringify({ lists: [{ title: 'Community Plugins', url: COMMUNITY_CATALOG }] }) };
      }
      if (url === COMMUNITY_CATALOG) return { status: 200, body: JSON.stringify(catalog) };
      return { status: 404, body: '' };
    },
    async fetchToSd(url, dest) {
      calls.fetchToSd.push({ url, dest });
      return { status: 200 };
    },
  };
  return { fetch, api, calls };
}

const SMALL_CATALOG = {
  name: 'Community Plugins',
  plugins: [{ name: 'pluginhub', title: 'Plugin Hub', version: '0.1.1', base: 'https://example.test/hub/', files: ['plugin.js'] }],
};

test('browser hub reuses cached catalogs until Refresh', async () => {
  const localStorage = fakeStorage();
  const first = hubDevice({ catalog: SMALL_CATALOG });
  await (await loadPlugin({ document: fakeDocument(), fetch: first.fetch, localStorage }))({ innerHTML: '' }, first.api);
  assert.deepEqual(first.calls.relay, [LIST_INDEX, COMMUNITY_CATALOG]);

  // A page reload within the cache time makes no relay at all.
  const document = fakeDocument();
  const second = hubDevice({ catalog: SMALL_CATALOG });
  await (await loadPlugin({ document, fetch: second.fetch, localStorage }))({ innerHTML: '' }, second.api);
  assert.deepEqual(second.calls.relay, []);
  assert.match(document.elements['ph-status'].textContent, /1 plugin available/);

  // Refresh fetches the selected catalog again, but not the list index.
  await document.elements['ph-refresh'].onclick();
  assert.deepEqual(second.calls.relay, [COMMUNITY_CATALOG]);

  // An old copy is fetched again.
  for (const [key, value] of localStorage.data) {
    localStorage.data.set(key, JSON.stringify({ ...JSON.parse(value), time: Date.now() - 16 * 60 * 1000 }));
  }
  const third = hubDevice({ catalog: SMALL_CATALOG });
  await (await loadPlugin({ document: fakeDocument(), fetch: third.fetch, localStorage }))({ innerHTML: '' }, third.api);
  assert.deepEqual(third.calls.relay, [LIST_INDEX, COMMUNITY_CATALOG]);
});

test('browser hub fetches a catalog last seen large through /api/fetch', async () => {
  const stale = Date.now() - 16 * 60 * 1000;
  const localStorage = fakeStorage({
    ['pluginhub.remote:' + COMMUNITY_CATALOG]: JSON.stringify({ time: stale, bytes: 25000, body: JSON.stringify(SMALL_CATALOG) }),
  });
  const device = hubDevice({ catalog: SMALL_CATALOG });
  await (await loadPlugin({ document: fakeDocument(), fetch: device.fetch, localStorage }))({ innerHTML: '' }, device.api);
  assert.deepEqual(device.calls.relay, [LIST_INDEX]);
  assert.deepEqual(device.calls.fetchToSd, [
    { url: COMMUNITY_CATALOG, dest: '/.crosspoint/plugins/pluginhub/catalog-cache.json' },
  ]);
  // The new copy is small, so the next fetch uses the relay again.
  const entry = JSON.parse(localStorage.data.get('pluginhub.remote:' + COMMUNITY_CATALOG));
  assert.equal(entry.bytes, JSON.stringify(SMALL_CATALOG).length);
});

test('browser hub does not cache a catalog that is not JSON', async () => {
  const localStorage = fakeStorage();
  const device = hubDevice({ catalog: SMALL_CATALOG });
  const relay = device.api.relay;
  device.api.relay = async (method, url) =>
    url === COMMUNITY_CATALOG ? { status: 200, body: '<html>busy</html>' } : relay(method, url);
  const document = fakeDocument();
  await (await loadPlugin({ document, fetch: device.fetch, localStorage }))({ innerHTML: '' }, device.api);
  assert.match(document.elements['ph-status'].textContent, /^Error loading/);
  assert.ok(!localStorage.data.has('pluginhub.remote:' + COMMUNITY_CATALOG));
  assert.ok(localStorage.data.has('pluginhub.remote:' + LIST_INDEX));
});

test('browser hub reads its own update from the catalog', async () => {
  const catalog = {
    name: 'Community Plugins',
    plugins: [{ name: 'pluginhub', title: 'Plugin Hub', version: '0.2.0', base: 'https://example.test/hub/', files: ['plugin.js'] }],
  };
  const document = fakeDocument();
  const device = hubDevice({ catalog });
  await (await loadPlugin({ document, fetch: device.fetch }))({ innerHTML: '' }, device.api);
  assert.equal(document.elements['ph-version'].textContent, 'Version: v0.1.1 — Update available: v0.2.0');
  assert.ok(!device.calls.relay.some((url) => url.includes('api.github.com')));

  // Switching to a catalog without Plugin Hub must clear the old update notice.
  const originalRelay = device.api.relay;
  device.api.relay = (method, url) => url === COMMUNITY_CATALOG
    ? Promise.resolve({ status: 200, body: JSON.stringify({ name: 'Custom', plugins: [] }) })
    : originalRelay(method, url);
  await document.elements['ph-refresh'].onclick();
  assert.equal(document.elements['ph-version'].textContent, 'Version: v0.1.1');
});

test('browser hub writes its config only when it changes', async () => {
  const configText = JSON.stringify({ extraCatalogs: [] }, null, 2);
  const document = fakeDocument();
  const device = hubDevice({ catalog: SMALL_CATALOG, configText });
  await (await loadPlugin({ document, fetch: device.fetch }))({ innerHTML: '' }, device.api);
  await document.elements['ph-refresh'].onclick();
  assert.deepEqual(device.calls.writes, []);

  // A missing config is written once.
  const fresh = hubDevice({ catalog: SMALL_CATALOG });
  const freshDocument = fakeDocument();
  await (await loadPlugin({ document: freshDocument, fetch: fresh.fetch }))({ innerHTML: '' }, fresh.api);
  await freshDocument.elements['ph-refresh'].onclick();
  assert.equal(fresh.calls.writes.length, 1);
  assert.equal(fresh.calls.writes[0].path, '/.crosspoint/plugins/pluginhub/config.json');
});

test('refresh keeps the current list until the new one is ready', async () => {
  const document = fakeDocument();
  const catalog = (title) => ({
    name: 'Community Plugins',
    plugins: [{ name: 'sample', title, version: '1.0.0', base: 'https://example.test/s/', files: ['manifest.json'] }],
  });
  let pendingCatalog = null;
  let failCatalog = false;

  async function fetch(url) {
    if (url === '/api/status') return response({ json: { deviceModel: 'x4', psramBytes: 0 } });
    if (url.startsWith('/api/files?path=')) return response({ json: [] });
    if (url.startsWith('/download?path=')) return response({ status: 404 });
    throw new Error('unexpected fetch: ' + url);
  }

  const api = {
    async writeFile() {
      return { ok: true };
    },
    async relay(method, url) {
      if (url === LIST_INDEX) {
        return { status: 200, body: JSON.stringify({ lists: [{ title: 'Community Plugins', url: COMMUNITY_CATALOG }] }) };
      }
      if (url.includes('/releases/latest')) return { status: 200, body: JSON.stringify({ tag_name: 'v0.1.1' }) };
      if (url === COMMUNITY_CATALOG) {
        if (failCatalog) return { status: 404, body: '' };
        if (pendingCatalog) return pendingCatalog;
        return { status: 200, body: JSON.stringify(catalog('First')) };
      }
      return { status: 404, body: '' };
    },
  };

  const render = await loadPlugin({ document, fetch });
  await render({ innerHTML: '' }, api);
  const list = document.elements['ph-list'];
  const titles = () => list.children.filter((c) => c.className === 'setting-row').map((c) => c.id);
  assert.deepEqual(titles(), ['ph-plugin-sample']);
  const firstCard = list.children.find((c) => c.className === 'setting-row');

  let resolveCatalog;
  pendingCatalog = new Promise((resolve) => {
    resolveCatalog = resolve;
  });
  const refreshing = document.elements['ph-refresh'].onclick();
  await new Promise((resolve) => setImmediate(resolve));
  // While the catalog loads, the old list stays in place but inactive.
  assert.ok(list.children.includes(firstCard));
  assert.equal(list.style.pointerEvents, 'none');
  assert.ok(list.querySelectorAll('button').every((button) => button.disabled),
    'retained buttons must not be keyboard-activatable');

  resolveCatalog({ status: 200, body: JSON.stringify(catalog('Second')) });
  await refreshing;
  assert.deepEqual(titles(), ['ph-plugin-sample']);
  assert.ok(!list.children.includes(firstCard));
  assert.equal(list.style.pointerEvents, '');
  assert.equal(list.style.opacity, '');
  assert.ok(list.querySelectorAll('button').every((button) => !button.disabled),
    'replacement buttons should be enabled');

  pendingCatalog = null;
  failCatalog = true;
  await document.elements['ph-refresh'].onclick();
  assert.equal(list.children.length, 0);
  assert.equal(list.style.pointerEvents, '');
  assert.match(document.elements['ph-status'].textContent, /^Error loading/);
});

test('overlapping refreshes ignore stale failures and successful responses', async () => {
  const document = fakeDocument();
  const catalog = (title) => ({
    name: 'Community Plugins',
    plugins: [{ name: 'sample', title, version: '1.0.0', base: 'https://example.test/s/', files: ['manifest.json'] }],
  });
  const requests = [];
  let firstLoad = true;
  const api = {
    async writeFile() {
      return { ok: true };
    },
    async relay(method, url) {
      if (url === LIST_INDEX) {
        return { status: 200, body: JSON.stringify({ lists: [{ title: 'Community Plugins', url: COMMUNITY_CATALOG }] }) };
      }
      if (url.includes('/releases/latest')) return { status: 200, body: JSON.stringify({ tag_name: 'v0.1.1' }) };
      if (url === COMMUNITY_CATALOG) {
        if (firstLoad) {
          firstLoad = false;
          return { status: 200, body: JSON.stringify(catalog('Initial')) };
        }
        return new Promise((resolve, reject) => requests.push({ resolve, reject }));
      }
      return { status: 404, body: '' };
    },
  };
  async function fetch(url) {
    if (url === '/api/status') return response({ json: { deviceModel: 'x4', psramBytes: 0 } });
    if (url.startsWith('/api/files?path=')) return response({ json: [] });
    if (url.startsWith('/download?path=')) return response({ status: 404 });
    throw new Error('unexpected fetch: ' + url);
  }

  const localStorage = fakeStorage();
  const render = await loadPlugin({ document, fetch, localStorage });
  await render({ innerHTML: '' }, api);
  const list = document.elements['ph-list'];
  const refresh = () => document.elements['ph-refresh'].onclick();
  const currentTitle = () => list.children.find((c) => c.id === 'ph-plugin-sample')?.children[0].innerHTML;
  const tick = () => new Promise((resolve) => setImmediate(resolve));

  const oldFailure = refresh();
  await tick();
  const latest = refresh();
  await tick();
  assert.equal(requests.length, 2);
  requests[1].resolve({ status: 200, body: JSON.stringify(catalog('Latest')) });
  await latest;
  const latestCard = list.children.find((c) => c.id === 'ph-plugin-sample');
  assert.match(currentTitle(), /Latest/);
  requests[0].reject(new Error('old catalog failed'));
  await oldFailure;
  assert.ok(list.children.includes(latestCard));
  assert.match(currentTitle(), /Latest/);
  assert.equal(document.elements['ph-status'].textContent, '1 plugin available.');
  assert.equal(list.style.pointerEvents, '');

  const oldSuccess = refresh();
  await tick();
  const newest = refresh();
  await tick();
  assert.equal(requests.length, 4);
  requests[3].resolve({ status: 200, body: JSON.stringify(catalog('Newest')) });
  await newest;
  requests[2].resolve({ status: 200, body: JSON.stringify(catalog('Obsolete')) });
  await oldSuccess;
  assert.match(currentTitle(), /Newest/);
  assert.doesNotMatch(currentTitle(), /Obsolete/);
  const cached = JSON.parse(localStorage.data.get('pluginhub.remote:' + COMMUNITY_CATALOG));
  assert.match(cached.body, /Newest/);
  assert.doesNotMatch(cached.body, /Obsolete/, 'a stale response must not overwrite the cache');
  assert.equal(document.elements['ph-status'].textContent, '1 plugin available.');
});

test('failed actions do not re-enable stale buttons during a refresh', async () => {
  for (const kind of ['install', 'remove']) {
    const document = fakeDocument();
    const catalog = {
      name: 'Community Plugins',
      plugins: [{ name: 'sample', title: 'Sample', version: '1.0.0', base: 'https://example.test/s/', files: ['manifest.json'] }],
    };
    let pendingRefresh = false;
    let resolveCatalog;
    let rejectAction;
    let signalActionStarted;
    const actionStarted = new Promise((resolve) => { signalActionStarted = resolve; });

    async function fetch(url) {
      if (url === '/api/status') return response({ json: { deviceModel: 'x4', psramBytes: 0 } });
      if (url.startsWith('/download?path=')) return response({ status: 404 });
      if (url.startsWith('/api/files?path=')) {
        const path = new URL(url, 'http://device').searchParams.get('path');
        return response({ json: path === '/.crosspoint/plugins'
          ? [{ name: 'sample', isDirectory: true }] : [] });
      }
      if (url === '/mkdir') return response({});
      if (url === '/delete') {
        if (kind === 'remove') {
          return new Promise((_resolve, reject) => {
            rejectAction = reject;
            signalActionStarted();
          });
        }
        return response({});
      }
      throw new Error('unexpected fetch: ' + url);
    }

    const api = {
      async writeFile() { return { ok: true }; },
      async relay(_method, url) {
        if (url === LIST_INDEX) {
          return { status: 200, body: JSON.stringify({ lists: [{ title: 'Community Plugins', url: COMMUNITY_CATALOG }] }) };
        }
        if (url.includes('/releases/latest')) return { status: 200, body: JSON.stringify({ tag_name: 'v0.1.1' }) };
        if (url === COMMUNITY_CATALOG) {
          if (pendingRefresh) {
            return new Promise((resolve) => { resolveCatalog = resolve; });
          }
          return { status: 200, body: JSON.stringify(catalog) };
        }
        return { status: 404, body: '' };
      },
      async fetchToSd() {
        if (kind === 'install') {
          return new Promise((_resolve, reject) => {
            rejectAction = reject;
            signalActionStarted();
          });
        }
        return { status: 200 };
      },
    };

    const render = await loadPlugin({ document, fetch });
    await render({ innerHTML: '' }, api);
    const list = document.elements['ph-list'];
    const oldCard = list.children.find((child) => child.id === 'ph-plugin-sample');
    const buttons = oldCard.querySelectorAll('button');
    const actionButton = kind === 'install' ? buttons[0] : buttons[1];
    assert.ok(actionButton, kind + ' button exists');

    const runningAction = actionButton.onclick();
    await actionStarted;
    pendingRefresh = true;
    const refreshing = document.elements['ph-refresh'].onclick();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(list.style.pointerEvents, 'none');
    assert.ok(buttons.every((button) => button.disabled));

    rejectAction(new Error('simulated ' + kind + ' failure'));
    await runningAction;
    assert.equal(actionButton.disabled, true, kind + ' failure must not reactivate its stale button');
    assert.ok(buttons.every((button) => button.disabled));

    resolveCatalog({ status: 200, body: JSON.stringify(catalog) });
    await refreshing;
    assert.ok(!list.children.includes(oldCard));
    assert.ok(list.querySelectorAll('button').every((button) => !button.disabled));
  }
});

test('unexpected refresh failure clears loading state', async () => {
  const document = fakeDocument();
  // Simulate an unexpected DOM failure rather than an unchanged config write.
  const api = {
    async writeFile() {
      // A previously saved, unchanged config no longer needs a write.
      return { ok: true };
    },
    async relay(method, url) {
      if (url === LIST_INDEX) {
        return { status: 200, body: JSON.stringify({ lists: [{ title: 'Community Plugins', url: COMMUNITY_CATALOG }] }) };
      }
      if (url.includes('/releases/latest')) return { status: 200, body: JSON.stringify({ tag_name: 'v0.1.1' }) };
      if (url === COMMUNITY_CATALOG) {
        return { status: 200, body: JSON.stringify({
          name: 'Community Plugins',
          plugins: [{ name: 'sample', title: 'Sample', version: '1.0.0', base: 'https://example.test/s/', files: ['manifest.json'] }],
        }) };
      }
      return { status: 404, body: '' };
    },
  };
  async function fetch(url) {
    if (url === '/api/status') return response({ json: { deviceModel: 'x4', psramBytes: 0 } });
    if (url.startsWith('/api/files?path=')) return response({ json: [] });
    if (url.startsWith('/download?path=')) return response({ status: 404 });
    throw new Error('unexpected fetch: ' + url);
  }
  const render = await loadPlugin({ document, fetch });
  await render({ innerHTML: '' }, api);
  const list = document.elements['ph-list'];
  assert.ok(list.children.length > 0);
  document.createElement = () => { throw new Error('DOM unavailable'); };
  await document.elements['ph-refresh'].onclick();
  assert.equal(list.children.length, 0);
  assert.equal(list.style.pointerEvents, '');
  assert.equal(list.style.opacity, '');
  assert.match(document.elements['ph-status'].textContent, /Error loading.*DOM unavailable/);
});
