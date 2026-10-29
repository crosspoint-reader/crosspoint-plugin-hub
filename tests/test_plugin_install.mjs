import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../plugin.js', import.meta.url), 'utf8');
const installer = source.slice(
  source.indexOf('  async function mkdir(path) {'),
  source.indexOf('  async function uninstallPlugin(')
);
assert.ok(installer.includes('async function installPlugin('));

const plugin = (files = ['manifest.json', 'device.json', 'config.json', 'plugin.js']) => ({
  name: 'ybx',
  base: 'https://example.test/ybx/',
  files,
});

function scenario({ configStatus = 404, networkFailure = false } = {}) {
  const downloaded = [];
  const inspected = [];
  const madeDirs = [];
  const progress = [];
  const target = '/plugins/ybx';
  const context = vm.createContext({
    PLUGINS_DIR: '/.crosspoint/plugins',
    Set, encodeURIComponent,
    fetch: async (url, options) => {
      if (url === '/mkdir') {
        madeDirs.push(new URLSearchParams(options.body).get('path'));
        return {ok: true, status: 200};
      }
      if (url.startsWith('/download?path=')) {
        const path = new URLSearchParams(url.slice(url.indexOf('?') + 1)).get('path');
        inspected.push(path);
        if (networkFailure) throw new Error('network unavailable');
        return {ok: configStatus >= 200 && configStatus < 300, status: configStatus};
      }
      throw new Error('unexpected request ' + url);
    },
    api: {
      fetchToSd: async (url, path) => {
        downloaded.push({url, path});
        return {status: 200};
      },
    },
  });
  vm.runInContext(installer + '\nglobalThis.installPlugin = installPlugin;', context);
  return {
    install: (packageData = plugin()) =>
      context.installPlugin(packageData, (count, total) => progress.push([count, total]), target),
    downloaded, inspected, madeDirs, progress, target,
  };
}

test('update or reinstall preserves an existing config.json while updating runtime files', async () => {
  const host = scenario({configStatus: 200});
  await host.install();
  assert.deepEqual(host.inspected, ['/plugins/ybx/config.json']);
  assert.deepEqual(host.downloaded.map(x => x.path), [
    '/plugins/ybx/manifest.json',
    '/plugins/ybx/device.json',
    '/plugins/ybx/plugin.js',
  ]);
  assert.deepEqual(host.progress.at(-1), [4, 4]);
  assert.equal(host.downloaded.some(x => x.path.endsWith('config.json')), false);
});

test('first install receives default config.json when no existing file is found', async () => {
  const host = scenario({configStatus: 404});
  await host.install();
  assert.deepEqual(host.inspected, ['/plugins/ybx/config.json']);
  assert.ok(host.downloaded.some(x => x.path === '/plugins/ybx/config.json'));
  assert.deepEqual(host.progress.at(-1), [4, 4]);
});

test('existing settings are protected when the existence check returns an error', async () => {
  for (const status of [401, 403, 500]) {
    const host = scenario({configStatus: status});
    await assert.rejects(host.install(), new RegExp('cannot check existing config.json \\(HTTP ' + status + '\\)'));
    assert.equal(host.downloaded.length, 0);
    assert.equal(host.madeDirs.length, 0);
  }
});

test('network failure checking config.json refuses to write instead of assuming absent', async () => {
  const host = scenario({networkFailure: true});
  await assert.rejects(host.install(), /cannot check existing config.json: network unavailable/);
  assert.equal(host.downloaded.length, 0);
});

test('catalog cannot distribute a device token or use traversal paths', async () => {
  const host = scenario({configStatus: 404});
  for (const name of ['token.json', 'TOKEN.JSON', 'Token.Json', 'data/tOkEn.Json']) {
    await assert.rejects(host.install(plugin(['manifest.json', name])), /token.json/);
  }
  await assert.rejects(host.install(plugin(['manifest.json', '../config.json'])), /unsafe plugin file path/);
  await assert.rejects(host.install(plugin(['manifest.json', 'MANIFEST.JSON'])), /duplicate plugin path/);
  assert.equal(host.inspected.length, 0);
  assert.equal(host.madeDirs.length, 0);
  assert.equal(host.downloaded.length, 0);
});

test('plugins without config.json install without extra file checks', async () => {
  const host = scenario({configStatus: 500});
  await host.install(plugin(['manifest.json', 'plugin.js']));
  assert.deepEqual(host.inspected, []);
  assert.deepEqual(host.downloaded.map(x => x.path), [
    '/plugins/ybx/manifest.json', '/plugins/ybx/plugin.js'
  ]);
});

test('case-folded Config.json preserves the existing root config on FAT volumes', async () => {
  const host = scenario({configStatus: 200});
  await host.install(plugin(['manifest.json', 'Config.JSON', 'plugin.js']));
  assert.deepEqual(host.inspected, ['/plugins/ybx/config.json']);
  assert.deepEqual(host.downloaded.map(x => x.path), [
    '/plugins/ybx/manifest.json', '/plugins/ybx/plugin.js'
  ]);
});

test('case-folded Config.json gets default values on first install', async () => {
  const host = scenario({configStatus: 404});
  await host.install(plugin(['manifest.json', 'Config.JSON', 'plugin.js']));
  assert.ok(host.downloaded.some(x => x.path === '/plugins/ybx/Config.JSON'));
});
