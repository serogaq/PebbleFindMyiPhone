'use strict';

var assert = require('assert');
var fs = require('fs');
var os = require('os');
var path = require('path');
var api = require('../src/pkjs/lib/api');
var configPage = require('../src/pkjs/lib/config-page');
var localization = require('../src/pkjs/lib/localization');
var protocol = require('../src/pkjs/lib/protocol');
var settings = require('../src/pkjs/lib/settings');
var localizationGenerator = require('../scripts/generate-localization');
var englishSettings = require('../localization/en/settings.json');

var tests = [];
function test(name, fn) {
  tests.push({name: name, fn: fn});
}

test('validates DNS, IPv4 and bracketed IPv6 address:port', function() {
  assert.strictEqual(settings.validate({address: 'find.example.com:443', ssl: true, token: 'x'}).ok, true);
  assert.strictEqual(settings.validate({address: '192.168.1.20:8080', ssl: false, token: 'x'}).ok, true);
  assert.strictEqual(settings.validate({address: '[fd00::1]:8080', ssl: true, token: 'x'}).ok, true);
});

test('rejects missing, schemed, path and invalid port addresses', function() {
  assert.strictEqual(settings.validate({address: '', token: ''}).missing, true);
  ['https://host:443', 'host:443/path', 'host', 'host:0', 'host:65536'].forEach(function(address) {
    assert.strictEqual(settings.validate({address: address, token: 'x'}).ok, false, address);
  });
});

test('builds HTTP and HTTPS base URLs without exposing config to watch', function() {
  assert.strictEqual(settings.STORAGE_KEY, 'find-my-iphone.settings.v1');
  assert.strictEqual(settings.baseUrl({address: 'host:443', ssl: true, token: 'x'}), 'https://host:443');
  assert.strictEqual(settings.baseUrl({address: 'host:8080', ssl: false, token: 'x'}), 'http://host:8080');
});

test('maps stable backend errors to watch protocol results', function() {
  assert.strictEqual(api.resultForResponse(401, {}).code, protocol.RESULT.API_UNAUTHORIZED);
  assert.strictEqual(api.resultForResponse(503, {error: {code: 'icloud.authentication_required'}}).code,
    protocol.RESULT.APPLE_AUTH_REQUIRED);
  assert.strictEqual(api.resultForResponse(503, {error: {code: 'target.not_found'}}).code,
    protocol.RESULT.TARGET_NOT_FOUND);
  assert.strictEqual(api.resultForResponse(502, {error: {
    code: 'icloud.command_outcome_unknown', command_may_have_been_dispatched: true
  }}).commandDispatched, true);
});

test('startup status check validates backend token and Apple readiness', function() {
  withFakeXhr([
    {status: 503, body: {error: {code: 'icloud.authentication_required'}}}
  ], function(requests) {
    var result;
    api.checkStatus({address: 'host:443', ssl: true, token: 'secret'}, function(value) {
      result = value;
    });
    assert.strictEqual(requests.length, 1);
    assert.strictEqual(requests[0].method, 'GET');
    assert.strictEqual(requests[0].url, 'https://host:443/v1/status');
    assert.strictEqual(requests[0].headers.Authorization, 'Bearer secret');
    assert.strictEqual(result.code, protocol.RESULT.APPLE_AUTH_REQUIRED);
  });
});

function withFakeXhr(responses, body) {
  var requests = [];
  global.XMLHttpRequest = function() {
    this.headers = {};
    requests.push(this);
  };
  global.XMLHttpRequest.prototype.open = function(method, url) {
    this.method = method;
    this.url = url;
  };
  global.XMLHttpRequest.prototype.setRequestHeader = function(key, value) {
    this.headers[key] = value;
  };
  global.XMLHttpRequest.prototype.send = function() {
    var response = responses.shift();
    if (response.transportError) {
      this.onerror();
      return;
    }
    this.status = response.status;
    this.responseText = JSON.stringify(response.body);
    this.readyState = 4;
    this.onreadystatechange();
  };
  body(requests);
  delete global.XMLHttpRequest;
}

