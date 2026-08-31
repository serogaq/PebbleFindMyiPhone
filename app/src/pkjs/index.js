'use strict';

var Clay = require('@rebble/clay');
var api = require('./lib/api');
var configPage = require('./lib/config-page');
var localization = require('./lib/localization');
var protocol = require('./lib/protocol');
var settingsStore = require('./lib/settings');
var settingsLocalization = require('./lib/settings-locales.auto');

var activeClay = null;

function sendResponse(requestKind, sequence, result) {
  var message = {};
  message.RESPONSE_KIND = requestKind;
  message.REQUEST_SEQ = sequence;
  message.RESULT_CODE = result.code;

  Pebble.sendAppMessage(message, function() {
    console.log('Response delivered kind=' + requestKind + ' code=' + result.code);
  }, function() {
    console.log('Response delivery failed kind=' + requestKind + ' code=' + result.code);
  });
}

Pebble.addEventListener('ready', function() {
  console.log('Find My iPhone PKJS ready');
});

Pebble.addEventListener('appmessage', function(event) {
  var payload = event && event.payload ? event.payload : {};
  var requestKind = Number(payload.REQUEST_KIND || 0);
  var sequence = Number(payload.REQUEST_SEQ || 0);
  var settings = settingsStore.load();
  var validation = settingsStore.validate(settings);

  if (!validation.ok) {
    sendResponse(requestKind, sequence, {
      code: validation.missing ? protocol.RESULT.CONFIG_MISSING : protocol.RESULT.CONFIG_INVALID
    });
    return;
  }

  if (requestKind === protocol.REQUEST.CHECK_STATUS) {
    api.checkStatus(settings, function(result) {
      sendResponse(requestKind, sequence, result);
    });
  } else if (requestKind === protocol.REQUEST.PLAY_SOUND) {
    api.playSound(settings, function(result) {
      sendResponse(requestKind, sequence, result);
    });
  } else {
    sendResponse(requestKind, sequence, {code: protocol.RESULT.API_ERROR});
  }
});

Pebble.addEventListener('showConfiguration', function() {
  var phoneLocale = typeof navigator !== 'undefined' && navigator.language ?
    navigator.language : 'en';
  var strings = localization.resolve(settingsLocalization.locales, phoneLocale);
  var userData = {
    strings: strings,
    addressPattern: settingsStore.ADDRESS_PATTERN_SOURCE
  };
  activeClay = new Clay(
    configPage.buildConfig(strings, settingsLocalization.build),
    configPage.customClay,
    {
      autoHandleEvents: false,
      userData: userData
    });
  // With manual event handling Clay is constructed after Pebble's `ready`
  // event, so its deferred metadata population will not run for this instance.
  // Populate the data consumed by customClay before generateUrl() serializes it.
  activeClay.meta.userData = userData;
  activeClay.setSettings(settingsStore.toClay(settingsStore.load()));
  Pebble.openURL(activeClay.generateUrl());
});

Pebble.addEventListener('webviewclosed', function(event) {
  if (!activeClay || !event || !event.response) {
    activeClay = null;
    return;
  }
  var settings = settingsStore.fromClay(activeClay.getSettings(event.response, false));
  if (settingsStore.validate(settings).ok) {
    settingsStore.save(settings);
    console.log('Backend settings saved');
  } else {
    console.log('Rejected invalid backend settings');
  }
  activeClay = null;
});
