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
        name: 'x4-only',
        title: 'X4 Only',
        version: '1.0.0',
        base: 'https://example.test/x4/',
        files: ['manifest.json'],
        compatibility: { advisory: 'models=x4|x4pro' },
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
      if (path === '/.crosspoint/plugins/pluginhub/.catalog-cache.json') {
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
      if (url.includes('/repos/crosspoint-reader/crosspoint-plugin-hub/releases/latest')) {
        return { status: 200, body: JSON.stringify({ tag_name: 'v0.1.1' }) };
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

  assert.equal(relayCalls.length, 3);
  assert.equal(relayCalls[0], LIST_INDEX);
  assert.match(relayCalls[1], /crosspoint-plugin-hub\/releases\/latest$/);
  assert.deepEqual(relayCalls.slice(2), [COMMUNITY_CATALOG]);
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
  assert.equal(cards.length, 3);
  assert.ok(cards.some((card) => card.id === 'ph-plugin-sample-newer'));
  assert.ok(!cards.some((card) => card.id === 'ph-plugin-x4-only'));
  assert.equal(cards[0].children[1].children[0].textContent, 'Reinstall');
  assert.match(cards[0].children[1].children[0].className, /ph-btn-reinstall/);
  assert.match(cards[0].children[1].children.find(child => child.textContent === 'Remove').className, /ph-btn-remove/);
  for (const card of cards) {
    assert.equal(card.style.display, 'grid');
    assert.equal(card.style.gridTemplateColumns, 'minmax(0, 1fr) max-content');
    assert.equal(card.style.width, '100%');
    assert.equal(card.children[0].style.minWidth, '0');
    assert.equal(card.children[1].style.justifyContent, 'flex-end');
    assert.equal(card.children[1].style.justifySelf, 'end');
    assert.equal(card.children[1].style.marginLeft, '0');
  }
  assert.equal(cards[1].children[1].children[0].textContent, 'Update');
  assert.equal(cards[2].children[1].children[0].textContent, 'Install');
  assert.match(document.elements['ph-status'].textContent, /3 plugins available, 1 update/);

  assert.deepEqual(fetchToSdCalls, [
    { url: COMMUNITY_CATALOG, dest: '/.crosspoint/plugins/pluginhub/.catalog-cache.json' },
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
      if (url.includes('/repos/crosspoint-reader/crosspoint-plugin-hub/releases/latest')) {
        return { status: 200, body: JSON.stringify({ tag_name: 'v0.1.4' }) };
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
  assert.deepEqual(relayCalls.slice(2), [COMMUNITY_CATALOG]);
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
      if (url.includes('/repos/crosspoint-reader/crosspoint-plugin-hub/releases/latest')) {
        return { status: 200, body: JSON.stringify({ tag_name: 'v0.1.6' }) };
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
      if (url.includes('/repos/crosspoint-reader/crosspoint-plugin-hub/releases/latest')) {
        return { status: 200, body: JSON.stringify({ tag_name: 'v0.1.6' }) };
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

  resolveCatalog({ status: 200, body: JSON.stringify(catalog('Second')) });
  await refreshing;
  assert.deepEqual(titles(), ['ph-plugin-sample']);
  assert.ok(!list.children.includes(firstCard));
  assert.equal(list.style.pointerEvents, '');
  assert.equal(list.style.opacity, '');

  pendingCatalog = null;
  failCatalog = true;
  await document.elements['ph-refresh'].onclick();
  assert.equal(list.children.length, 0);
  assert.equal(list.style.pointerEvents, '');
  assert.match(document.elements['ph-status'].textContent, /^Error loading/);
});
