'use strict';

var Clay = require('@rebble/clay');
var api = require('./lib/api');
var configPage = require('./lib/config-page');
var localization = require('./lib/localization');
var protocol = require('./lib/protocol');
var settingsStore = require('./lib/settings');
var settingsLocalization = require('./lib/settings-locales.auto');
var appRuntime = require('./lib/app-runtime');

appRuntime.create({
  Pebble: Pebble,
  Clay: Clay,
  api: api,
  configPage: configPage,
  localization: localization,
  protocol: protocol,
  settingsStore: settingsStore,
  settingsLocalization: settingsLocalization,
  getPhoneLocale: function() {
    return typeof navigator !== 'undefined' && navigator.language ? navigator.language : 'en';
  }
}).register();
