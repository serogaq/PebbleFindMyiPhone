'use strict';

function create(options) {
  var Pebble = options.Pebble;
  var Clay = options.Clay;
  var api = options.api;
  var configPage = options.configPage;
  var localization = options.localization;
  var protocol = options.protocol;
  var settingsStore = options.settingsStore;
  var settingsLocalization = options.settingsLocalization;
  var getPhoneLocale = options.getPhoneLocale;
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

  function onAppMessage(event) {
    var payload = event && event.payload ? event.payload : {};
    var requestKind = Number(payload.REQUEST_KIND || 0);
    var sequence = Number(payload.REQUEST_SEQ || 0);
    var storedSettings = settingsStore.load();
    var validation = settingsStore.validate(storedSettings);

    if (!validation.ok) {
      sendResponse(requestKind, sequence, {
        code: validation.missing ? protocol.RESULT.CONFIG_MISSING : protocol.RESULT.CONFIG_INVALID
      });
      return;
    }

    if (requestKind === protocol.REQUEST.CHECK_STATUS) {
      api.checkStatus(storedSettings, function(result) {
        sendResponse(requestKind, sequence, result);
      });
    } else if (requestKind === protocol.REQUEST.PLAY_SOUND) {
      api.playSound(storedSettings, function(result) {
        sendResponse(requestKind, sequence, result);
      });
    } else {
      sendResponse(requestKind, sequence, {code: protocol.RESULT.API_ERROR});
    }
  }

  function onShowConfiguration() {
    var strings = localization.resolve(settingsLocalization.locales, getPhoneLocale());
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
    // Manual event handling constructs Clay after Pebble's ready event. Ensure
    // customClay receives its metadata before generateUrl() serializes the page.
    activeClay.meta.userData = userData;
    activeClay.setSettings(settingsStore.toClay(settingsStore.load()));
    Pebble.openURL(activeClay.generateUrl());
  }

  function onWebviewClosed(event) {
    if (!activeClay || !event || !event.response) {
      activeClay = null;
      return;
    }
    var storedSettings = settingsStore.fromClay(activeClay.getSettings(event.response, false));
    if (settingsStore.validate(storedSettings).ok) {
      settingsStore.save(storedSettings);
      console.log('Backend settings saved');
    } else {
      console.log('Rejected invalid backend settings');
    }
    activeClay = null;
  }

  function register() {
    Pebble.addEventListener('ready', function() {
      console.log('Find My iPhone PKJS ready');
    });
    Pebble.addEventListener('appmessage', onAppMessage);
    Pebble.addEventListener('showConfiguration', onShowConfiguration);
    Pebble.addEventListener('webviewclosed', onWebviewClosed);
  }

  return {register: register};
}

module.exports = {create: create};