test('retries only device lookup once with the same idempotency key', function() {
  var realTimeout = global.setTimeout;
  global.setTimeout = function(callback) { callback(); };
  withFakeXhr([
    {status: 502, body: {error: {code: 'icloud.device_lookup_failed', retryable: true}}},
    {status: 202, body: {status: 'submitted'}}
  ], function(requests) {
    var result;
    api.playSound({address: 'host:443', ssl: true, token: 'secret'}, function(value) { result = value; });
    assert.strictEqual(requests.length, 2);
    assert.strictEqual(requests[0].headers['Idempotency-Key'], requests[1].headers['Idempotency-Key']);
    assert.strictEqual(requests[0].headers.Authorization, 'Bearer secret');
    assert.strictEqual(result.code, protocol.RESULT.OK);
  });
  global.setTimeout = realTimeout;
});

test('does not retry an ambiguous transport failure', function() {
  withFakeXhr([{transportError: true}], function(requests) {
    var result;
    api.playSound({address: 'host:443', ssl: true, token: 'secret'}, function(value) { result = value; });
    assert.strictEqual(requests.length, 1);
    assert.strictEqual(result.code, protocol.RESULT.OUTCOME_UNKNOWN);
    assert.strictEqual(result.commandDispatched, true);
  });
});

test('treats XHR readyState 4 with status zero as an ambiguous transport failure', function() {
  withFakeXhr([{status: 0, body: {}}], function(requests) {
    var result;
    api.playSound({address: 'host:443', ssl: true, token: 'secret'}, function(value) {
      result = value;
    });
    assert.strictEqual(requests.length, 1);
    assert.strictEqual(result.code, protocol.RESULT.OUTCOME_UNKNOWN);
    assert.strictEqual(result.commandDispatched, true);
  });
});

test('does not retry device lookup unless backend marks it safe and pre-dispatch', function() {
  withFakeXhr([
    {status: 502, body: {error: {
      code: 'icloud.device_lookup_failed', retryable: false, command_dispatched: false
    }}}
  ], function(requests) {
    var result;
    api.playSound({address: 'host:443', ssl: true, token: 'secret'}, function(value) {
      result = value;
    });
    assert.strictEqual(requests.length, 1);
    assert.strictEqual(result.code, protocol.RESULT.DEVICE_LOOKUP_FAILED);
  });
});

test('manifest targets exactly the four modern watch platforms', function() {
  var manifest = require('../package.json');
  assert.strictEqual(manifest.name, 'pebble-find-my-iphone');
  assert.strictEqual(manifest.pebble.displayName, 'Find My iPhone');
  assert(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
    manifest.pebble.uuid));
  assert(/^\d+\.\d+\.0$/.test(manifest.version));
  assert.strictEqual(manifest.author, 'serogaq');
  assert.deepStrictEqual(manifest.pebble.targetPlatforms, ['diorite', 'emery', 'flint', 'gabbro']);
  assert.deepStrictEqual(manifest.pebble.capabilities, ['configurable']);
  assert.strictEqual(manifest.pebble.messageKeys.indexOf('HTTP_STATUS'), -1);
  assert.strictEqual(manifest.pebble.messageKeys.indexOf('RETRYABLE'), -1);
  assert.strictEqual(manifest.pebble.messageKeys.indexOf('COMMAND_DISPATCHED'), -1);
});

test('settings page renders first and starts live status check after build', function() {
  var buildInfo = {version: '1.0.0', built_at: 'Aug 31, 2026 13:42:18 GMT'};
  var config = configPage.buildConfig(englishSettings, buildInfo);
  var status = config.filter(function(item) { return item.id === 'status'; })[0];
  var token = config.filter(function(item) { return item.id === 'token'; })[0];
  var requiredNotice = config.filter(function(item) { return item.id === 'requiredNotice'; })[0];
  var license = config.filter(function(item) { return item.id === 'license'; })[0];
  var version = config.filter(function(item) { return item.id === 'version'; })[0];
  var builtAt = config.filter(function(item) { return item.id === 'builtAt'; })[0];
  var submitIndex = config.map(function(item) { return item.type; }).indexOf('submit');
  var statusHeadingIndex = config.findIndex(function(item) {
    return item.type === 'heading' && item.defaultValue === englishSettings.status_title;
  });
  var source = configPage.customClay.toString();

  assert(status, 'status component');
  assert(token, 'token component');
  assert(requiredNotice, 'required notice component');
  assert(license, 'license component');
  assert(version, 'version component');
  assert(builtAt, 'build time component');
  assert.strictEqual(submitIndex + 1, statusHeadingIndex);
  assert.strictEqual(token.attributes.type, 'password');
  assert.strictEqual(requiredNotice.defaultValue,
    'Required Notice: Copyright © serogaq (https://github.com/serogaq/PebbleFindMyiPhone)');
  assert(license.defaultValue.indexOf('https://polyformproject.org/licenses/noncommercial/1.0.0') !== -1);
  assert.strictEqual(version.defaultValue, 'Version: 1.0.0');
  assert.strictEqual(builtAt.defaultValue, 'Built at: Aug 31, 2026 13:42:18 GMT');
  assert.strictEqual(config.indexOf(version), config.indexOf(license) + 1);
  assert.strictEqual(config.indexOf(builtAt), config.indexOf(version) + 1);
  assert(source.indexOf("clay.on(clay.EVENTS.AFTER_BUILD") !== -1);
  assert(source.indexOf('checkStatus();') !== -1);
  assert(source.indexOf("'/v1/status'") !== -1);
  assert(source.indexOf('setInterval') !== -1);
});

