'use strict';

var STORAGE_KEY = 'find-my-iphone.settings.v1';
var ADDRESS_PATTERN = /^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?|\[[0-9A-Fa-f:.]+\]):([0-9]{1,5})$/;
var ADDRESS_PATTERN_SOURCE = ADDRESS_PATTERN.source;

function empty() {
  return {address: '', ssl: true, token: ''};
}

function normalize(raw) {
  raw = raw || {};
  return {
    address: typeof raw.address === 'string' ? raw.address.trim() : '',
    ssl: raw.ssl === false || raw.ssl === 0 || raw.ssl === '0' ? false : true,
    token: typeof raw.token === 'string' ? raw.token : ''
  };
}

function validate(raw) {
  var settings = normalize(raw);
  if (!settings.address || !settings.token) {
    return {ok: false, missing: true, reason: 'missing'};
  }
  if (settings.address.indexOf('://') !== -1 || /[/?#\s]/.test(settings.address)) {
    return {ok: false, missing: false, reason: 'format'};
  }
  var match = ADDRESS_PATTERN.exec(settings.address);
  if (!match) {
    return {ok: false, missing: false, reason: 'format'};
  }
  var port = Number(match[1]);
  if (port < 1 || port > 65535) {
    return {ok: false, missing: false, reason: 'port'};
  }
  return {ok: true, missing: false, settings: settings};
}

function load() {
  try {
    var stored = localStorage.getItem(STORAGE_KEY);
    return stored ? normalize(JSON.parse(stored)) : empty();
  } catch (_error) {
    return empty();
  }
}

function save(settings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(normalize(settings)));
}

function clayValue(values, key) {
  var value = values ? values[key] : undefined;
  if (value && typeof value === 'object' && Object.prototype.hasOwnProperty.call(value, 'value')) {
    return value.value;
  }
  return value;
}

function fromClay(values) {
  return normalize({
    address: clayValue(values, 'CONFIG_ADDRESS'),
    ssl: clayValue(values, 'CONFIG_SSL'),
    token: clayValue(values, 'CONFIG_TOKEN')
  });
}

function toClay(settings) {
  settings = normalize(settings);
  return {
    CONFIG_ADDRESS: settings.address,
    CONFIG_SSL: settings.ssl,
    CONFIG_TOKEN: settings.token
  };
}

function baseUrl(settings) {
  var valid = validate(settings);
  return valid.ok ? (valid.settings.ssl ? 'https://' : 'http://') + valid.settings.address : null;
}

module.exports = {
  STORAGE_KEY: STORAGE_KEY,
  ADDRESS_PATTERN_SOURCE: ADDRESS_PATTERN_SOURCE,
  empty: empty,
  normalize: normalize,
  validate: validate,
  load: load,
  save: save,
  fromClay: fromClay,
  toClay: toClay,
  baseUrl: baseUrl
};
