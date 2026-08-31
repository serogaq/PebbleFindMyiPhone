'use strict';

function buildConfig(s, buildInfo) {
  return [
    {type: 'heading', defaultValue: s.title},
    {
      type: 'input', id: 'address', messageKey: 'CONFIG_ADDRESS', label: s.address,
      description: s.address_hint,
      attributes: {
        placeholder: s.address_placeholder, autocapitalize: 'none', autocorrect: 'off',
        required: true
      }
    },
    {
      type: 'toggle', id: 'ssl', messageKey: 'CONFIG_SSL', label: s.ssl,
      description: s.ssl_hint, defaultValue: true
    },
    {
      type: 'input', id: 'token', messageKey: 'CONFIG_TOKEN', label: s.token,
      description: s.token_hint,
      attributes: {
        type: 'password', placeholder: s.token_placeholder, autocapitalize: 'none',
        autocorrect: 'off', required: true
      }
    },
    {type: 'submit', defaultValue: s.save},
    {type: 'heading', defaultValue: s.status_title},
    {type: 'text', id: 'status', defaultValue: s.not_configured},
    {type: 'button', id: 'retry', defaultValue: s.retry},
    {type: 'heading', defaultValue: s.about_title},
    {type: 'text', id: 'requiredNotice', defaultValue: s.required_notice},
    {type: 'text', id: 'license', defaultValue: s.license},
    {type: 'text', id: 'version', defaultValue: s.version_label + ': ' + buildInfo.version},
    {type: 'text', id: 'commit', defaultValue: s.commit_label + ': ' + buildInfo.commit}
  ];
}

// This function is serialized into the generated Clay data: page. Keep every
// dependency inside the function body: require() and outer variables are absent.
function customClay(minified) {
  var clay = this;
  var metadata = clay.meta.userData;
  var strings = metadata.strings;
  var addressPattern = new RegExp(metadata.addressPattern);
  var timer = null;

  function validAddress(address) {
    if (!address || address.indexOf('://') !== -1 || /[/?#\s]/.test(address)) {
      return false;
    }
    var match = addressPattern.exec(address);
    return !!match && Number(match[1]) >= 1 && Number(match[1]) <= 65535;
  }

  function setStatus(text) {
    clay.getItemById('status').set(text);
  }

  function stopLoader() {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
  }

  function startLoader() {
    var dots = 0;
    setStatus(strings.checking);
    timer = setInterval(function() {
      dots = (dots + 1) % 4;
      setStatus(strings.checking + new Array(dots + 1).join('.'));
    }, 350);
  }

  function statusText(status, body) {
    var code = body && body.error ? body.error.code : '';
    if (status === 200 && body.state === 'ready') {
      return strings.ready;
    }
    if (status === 401 || code === 'api.unauthorized') {
      return strings.unauthorized;
    }
    if (code === 'icloud.authentication_required') {
      return strings.reauth;
    }
    if (code === 'target.not_found') {
      return strings.target;
    }
    if (code === 'icloud.request_failed' || code === 'icloud.device_lookup_failed') {
      return strings.apple_error;
    }
    return strings.unavailable;
  }

  function checkStatus() {
    stopLoader();
    var address = String(clay.getItemById('address').get() || '').trim();
    var token = String(clay.getItemById('token').get() || '');
    var ssl = !!clay.getItemById('ssl').get();
    if (!address || !token) {
      setStatus(strings.not_configured);
      return;
    }
    if (!validAddress(address)) {
      setStatus(strings.invalid);
      return;
    }

    startLoader();
    var xhr = new XMLHttpRequest();
    var completed = false;
    function finish(text) {
      if (completed) {
        return;
      }
      completed = true;
      stopLoader();
      setStatus(text);
    }
    try {
      xhr.open('GET', (ssl ? 'https://' : 'http://') + address + '/v1/status', true);
      xhr.timeout = 8000;
      xhr.setRequestHeader('Authorization', 'Bearer ' + token);
      xhr.onreadystatechange = function() {
        if (xhr.readyState !== 4) {
          return;
        }
        var body = {};
        try { body = JSON.parse(xhr.responseText || '{}'); } catch (_error) {}
        finish(statusText(xhr.status, body));
      };
      xhr.onerror = function() { finish(strings.unavailable); };
      xhr.ontimeout = xhr.onerror;
      xhr.send(null);
    } catch (_error) {
      finish(strings.unavailable);
    }
  }

  clay.on(clay.EVENTS.AFTER_BUILD, function() {
    clay.getItemById('retry').on('click', checkStatus);
    checkStatus();
  });
}

module.exports = {
  buildConfig: buildConfig,
  customClay: customClay
};
