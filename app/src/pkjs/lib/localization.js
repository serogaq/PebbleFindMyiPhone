'use strict';

function normalizeLocale(value) {
  return String(value || '').trim().replace(/_/g, '-').toLowerCase();
}

function resolve(catalogs, requestedLocale) {
  var locale = normalizeLocale(requestedLocale);
  while (locale) {
    if (Object.prototype.hasOwnProperty.call(catalogs, locale)) {
      return catalogs[locale];
    }
    var separator = locale.lastIndexOf('-');
    if (separator === -1) {
      break;
    }
    locale = locale.slice(0, separator);
  }
  return catalogs.en;
}

module.exports = {
  normalizeLocale: normalizeLocale,
  resolve: resolve
};