test('all locale directories contain complete non-empty watch and settings translations', function() {
  var localizationRoot = path.join(__dirname, '../localization');
  var localeNames = fs.readdirSync(localizationRoot, {withFileTypes: true})
    .filter(function(entry) { return entry.isDirectory() && entry.name.charAt(0) !== '.'; })
    .map(function(entry) { return entry.name; })
    .sort();
  var requiredNotice =
    'Required Notice: Copyright © serogaq (https://github.com/serogaq/PebbleFindMyiPhone)';

  assert(localeNames.indexOf('en') !== -1, 'English fallback locale');
  ['watch.json', 'settings.json'].forEach(function(filename) {
    var dictionaries = {};
    var allKeys = {};
    localeNames.forEach(function(locale) {
      var dictionary = JSON.parse(fs.readFileSync(
        path.join(localizationRoot, locale, filename), 'utf8'));
      dictionaries[locale] = dictionary;
      Object.keys(dictionary).forEach(function(key) {
        assert(/^[a-z][a-z0-9_]*$/.test(key), locale + '/' + filename + ': ' + key);
        assert.strictEqual(typeof dictionary[key], 'string', locale + '/' + filename + ': ' + key);
        assert(dictionary[key].trim(), locale + '/' + filename + ': empty ' + key);
        allKeys[key] = true;
      });
    });
    var expectedKeys = Object.keys(allKeys).sort();
    localeNames.forEach(function(locale) {
      assert.deepStrictEqual(Object.keys(dictionaries[locale]).sort(), expectedKeys,
        locale + '/' + filename + ' must contain exactly the same keys as every locale');
    });
  });
  localeNames.forEach(function(locale) {
    var dictionary = JSON.parse(fs.readFileSync(
      path.join(localizationRoot, locale, 'settings.json'), 'utf8'));
    assert.strictEqual(dictionary.required_notice, requiredNotice, locale + ' required notice');
  });
});

test('locale resolver supports regional tags and falls back to English', function() {
  var catalogs = {
    en: {name: 'English'},
    fr: {name: 'French'},
    'pt-br': {name: 'Brazilian Portuguese'}
  };

  assert.strictEqual(localization.normalizeLocale('PT_BR'), 'pt-br');
  assert.strictEqual(localization.resolve(catalogs, 'fr_FR').name, 'French');
  assert.strictEqual(localization.resolve(catalogs, 'pt-BR').name, 'Brazilian Portuguese');
  assert.strictEqual(localization.resolve(catalogs, 'de-DE').name, 'English');
  assert.strictEqual(localization.resolve(catalogs, '').name, 'English');
});

test('build metadata uses package version and stable GMT formatting', function() {
  var manifest = require('../package.json');
  var buildTime = localizationGenerator.formatBuildTime(
    new Date('2026-08-31T13:42:18Z'));
  var rendered = localizationGenerator.renderSettingsModule({
    en: {settings: englishSettings}
  }, {version: manifest.version, built_at: buildTime});

  assert.strictEqual(buildTime, 'Aug 31, 2026 13:42:18 GMT');
  assert(rendered.indexOf('"version": "' + manifest.version + '"') !== -1);
  assert(rendered.indexOf('"built_at": "Aug 31, 2026 13:42:18 GMT"') !== -1);
});

