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

  function setAnalysisStatus(message, tone) {
    var status = getById('app-analysis-status');
    if (!status) return;
    if (!message) {
      status.hidden = true;
      status.textContent = '';
      status.removeAttribute('data-tone');
      return;
    }
    status.hidden = false;
    status.textContent = message;
    status.setAttribute('data-tone', tone || 'info');
  }

  function setHeroRunSummary(title, note) {
    var titleEl = getById('app-hero-active-run');
    var noteEl = getById('app-hero-active-run-note');
    if (!titleEl || !noteEl) return;
    titleEl.textContent = title || 'Ready to queue';
    noteEl.textContent = note || 'Ready to run an analysis.';
  }

  window.CanopexCoreDom = {
    getById: getById,
    setText: setText,
    bindClick: bindClick,
    bindInput: bindInput,
    setAnalysisStatus: setAnalysisStatus,
    setHeroRunSummary: setHeroRunSummary,
  };
})();
