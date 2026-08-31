'use strict';

var protocol = require('./protocol');
var settingsStore = require('./settings');

function parseJson(text) {
  try {
    return text ? JSON.parse(text) : {};
  } catch (_error) {
    return {};
  }
}

function resultForResponse(status, body) {
  var error = body && body.error ? body.error : {};
  var code = error.code || '';
  var mapped = protocol.RESULT.API_ERROR;

  if (status === 401 || code === 'api.unauthorized') {
    mapped = protocol.RESULT.API_UNAUTHORIZED;
  } else if (code === 'icloud.authentication_required') {
    mapped = protocol.RESULT.APPLE_AUTH_REQUIRED;
  } else if (code === 'target.not_found') {
    mapped = protocol.RESULT.TARGET_NOT_FOUND;
  } else if (code === 'target.sound_unavailable') {
    mapped = protocol.RESULT.SOUND_UNAVAILABLE;
  } else if (code === 'api.rate_limited') {
    mapped = protocol.RESULT.RATE_LIMITED;
  } else if (code === 'icloud.device_lookup_failed') {
    mapped = protocol.RESULT.DEVICE_LOOKUP_FAILED;
  } else if (code === 'icloud.command_outcome_unknown') {
    mapped = protocol.RESULT.OUTCOME_UNKNOWN;
  } else if (code === 'icloud.request_failed') {
    mapped = protocol.RESULT.APPLE_REQUEST_FAILED;
  }

  return {
    code: mapped,
    httpStatus: status,
    retryable: error.retryable === true,
    commandDispatched: error.command_dispatched === true || error.command_may_have_been_dispatched === true,
    backendCode: code
  };
}

function createIdempotencyKey() {
  var random = Math.floor(Math.random() * 0x100000000).toString(16);
  return 'pebble-' + Date.now().toString(36) + '-' + ('00000000' + random).slice(-8);
}

function xhrRequest(options, callback) {
  var request = new XMLHttpRequest();
  var completed = false;

  function finish(result) {
    if (!completed) {
      completed = true;
      callback(result);
    }
  }

  try {
    request.open(options.method, options.url, true);
    request.timeout = options.timeout;
    if (options.token) {
      request.setRequestHeader('Authorization', 'Bearer ' + options.token);
    }
    if (options.idempotencyKey) {
      request.setRequestHeader('Idempotency-Key', options.idempotencyKey);
    }
    request.onreadystatechange = function() {
      if (request.readyState === 4) {
        if (request.status === 0) {
          finish({transportError: true, status: 0, body: {}});
        } else {
          finish({transportError: false, status: request.status, body: parseJson(request.responseText)});
        }
      }
    };
    request.onerror = function() {
      finish({transportError: true, status: 0, body: {}});
    };
    request.ontimeout = request.onerror;
    request.onabort = request.onerror;
    request.send(null);
  } catch (_error) {
    finish({transportError: true, status: 0, body: {}});
  }
}

function checkStatus(settings, callback) {
  var baseUrl = settingsStore.baseUrl(settings);
  if (!baseUrl) {
    callback({code: protocol.RESULT.CONFIG_INVALID});
    return;
  }
  xhrRequest({
    method: 'GET',
    url: baseUrl + '/v1/status',
    token: settings.token,
    timeout: 8000
  }, function(response) {
    if (!response.transportError && response.status === 200 && response.body.state === 'ready') {
      callback({code: protocol.RESULT.OK, httpStatus: 200});
    } else if (response.transportError) {
      callback({code: protocol.RESULT.BACKEND_UNAVAILABLE, httpStatus: response.status});
    } else {
      callback(resultForResponse(response.status, response.body));
    }
  });
}

function playSound(settings, callback) {
  var baseUrl = settingsStore.baseUrl(settings);
  if (!baseUrl) {
    callback({code: protocol.RESULT.CONFIG_INVALID});
    return;
  }

  var idempotencyKey = createIdempotencyKey();
  var attempts = 0;
  function attempt() {
    attempts += 1;
    xhrRequest({
      method: 'POST',
      url: baseUrl + '/v1/find-my/play-sound',
      token: settings.token,
      idempotencyKey: idempotencyKey,
      timeout: 20000
    }, function(response) {
      if (response.transportError) {
        callback({code: protocol.RESULT.OUTCOME_UNKNOWN, commandDispatched: true});
        return;
      }
      if (response.status === 202 && response.body.status === 'submitted') {
        callback({code: protocol.RESULT.OK, httpStatus: 202, commandDispatched: true});
        return;
      }
      var result = resultForResponse(response.status, response.body);
      if (result.backendCode === 'icloud.device_lookup_failed' && result.retryable &&
          !result.commandDispatched && attempts === 1) {
        setTimeout(attempt, 750);
      } else {
        callback(result);
      }
    });
  }
  attempt();
}

module.exports = {
  parseJson: parseJson,
  resultForResponse: resultForResponse,
  createIdempotencyKey: createIdempotencyKey,
  xhrRequest: xhrRequest,
  checkStatus: checkStatus,
  playSound: playSound
};
