/**
 * app-core-state.js - Shared state helpers for app modules.
 *
 * This is the initial Slice 1 foundation: simple in-memory state and
 * localStorage-backed preference helpers.
 */
(function () {
  'use strict';

  var state = {
    workspaceRole: 'conservation',
    workspacePreference: 'investigate',
  };

  function get(key) {
    return state[key];
  }

  function set(key, value) {
    state[key] = value;
    return value;
  }

  function readStoredValue(key) {
    try {
      return localStorage.getItem(key);
    } catch (_) {
      return null;
    }
  }

  function storeValue(key, value) {
    try {
      localStorage.setItem(key, value);
      return true;
    } catch (_) {
      return false;
    }
  }

  window.CanopexCoreState = {
    get: get,
    set: set,
    readStoredValue: readStoredValue,
    storeValue: storeValue,
  };
})();
