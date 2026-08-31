'use strict';

var REQUIRED_NOTICE = 'Required Notice: Copyright © serogaq (https://github.com/serogaq/PebbleFindMyiPhone)';
var LICENSE_URL = 'https://polyformproject.org/licenses/noncommercial/1.0.0';

var EN = {
  title: 'Find My iPhone',
  address: 'Backend address:port',
  addressHint: 'Example: find.example.com:443 or 192.168.1.20:8080',
  ssl: 'Use SSL (HTTPS)',
  sslHint: 'Disable only on a trusted local network. HTTP sends the token without encryption.',
  token: 'API token',
  tokenHint: 'Stored only inside the Pebble app on this phone.',
  statusTitle: 'Backend and Apple status',
  notConfigured: 'Enter address, port and token to check status.',
  checking: 'Checking…',
  ready: 'Ready. Apple session and target iPhone are available.',
  unauthorized: 'Backend token is incorrect.',
  reauth: 'Apple authorization must be renewed on the server.',
  target: 'The configured target iPhone was not found.',
  unavailable: 'Backend is unavailable or the request timed out.',
  appleError: 'Apple rejected or failed the request.',
  invalid: 'Address must be host:port. Scheme and path are not allowed.',
  retry: 'Check again',
  save: 'Save',
  aboutTitle: 'About',
  requiredNotice: REQUIRED_NOTICE,
  license: 'Licensed under PolyForm Noncommercial 1.0.0. ' + LICENSE_URL
};

var RU = {
  title: 'Найти iPhone',
  address: 'Адрес backend:port',
  addressHint: 'Например: find.example.com:443 или 192.168.1.20:8080',
  ssl: 'Использовать SSL (HTTPS)',
  sslHint: 'Отключайте только в доверенной локальной сети. HTTP передаёт токен без шифрования.',
  token: 'API-токен',
  tokenHint: 'Хранится только внутри приложения Pebble на этом телефоне.',
  statusTitle: 'Состояние backend и Apple',
  notConfigured: 'Введите адрес, порт и токен для проверки.',
  checking: 'Проверяем…',
  ready: 'Готово. Apple-сессия и целевой iPhone доступны.',
  unauthorized: 'Неверный токен backend.',
  reauth: 'Нужно обновить Apple-авторизацию на сервере.',
  target: 'Настроенный iPhone не найден.',
  unavailable: 'Backend недоступен или истёк таймаут.',
  appleError: 'Apple отклонил запрос или вернул ошибку.',
  invalid: 'Адрес должен иметь вид host:port, без scheme и path.',
  retry: 'Проверить снова',
  save: 'Сохранить',
  aboutTitle: 'О приложении',
  requiredNotice: REQUIRED_NOTICE,
  license: 'Лицензия PolyForm Noncommercial 1.0.0. ' + LICENSE_URL
};

function stringsForWatch(info) {
  var language = info && info.language ? String(info.language).toLowerCase() : 'en';
  return language.indexOf('ru') === 0 ? RU : EN;
}

function buildConfig(s) {
  return [
    {type: 'heading', defaultValue: s.title},
    {
      type: 'input', id: 'address', messageKey: 'CONFIG_ADDRESS', label: s.address,
      description: s.addressHint,
      attributes: {
        placeholder: 'host:port', autocapitalize: 'none', autocorrect: 'off', required: true
      }
    },
    {
      type: 'toggle', id: 'ssl', messageKey: 'CONFIG_SSL', label: s.ssl,
      description: s.sslHint, defaultValue: true
    },
    {
      type: 'input', id: 'token', messageKey: 'CONFIG_TOKEN', label: s.token,
      description: s.tokenHint,
      attributes: {
        type: 'password', placeholder: 'Bearer token', autocapitalize: 'none',
        autocorrect: 'off', required: true
      }
    },
    {type: 'heading', defaultValue: s.statusTitle},
    {type: 'text', id: 'status', defaultValue: s.notConfigured},
    {type: 'button', id: 'retry', defaultValue: s.retry},
    {type: 'heading', defaultValue: s.aboutTitle},
    {type: 'text', id: 'requiredNotice', defaultValue: s.requiredNotice},
    {type: 'text', id: 'license', defaultValue: s.license},
    {type: 'submit', defaultValue: s.save}
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
      return strings.appleError;
    }
    return strings.unavailable;
  }

  function checkStatus() {
    stopLoader();
    var address = String(clay.getItemById('address').get() || '').trim();
    var token = String(clay.getItemById('token').get() || '');
    var ssl = !!clay.getItemById('ssl').get();
    if (!address || !token) {
      setStatus(strings.notConfigured);
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
  EN: EN,
  RU: RU,
  stringsForWatch: stringsForWatch,
  buildConfig: buildConfig,
  customClay: customClay
};
