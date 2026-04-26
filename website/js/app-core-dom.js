/**
 * app-core-dom.js - Shared DOM helpers for app modules.
 *
 * Keep these helpers tiny and null-safe so module code can focus on
 * behavior instead of repetitive element guards.
 */
(function () {
  'use strict';

  function getById(id) {
    return document.getElementById(id);
  }

  function setText(id, value) {
    var el = getById(id);
    if (el) el.textContent = value;
  }

  function bindClick(id, handler) {
    var el = getById(id);
    if (!el) return false;
    el.addEventListener('click', handler);
    return true;
  }

  function bindInput(id, handler) {
    var el = getById(id);
    if (!el) return false;
    el.addEventListener('input', handler);
    return true;
  }

  window.CanopexCoreDom = {
    getById: getById,
    setText: setText,
    bindClick: bindClick,
    bindInput: bindInput,
  };
})();
