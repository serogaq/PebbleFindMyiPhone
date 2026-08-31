'use strict';

var jsGlobals = {
  XMLHttpRequest: 'readonly',
  clearInterval: 'readonly',
  console: 'readonly',
  localStorage: 'readonly',
  module: 'readonly',
  navigator: 'readonly',
  Pebble: 'readonly',
  require: 'readonly',
  setInterval: 'readonly',
  setTimeout: 'readonly'
};

var nodeGlobals = {
  __dirname: 'readonly',
  console: 'readonly',
  global: 'readonly',
  module: 'readonly',
  process: 'readonly',
  require: 'readonly'
};

module.exports = [
  {
    files: ['src/pkjs/**/*.js'],
    languageOptions: {
      ecmaVersion: 5,
      sourceType: 'commonjs',
      globals: jsGlobals
    },
    rules: {
      curly: 'error',
      eqeqeq: 'error',
      'no-undef': 'error',
      'no-unused-vars': ['error', {args: 'none', caughtErrors: 'none'}]
    }
  },
  {
    files: ['scripts/**/*.js', 'tests/**/*.js', 'eslint.config.js'],
    languageOptions: {
      ecmaVersion: 5,
      sourceType: 'commonjs',
      globals: nodeGlobals
    },
    rules: {
      curly: 'error',
      eqeqeq: 'error',
      'no-undef': 'error',
      'no-unused-vars': ['error', {args: 'none', caughtErrors: 'none'}]
    }
  }
];
