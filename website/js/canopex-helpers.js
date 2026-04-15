/**
 * canopex-helpers.js — Pure formatting and display helpers.
 *
 * Extracted from app-shell.js. No DOM mutation, no auth, no side effects.
 * Exposes window.CanopexHelpers for consumption by app-shell.js.
 */
(function () {
  'use strict';

  function displayAnalysisPhase(customStatus, runtimeStatus) {
    if (runtimeStatus === 'Completed') return 'complete';
    return (customStatus && customStatus.phase) || 'queued';
  }

  function parseStatusTimestamp(value) {
    if (!value) return null;
    var normalized = String(value).replace(' ', 'T');
    var parsed = Date.parse(normalized);
    return Number.isNaN(parsed) ? null : parsed;
  }

  function formatRelativeDuration(ms) {
    if (ms == null || ms < 0) return null;
    var totalSeconds = Math.round(ms / 1000);
    if (totalSeconds < 60) return totalSeconds + 's';
    var minutes = Math.floor(totalSeconds / 60);
    var seconds = totalSeconds % 60;
    if (minutes < 60) return minutes + 'm' + (seconds >= 5 ? ' ' + seconds + 's' : '');
    var hours = Math.floor(minutes / 60);
    var remainingMinutes = minutes % 60;
    return hours + 'h' + (remainingMinutes ? ' ' + remainingMinutes + 'm' : '');
  }

  function summarizeRunTiming(data) {
    var createdMs = parseStatusTimestamp(data && data.createdTime);
    var updatedMs = parseStatusTimestamp(data && data.lastUpdatedTime);
    var now = Date.now();
    return {
      elapsed: createdMs ? formatRelativeDuration(now - createdMs) : null,
      sinceUpdate: updatedMs ? formatRelativeDuration(now - updatedMs) : null,
      stale: updatedMs ? (now - updatedMs) >= 90000 : false,
    };
  }

  function capabilityHeadline(caps) {
    var parts = [];
    if (caps.ai_insights) parts.push('AI insights');
    if (caps.api_access) parts.push('API ready');
    if (caps.concurrency && caps.concurrency > 1) parts.push(String(caps.concurrency) + ' concurrent runs');
    if (!parts.length) return 'Core analysis workspace';
    return parts.slice(0, 2).join(' + ');
  }

  function shortInstanceId(instanceId) {
    var value = String(instanceId || 'pending');
    return value.length > 8 ? value.slice(0, 8) : value;
  }

  function formatHistoryTimestamp(value) {
    var parsed = parseStatusTimestamp(value);
    if (parsed == null) return 'Time unavailable';
    return new Date(parsed).toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit'
    });
  }

  function formatCountLabel(count, singular, plural) {
    if (count == null || isNaN(count)) return null;
    var whole = Number(count);
    var noun = whole === 1 ? singular : (plural || singular + 's');
    return whole + ' ' + noun;
  }

  function providerLabel(providerName) {
    if (!providerName) return null;
    if (providerName === 'planetary_computer') return 'Planetary Computer';
    return String(providerName).replace(/_/g, ' ');
  }

  function summarizeFailureCounts(partialFailures) {
    if (!partialFailures) return null;
    var parts = [];
    if (partialFailures.imagery) parts.push(partialFailures.imagery + ' imagery');
    if (partialFailures.downloads) parts.push(partialFailures.downloads + ' download');
    if (partialFailures.postProcess) parts.push(partialFailures.postProcess + ' post-process');
    if (!parts.length) return null;
    return 'Failures: ' + parts.join(', ');
  }

  function parseDownloadFilename(response, fallbackName) {
    var disposition = response && response.headers ? response.headers.get('Content-Disposition') : '';
    var match = disposition && disposition.match(/filename="?([^";]+)"?/i);
    return match && match[1] ? match[1] : fallbackName;
  }

  function createStatEl(label, value, tone) {
    let cls;
    if (tone === 'positive') cls = ' positive';
    else if (tone === 'negative') cls = ' negative';
    else cls = ' neutral';
    const div = document.createElement('div');
    div.className = 'app-evidence-stat';
    const span = document.createElement('span');
    span.textContent = label;
    const strong = document.createElement('strong');
    strong.className = cls;
    strong.textContent = value;
    div.appendChild(span);
    div.appendChild(strong);
    return div;
  }

  function setStatGrid(grid, stats) {
    grid.textContent = '';
    stats.forEach(function (s) { grid.appendChild(createStatEl(s[0], s[1], s[2])); });
  }

  function createCallout(tone, message) {
    var div = document.createElement('div');
    div.className = 'app-callout';
    div.setAttribute('data-tone', tone);
    div.textContent = message;
    return div;
  }

  function formatRetention(days) {
    if (days == null) return 'Custom';
    if (days === 365) return '1 year';
    return String(days) + ' days';
  }

  window.CanopexHelpers = {
    displayAnalysisPhase: displayAnalysisPhase,
    parseStatusTimestamp: parseStatusTimestamp,
    formatRelativeDuration: formatRelativeDuration,
    summarizeRunTiming: summarizeRunTiming,
    capabilityHeadline: capabilityHeadline,
    shortInstanceId: shortInstanceId,
    formatHistoryTimestamp: formatHistoryTimestamp,
    formatCountLabel: formatCountLabel,
    providerLabel: providerLabel,
    summarizeFailureCounts: summarizeFailureCounts,
    parseDownloadFilename: parseDownloadFilename,
    createStatEl: createStatEl,
    setStatGrid: setStatGrid,
    createCallout: createCallout,
    formatRetention: formatRetention,
  };
})();
