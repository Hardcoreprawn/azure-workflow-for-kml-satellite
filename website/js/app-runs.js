/**
 * app-runs.js - Shared run lifecycle helpers.
 *
 * This module holds data-shaping and lifecycle primitives that are reused
 * across app surfaces while keeping UI rendering in app-shell for now.
 */
(function () {
  'use strict';

  function normalizeRun(run) {
    if (!run) return null;
    var normalized = Object.assign({}, run);
    normalized.instanceId = normalized.instanceId || normalized.instance_id || '';
    normalized.submissionId = normalized.submissionId || normalized.submission_id || normalized.instanceId;
    normalized.submittedAt = normalized.submittedAt || normalized.submitted_at || normalized.createdTime || '';
    normalized.submissionPrefix = normalized.submissionPrefix || normalized.submission_prefix || 'analysis';
    normalized.providerName = normalized.providerName || normalized.provider_name || 'planetary_computer';
    normalized.featureCount = normalized.featureCount != null ? normalized.featureCount : normalized.feature_count;
    normalized.aoiCount = normalized.aoiCount != null ? normalized.aoiCount : normalized.aoi_count;
    normalized.processingMode = normalized.processingMode || normalized.processing_mode;
    normalized.maxSpreadKm = normalized.maxSpreadKm != null ? normalized.maxSpreadKm : normalized.max_spread_km;
    normalized.totalAreaHa = normalized.totalAreaHa != null ? normalized.totalAreaHa : normalized.total_area_ha;
    normalized.largestAreaHa = normalized.largestAreaHa != null ? normalized.largestAreaHa : normalized.largest_area_ha;
    normalized.workspaceRole = normalized.workspaceRole || normalized.workspace_role;
    normalized.workspacePreference = normalized.workspacePreference || normalized.workspace_preference;

    if (normalized.output) {
      if (normalized.featureCount == null && normalized.output.featureCount != null) normalized.featureCount = normalized.output.featureCount;
      if (normalized.aoiCount == null && normalized.output.aoiCount != null) normalized.aoiCount = normalized.output.aoiCount;
      if (normalized.artifactCount == null && normalized.output.artifacts) normalized.artifactCount = Object.keys(normalized.output.artifacts).length;
      if (!normalized.partialFailures) {
        normalized.partialFailures = {
          imagery: normalized.output.imageryFailed || 0,
          downloads: normalized.output.downloadsFailed || 0,
          postProcess: normalized.output.postProcessFailed || 0,
        };
      }
    }

    return normalized.instanceId ? normalized : null;
  }

  function historyRunSortValue(run, parseTimestamp) {
    var parser = typeof parseTimestamp === 'function' ? parseTimestamp : function () { return null; };
    return parser((run && (run.submittedAt || run.createdTime || run.lastUpdatedTime)) || '') || 0;
  }

  function sortRuns(runs, parseTimestamp) {
    return (runs || [])
      .map(normalizeRun)
      .filter(Boolean)
      .sort(function (a, b) {
        return historyRunSortValue(b, parseTimestamp) - historyRunSortValue(a, parseTimestamp);
      });
  }

  function isRunActive(run) {
    var runtimeStatus = String((run && run.runtimeStatus) || '').trim().toLowerCase();
    return ['completed', 'failed', 'terminated', 'canceled'].indexOf(runtimeStatus) === -1;
  }

  function mapPhase(customStatus, runtimeStatus, validPhases) {
    if (runtimeStatus === 'Completed') return 'complete';
    if (customStatus && customStatus.phase && Array.isArray(validPhases) && validPhases.indexOf(customStatus.phase) > -1) {
      return customStatus.phase;
    }
    return 'submit';
  }

  function upsertRun(existingRuns, run, parseTimestamp) {
    var normalized = normalizeRun(run);
    if (!normalized) return sortRuns(existingRuns || [], parseTimestamp);

    var replaced = false;
    var nextRuns = (existingRuns || []).map(function (existing) {
      var existingId = existing.instanceId || existing.instance_id;
      if (existingId !== normalized.instanceId) return existing;
      replaced = true;
      return Object.assign({}, existing, normalized);
    });
    if (!replaced) nextRuns.unshift(normalized);
    return sortRuns(nextRuns, parseTimestamp);
  }

  function applyHistoryPayload(payload, options, currentSelectionId, latestRun, locationInstanceId, parseTimestamp) {
    var opts = options || {};
    var normalizedActiveRun = normalizeRun(payload && payload.activeRun);
    var nextRuns = sortRuns(payload && payload.runs, parseTimestamp);

    if (normalizedActiveRun && !nextRuns.some(function (run) { return run.instanceId === normalizedActiveRun.instanceId; })) {
      nextRuns.unshift(normalizedActiveRun);
      nextRuns = sortRuns(nextRuns, parseTimestamp);
    }

    if (opts.preferInstanceId && latestRun &&
        (latestRun.instanceId || latestRun.instance_id) === opts.preferInstanceId &&
        !nextRuns.some(function (run) { return run.instanceId === opts.preferInstanceId; })) {
      var preserved = normalizeRun(latestRun);
      if (preserved) {
        nextRuns.unshift(preserved);
        nextRuns = sortRuns(nextRuns, parseTimestamp);
      }
    }

    var nextSelectedId = opts.preferInstanceId || currentSelectionId || locationInstanceId || '';
    if (nextSelectedId && !nextRuns.some(function (run) { return run.instanceId === nextSelectedId; })) {
      nextSelectedId = '';
    }
    if (!nextSelectedId && normalizedActiveRun) nextSelectedId = normalizedActiveRun.instanceId;
    if (!nextSelectedId && nextRuns[0]) nextSelectedId = nextRuns[0].instanceId;

    return {
      runs: nextRuns,
      selectedId: nextSelectedId || null,
      portfolioSummary: {
        scope: payload && payload.scope,
        orgId: payload && payload.orgId,
        memberCount: payload && payload.memberCount,
        stats: payload && payload.stats
      }
    };
  }

  function readRunSelectionFromLocation() {
    try {
      var params = new URLSearchParams(window.location.search || '');
      return { instanceId: params.get('run') || '' };
    } catch (_) {
      return { instanceId: '' };
    }
  }

  function selectedRunPermalink(instanceId, appBase) {
    try {
      var url = new URL(window.location.href);
      if (instanceId) {
        url.searchParams.set('run', instanceId);
      } else {
        url.searchParams.delete('run');
      }
      url.searchParams.delete('focus');
      var nextPath = url.pathname;
      var nextSearch = url.searchParams.toString();
      return nextSearch ? nextPath + '?' + nextSearch : nextPath;
    } catch (_) {
      return appBase || '/app/';
    }
  }

  function updateRunSelectionLocation(instanceId, appBase) {
    if (!window.history || typeof window.history.replaceState !== 'function') return;
    try {
      window.history.replaceState({}, '', selectedRunPermalink(instanceId, appBase));
    } catch (_) { /* ignore */ }
  }

  window.CanopexAppRuns = {
    normalizeRun: normalizeRun,
    sortRuns: sortRuns,
    isRunActive: isRunActive,
    mapPhase: mapPhase,
    upsertRun: upsertRun,
    applyHistoryPayload: applyHistoryPayload,
    readRunSelectionFromLocation: readRunSelectionFromLocation,
    selectedRunPermalink: selectedRunPermalink,
    updateRunSelectionLocation: updateRunSelectionLocation,
  };
})();