test('localization generator discovers a new folder without a language registry', function() {
  var temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'pebble-localization-'));
  var localizationRoot = path.join(temporaryRoot, 'localization');
  try {
    ['en', 'fr'].forEach(function(locale) {
      var directory = path.join(localizationRoot, locale);
      fs.mkdirSync(directory, {recursive: true});
      fs.writeFileSync(path.join(directory, 'watch.json'), JSON.stringify({title: locale}), 'utf8');
      fs.writeFileSync(path.join(directory, 'settings.json'),
        JSON.stringify(locale === 'en' ? {save: 'Save'} : {}), 'utf8');
    });
    var catalogs = localizationGenerator.loadCatalogs(localizationRoot);
    var settingsModule = localizationGenerator.renderSettingsModule(catalogs, {
      version: '1.0.0', built_at: 'Aug 31, 2026 13:42:18 GMT'
    });
    var cSource = localizationGenerator.renderCSource(catalogs, ['title']);

    assert.deepStrictEqual(Object.keys(catalogs).sort(), ['en', 'fr']);
    assert(settingsModule.indexOf('"fr"') !== -1);
    assert(settingsModule.indexOf('"save": "Save"') !== -1);
    assert(cSource.indexOf('{"fr", s_locale_fr}') !== -1);
  } finally {
    fs.rmSync(temporaryRoot, {recursive: true, force: true});
  }
});

test('watch and Settings select their own system locale sources', function() {
  var cSource = fs.readFileSync(path.join(__dirname, '../src/c/app.c'), 'utf8');
  var pkjsSource = fs.readFileSync(path.join(__dirname, '../src/pkjs/index.js'), 'utf8');

  assert(cSource.indexOf('localization_init(i18n_get_system_locale())') !== -1);
  assert.strictEqual(cSource.indexOf('prv_text('), -1);
  assert(pkjsSource.indexOf('navigator.language') !== -1);
  assert.strictEqual(pkjsSource.indexOf('getActiveWatchInfo'), -1);
});

test('RePebble description contains only user-facing store copy', function() {
  var description = fs.readFileSync(path.join(__dirname, '../store/description.txt'), 'utf8');
  assert.strictEqual(description.indexOf('Required Notice:'), -1);
  assert.strictEqual(description.indexOf('PolyForm'), -1);
});

test('release workflow keeps legal notice out of RePebble release notes', function() {
  var workflow = fs.readFileSync(
    path.join(__dirname, '../../.github/workflows/app-release.yml'), 'utf8');
  var repebbleJob = workflow.slice(workflow.indexOf('  repebble-draft:'));

  assert.strictEqual(workflow.indexOf('dist/github-release-notes.md'), -1);
  assert(workflow.indexOf(
    'github_release_notes="$RUNNER_TEMP/github-release-notes.md"') !== -1);
  assert.strictEqual(
    (workflow.match(/--notes-file "\$github_release_notes"/g) || []).length, 2);
  assert(workflow.indexOf('cat dist/NOTICE') !== -1);
  assert(repebbleJob.indexOf('--release-notes "$(cat dist/release-notes.md)"') !== -1);
  assert.strictEqual(repebbleJob.indexOf('github_release_notes'), -1);
});

test('manual Clay setup injects localized loader strings before generating URL', function() {
  var source = fs.readFileSync(path.join(__dirname, '../src/pkjs/index.js'), 'utf8');
  var metadata = source.indexOf('activeClay.meta.userData = userData');
  var generate = source.indexOf('activeClay.generateUrl()');
  assert(metadata !== -1 && metadata < generate);
  assert(source.indexOf('addressPattern: settingsStore.ADDRESS_PATTERN_SOURCE') !== -1);
});

test('watch guards startup status against an in-flight command and handles dropped inbox', function() {
  var source = fs.readFileSync(path.join(__dirname, '../src/c/app.c'), 'utf8');
  assert(source.indexOf('if (!s_busy) {\n    prv_send_request(REQUEST_CHECK_STATUS);') !== -1);
  assert(source.indexOf('app_message_register_inbox_dropped(prv_inbox_dropped)') !== -1);
  assert(source.indexOf('dict_calc_buffer_size(3') !== -1);
});

test('C and JS result enums remain aligned', function() {
  var cSource = fs.readFileSync(path.join(__dirname, '../src/c/app.c'), 'utf8');
  Object.keys(protocol.RESULT).forEach(function(name) {
    var pattern = new RegExp('RESULT_' + name + '\\s*=\\s*' + protocol.RESULT[name] + '[,\\n]');
    assert(pattern.test(cSource), name);
  });
});

(function run() {
  var passed = 0;
  tests.forEach(function(item) {
    try {
      item.fn();
      passed += 1;
      console.log('ok - ' + item.name);
    } catch (error) {
      console.error('not ok - ' + item.name);
      throw error;
    }
  });
  console.log('\n' + passed + ' tests passed');
}());
