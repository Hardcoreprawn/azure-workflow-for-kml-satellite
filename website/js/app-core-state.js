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

  function scopedCacheKey(prefix, userId, key) {
    if (!prefix || !userId || !key) return null;
    return prefix + userId + ':' + key;
  }

  function readScopedCache(prefix, userId, key) {
    try {
      var full = scopedCacheKey(prefix, userId, key);
      if (!full) return null;
      var raw = localStorage.getItem(full);
      if (!raw) return null;
      var entry = JSON.parse(raw);
      if (!entry || typeof entry.expires !== 'number' || Date.now() > entry.expires) {
        localStorage.removeItem(full);
        return null;
      }
      return entry.data;
    } catch (_) {
      return null;
    }
  }

  function writeScopedCache(prefix, userId, key, data, ttlMs) {
    if (!Number.isFinite(ttlMs)) return false;
    try {
      var full = scopedCacheKey(prefix, userId, key);
      if (!full) return false;
      localStorage.setItem(full, JSON.stringify({ data: data, expires: Date.now() + ttlMs }));
      return true;
    } catch (_) {
      return false;
    }
  }

  function clearScopedCacheKey(prefix, userId, key) {
    try {
      var full = scopedCacheKey(prefix, userId, key);
      if (full) localStorage.removeItem(full);
      return true;
    } catch (_) {
      return false;
    }
  }

  function clearAllScopedCache(prefix) {
    try {
      var keys = [];
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (k && k.indexOf(prefix) === 0) keys.push(k);
      }
      keys.forEach(function (k) { localStorage.removeItem(k); });
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
    readScopedCache: readScopedCache,
    writeScopedCache: writeScopedCache,
    clearScopedCacheKey: clearScopedCacheKey,
    clearAllScopedCache: clearAllScopedCache,
  };
})();
