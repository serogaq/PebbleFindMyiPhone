'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');
var api = require('../src/pkjs/lib/api');
var configPage = require('../src/pkjs/lib/config-page');
var protocol = require('../src/pkjs/lib/protocol');
var settings = require('../src/pkjs/lib/settings');

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
  var config = configPage.buildConfig(configPage.EN);
  var status = config.filter(function(item) { return item.id === 'status'; })[0];
  var token = config.filter(function(item) { return item.id === 'token'; })[0];
  var requiredNotice = config.filter(function(item) { return item.id === 'requiredNotice'; })[0];
  var license = config.filter(function(item) { return item.id === 'license'; })[0];
  var source = configPage.customClay.toString();

  assert(status, 'status component');
  assert(token, 'token component');
  assert(requiredNotice, 'required notice component');
  assert(license, 'license component');
  assert.strictEqual(token.attributes.type, 'password');
  assert.strictEqual(requiredNotice.defaultValue,
    'Required Notice: Copyright © serogaq (https://github.com/serogaq/PebbleFindMyiPhone)');
  assert(license.defaultValue.indexOf('https://polyformproject.org/licenses/noncommercial/1.0.0') !== -1);
  assert(source.indexOf("clay.on(clay.EVENTS.AFTER_BUILD") !== -1);
  assert(source.indexOf('checkStatus();') !== -1);
  assert(source.indexOf("'/v1/status'") !== -1);
  assert(source.indexOf('setInterval') !== -1);
});

test('RePebble description contains only user-facing store copy', function() {
  var description = fs.readFileSync(path.join(__dirname, '../store/description.txt'), 'utf8');
  assert.strictEqual(description.indexOf('Required Notice:'), -1);
  assert.strictEqual(description.indexOf('PolyForm'), -1);
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
