/**
 * app-run-lifecycle.js
 *
 * Analysis run queue, poll, display, and export.
 * Extracted from app-shell.js. Covers:
 *   - updateContentSummary  — phase-aware content panel wording
 *   - updateRunDetail       — run metadata display (scope, delivery, link)
 *   - downloadRunExport     — GeoJSON/CSV/PDF export trigger
 *   - updateAnalysisRun     — master run view update (owns latestAnalysisRun)
 *   - applyFirstRunLayout   — first-run vs returning user hero layout
 *   - stopAnalysisPolling   — cancel active poll
 *   - pollAnalysisRun       — 3 s poll loop with generation guard
 *   - queueAnalysis         — full submission flow (token → upload → track)
 *
 * Exposes window.CanopexRunLifecycle = {
 *   init, updateContentSummary, updateRunDetail, downloadRunExport,
 *   updateAnalysisRun, applyFirstRunLayout, stopAnalysisPolling,
 *   pollAnalysisRun, queueAnalysis, getLatestRun
 * }
 */
(function () {
  'use strict';

  // ── Internal state ────────────────────────────────────────────
  var latestAnalysisRun = null;
  var activeAnalysisPoll = null;
  var analysisPollGeneration = 0; // incremented on each pollAnalysisRun call to detect stale callbacks

  // ── Injected deps ─────────────────────────────────────────────
  var _d = {};

  function init(deps) {
    _d = deps || {};
  }

  // ── Helpers (reads from canopex-helpers / canopex-geo globals) ──

  function _helpers() { return window.CanopexHelpers || {}; }
  function _geo() { return window.CanopexGeo || {}; }

  function _displayAnalysisPhase(cs, rs) {
    var h = _helpers();
    return typeof h.displayAnalysisPhase === 'function' ? h.displayAnalysisPhase(cs, rs) : (rs || 'Pending');
  }
  function _summarizeRunTiming(data) {
    var h = _helpers();
    return typeof h.summarizeRunTiming === 'function' ? h.summarizeRunTiming(data) : {};
  }
  function _parseDownloadFilename(res, fallback) {
    var h = _helpers();
    return typeof h.parseDownloadFilename === 'function' ? h.parseDownloadFilename(res, fallback) : fallback;
  }
  function _formatHistoryTimestamp(v) {
    var h = _helpers();
    return typeof h.formatHistoryTimestamp === 'function' ? h.formatHistoryTimestamp(v) : String(v || '\u2014');
  }
  function _formatCountLabel(n, s, p) {
    var h = _helpers();
    return typeof h.formatCountLabel === 'function' ? h.formatCountLabel(n, s, p) : null;
  }
  function _providerLabel(name) {
    var h = _helpers();
    return typeof h.providerLabel === 'function' ? h.providerLabel(name) : null;
  }
  function _summarizeFailureCounts(pf) {
    var h = _helpers();
    return typeof h.summarizeFailureCounts === 'function' ? h.summarizeFailureCounts(pf) : null;
  }
  function _formatDistance(km) {
    var g = _geo();
    return typeof g.formatDistance === 'function' ? g.formatDistance(km) : km + ' km';
  }
  function _formatHectares(ha) {
    var g = _geo();
    return typeof g.formatHectares === 'function' ? g.formatHectares(ha) : ha + ' ha';
  }
  function _parseKmlText(text) {
    var g = _geo();
    return typeof g.parseKmlText === 'function' ? g.parseKmlText(text) : text;
  }

  // ── Public accessors ──────────────────────────────────────────

  function getLatestRun() { return latestAnalysisRun; }

  function upsertHistoryRun(run) {
    if (!_d.getAnalysisHistoryRuns || !_d.setAnalysisHistoryRuns || !_d.renderAnalysisHistoryList) return;
    var appRuns = window.CanopexAppRuns || {};
    if (typeof appRuns.upsertRun !== 'function') return;
    var helpers = window.CanopexHelpers || {};
    var parseTimestamp = typeof helpers.parseStatusTimestamp === 'function'
      ? helpers.parseStatusTimestamp
      : function (value) { return value; };
    var nextRuns = appRuns.upsertRun(_d.getAnalysisHistoryRuns(), run, parseTimestamp);
    _d.setAnalysisHistoryRuns(nextRuns);
    _d.renderAnalysisHistoryList();
    if (_d.applyFirstRunLayout) _d.applyFirstRunLayout();
  }

  // ── updateContentSummary ──────────────────────────────────────

  function updateContentSummary(data) {
    var role = _d.getCurrentRoleConfig ? _d.getCurrentRoleConfig() : {};
    var imageryEl = document.getElementById('app-content-imagery');
    var imageryNoteEl = document.getElementById('app-content-imagery-note');
    var enrichmentEl = document.getElementById('app-content-enrichment');
    var enrichmentNoteEl = document.getElementById('app-content-enrichment-note');
    var exportsEl = document.getElementById('app-content-exports');
    var exportsNoteEl = document.getElementById('app-content-exports-note');
    if (!imageryEl || !imageryNoteEl || !enrichmentEl || !enrichmentNoteEl || !exportsEl || !exportsNoteEl) return;

    var emptyContent = (role && role.emptyContent) || {};
    if (!data) {
      if (_d.showEvidenceSurface) _d.showEvidenceSurface(false);
      imageryEl.textContent = emptyContent.imageryTitle || 'Imagery';
      imageryNoteEl.textContent = emptyContent.imageryNote || '';
      enrichmentEl.textContent = emptyContent.enrichmentTitle || 'Enrichment';
      enrichmentNoteEl.textContent = emptyContent.enrichmentNote || '';
      exportsEl.textContent = emptyContent.exportsTitle || 'Exports';
      exportsNoteEl.textContent = emptyContent.exportsNote || '';
      return;
    }

    var runtimeStatus = data.runtimeStatus || 'Pending';
    var phase = (data.customStatus && data.customStatus.phase) || 'queued';
    var profile = _d.getActiveProfile ? _d.getActiveProfile() : {};
    var phaseCopy = (profile.contentPhaseCopy && profile.contentPhaseCopy[phase]) || {};

    if (runtimeStatus === 'Completed') {
      // Evidence surface is loaded by loadRunEvidence(), triggered from selectAnalysisRun
      // Phase status is hidden; evidence surface is shown
      return;
    }

    if (_d.showEvidenceSurface) _d.showEvidenceSurface(false);

    if (runtimeStatus === 'Failed' || runtimeStatus === 'Canceled' || runtimeStatus === 'Terminated') {
      imageryEl.textContent = 'Run interrupted';
      imageryNoteEl.textContent = 'The pipeline stopped before the imagery stack completed.';
      enrichmentEl.textContent = 'Context incomplete';
      enrichmentNoteEl.textContent = 'This run needs explicit failure handling rather than silent fallback behavior.';
      exportsEl.textContent = 'Nothing staged';
      exportsNoteEl.textContent = 'No saved outputs should be implied when the real pipeline fails.';
      return;
    }

    if (phase === 'ingestion' || phase === 'queued') {
      imageryEl.textContent = 'AOIs preparing';
      imageryNoteEl.textContent = 'The workspace is validating geometry and shaping the request for imagery search.';
      enrichmentEl.textContent = 'Waiting on imagery';
      enrichmentNoteEl.textContent = 'Context layers follow once the pipeline has something real to attach to.';
      exportsEl.textContent = 'Pipeline in motion';
      exportsNoteEl.textContent = 'Nothing is staged for export yet — outputs unlock after the run completes.';
      return;
    }

    if (phase === 'acquisition') {
      imageryEl.textContent = phaseCopy.imageryTitle || 'Scenes queued';
      imageryNoteEl.textContent = phaseCopy.imageryNote || 'Imagery is being selected and staged for this AOI set.';
      enrichmentEl.textContent = 'AOIs loading';
      enrichmentNoteEl.textContent = 'Context layers are being applied as the imagery batch arrives.';
      exportsEl.textContent = 'Preparing outputs';
      exportsNoteEl.textContent = 'Exports are being assembled — nearly there.';
      return;
    }

    if (phase === 'fulfilment') {
      imageryEl.textContent = phaseCopy.imageryTitle || 'Scenes confirmed';
      imageryNoteEl.textContent = phaseCopy.imageryNote || 'Imagery tiles are confirmed and being processed.';
      enrichmentEl.textContent = 'Enrichment completing';
      enrichmentNoteEl.textContent = 'Change detection, NDVI baselines, and weather context are being layered in.';
      exportsEl.textContent = 'Assembling outputs';
      exportsNoteEl.textContent = 'GeoJSON, CSV, and PDF packages are being built.';
      return;
    }

    if (phase === 'enrichment') {
      imageryEl.textContent = phaseCopy.imageryTitle || 'Imagery landed';
      imageryNoteEl.textContent = phaseCopy.imageryNote || 'All imagery tiles are confirmed and ready to view.';
      enrichmentEl.textContent = 'Enrichment active';
      enrichmentNoteEl.textContent = 'Context layers are being attached. Results unlock when enrichment completes.';
      exportsEl.textContent = 'Finalising exports';
      exportsNoteEl.textContent = 'Export packages are being finalised. They will unlock shortly.';
      return;
    }

    // Default / unknown phase
    imageryEl.textContent = 'Pipeline running';
    imageryNoteEl.textContent = 'The pipeline is active. Content panels will update as each phase completes.';
    enrichmentEl.textContent = 'In progress';
    enrichmentNoteEl.textContent = 'Enrichment layers will appear once imagery is confirmed.';
    exportsEl.textContent = 'Pending';
    exportsNoteEl.textContent = 'Exports will unlock when the run completes.';
  }

  // ── updateRunDetail ───────────────────────────────────────────

  function updateRunDetail(data) {
    var submittedEl = document.getElementById('app-run-submitted');
    var submittedNoteEl = document.getElementById('app-run-submitted-note');
    var scopeEl = document.getElementById('app-run-scope');
    var scopeNoteEl = document.getElementById('app-run-scope-note');
    var deliveryEl = document.getElementById('app-run-delivery');
    var deliveryNoteEl = document.getElementById('app-run-delivery-note');
    var linkLabelEl = document.getElementById('app-run-link-label');
    var linkEl = document.getElementById('app-run-link');
    if (!submittedEl || !submittedNoteEl || !scopeEl || !scopeNoteEl || !deliveryEl || !deliveryNoteEl || !linkLabelEl || !linkEl) return;

    var appBase = _d.getAppBase ? _d.getAppBase() : '/app/';
    if (!data) {
      submittedEl.textContent = '\u2014';
      submittedNoteEl.textContent = 'Run details restore here after reload.';
      scopeEl.textContent = '\u2014';
      scopeNoteEl.textContent = 'Feature and AOI counts appear when known.';
      deliveryEl.textContent = '\u2014';
      deliveryNoteEl.textContent = 'Failure counts and tracked artifacts will appear here.';
      linkLabelEl.textContent = 'Dashboard state';
      linkEl.href = appBase;
      linkEl.textContent = 'Open dashboard';
      document.querySelectorAll('[data-export-format]').forEach(function (button) {
        button.disabled = true;
      });
      return;
    }

    var runtimeStatus = data.runtimeStatus || 'Pending';
    var timing = _summarizeRunTiming(data);
    var scopeSummary = [
      _formatCountLabel(data.featureCount, 'feature'),
      _formatCountLabel(data.aoiCount, 'AOI'),
      data.processingMode,
    ].filter(Boolean).join(' \u2022 ');
    var scopeNote = [
      data.maxSpreadKm != null ? 'Spread ' + _formatDistance(data.maxSpreadKm) : null,
      data.totalAreaHa != null ? 'Area ' + _formatHectares(data.totalAreaHa) : null,
      _providerLabel(data.providerName),
    ].filter(Boolean).join(' \u2022 ');
    var failureSummary = _summarizeFailureCounts(data.partialFailures);
    var artifactCount = data.artifactCount || 0;

    submittedEl.textContent = _formatHistoryTimestamp(data.submittedAt || data.createdTime);
    submittedNoteEl.textContent = timing.sinceUpdate
      ? 'Last backend update ' + timing.sinceUpdate + ' ago.'
      : 'Your run history preserves this state across reloads.';
    scopeEl.textContent = scopeSummary || 'Scope loading';
    scopeNoteEl.textContent = scopeNote || 'Preflight detail appears when the run metadata is available.';

    if (runtimeStatus === 'Completed') {
      deliveryEl.textContent = artifactCount ? artifactCount + ' tracked outputs' : 'Exports ready';
      deliveryNoteEl.textContent = failureSummary || 'GeoJSON, CSV, and PDF exports are ready for this completed run.';
    } else if (runtimeStatus === 'Failed' || runtimeStatus === 'Canceled' || runtimeStatus === 'Terminated') {
      deliveryEl.textContent = 'Run interrupted';
      deliveryNoteEl.textContent = failureSummary || 'This run stopped before producing a complete result set.';
    } else {
      deliveryEl.textContent = 'Tracking live pipeline';
      deliveryNoteEl.textContent = failureSummary || 'Results will unlock here when the run completes.';
    }

    linkLabelEl.textContent = 'Run details';
    var permalink = _d.selectedRunPermalink ? _d.selectedRunPermalink(data.instanceId || data.instance_id) : appBase;
    linkEl.href = permalink;
    linkEl.textContent = 'Copy link to this run';

    document.querySelectorAll('[data-export-format]').forEach(function (button) {
      button.disabled = runtimeStatus !== 'Completed';
    });
    var evidenceExportNote = document.getElementById('app-evidence-export-note');
    if (evidenceExportNote) {
      evidenceExportNote.textContent = runtimeStatus === 'Completed'
        ? 'Download GeoJSON, CSV, or PDF for this completed run.'
        : 'Exports unlock when the selected run completes.';
    }
  }

  // ── downloadRunExport ─────────────────────────────────────────

  async function downloadRunExport(format) {
    var run = latestAnalysisRun;
    if (!run || !(run.instanceId || run.instance_id)) {
      if (_d.setAnalysisStatus) _d.setAnalysisStatus('Select a run first.', 'error');
      return;
    }

    var instanceId = run.instanceId || run.instance_id;
    if ((run.runtimeStatus || '') !== 'Completed') {
      if (_d.setAnalysisStatus) _d.setAnalysisStatus('Exports become available once the selected run completes.', 'info');
      return;
    }

    var button = document.querySelector('[data-export-format="' + format + '"]');
    var originalText = button ? button.textContent : format.toUpperCase();
    if (button) {
      button.disabled = true;
      button.textContent = 'Preparing\u2026';
    }

    try {
      var apiReady = _d.getApiReady ? _d.getApiReady() : Promise.resolve();
      await apiReady;
      var res = await _d.apiFetch('/api/export/' + encodeURIComponent(instanceId) + '/' + format);
      var blob = await res.blob();
      var blobUrl = URL.createObjectURL(blob);
      var link = document.createElement('a');
      link.href = blobUrl;
      link.download = _parseDownloadFilename(res, 'canopex_' + instanceId + '.' + format);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(blobUrl);
      if (_d.setAnalysisStatus) _d.setAnalysisStatus(format.toUpperCase() + ' export downloaded for the selected run.', 'success');
    } catch (err) {
      if (_d.setAnalysisStatus) _d.setAnalysisStatus((err && err.message) || 'Could not download the selected export.', 'error');
    } finally {
      if (button) {
        button.disabled = latestAnalysisRun && latestAnalysisRun.runtimeStatus !== 'Completed';
        button.textContent = originalText;
      }
    }
  }

  // ── updateAnalysisRun ─────────────────────────────────────────

  function updateAnalysisRun(data) {
    var panel = document.getElementById('app-analysis-run');
    latestAnalysisRun = data || null;
    if (!panel) return;
    if (!data) {
      panel.hidden = true;
      if (_d.setHeroRunSummary) {
        var readyNote = _d.getCurrentRoleConfig ? (_d.getCurrentRoleConfig().readyNote || '') : '';
        _d.setHeroRunSummary('Ready to queue', readyNote);
      }
      if (_d.updateHistorySummary) _d.updateHistorySummary(null);
      updateRunDetail(null);
      updateContentSummary(null);
      return;
    }
    panel.hidden = false;
    var instanceId = data.instanceId || data.instance_id || '\u2014';
    var runtimeStatus = data.runtimeStatus || 'queued';
    var phase = _displayAnalysisPhase(data.customStatus, runtimeStatus);
    var timing = _summarizeRunTiming(data);
    document.getElementById('app-analysis-instance').textContent = instanceId;
    document.getElementById('app-analysis-runtime').textContent = runtimeStatus;
    document.getElementById('app-analysis-phase').textContent = phase;
    if (_d.setHeroRunSummary) {
      _d.setHeroRunSummary(
        runtimeStatus,
        runtimeStatus === 'Completed'
          ? 'Pipeline finished successfully \u2014 results are ready.'
          : 'Current phase: ' + phase + '.' + (timing.elapsed ? ' Elapsed ' + timing.elapsed + '.' : '')
      );
    }
    if (_d.updateHistorySummary) _d.updateHistorySummary(data);
    updateRunDetail(data);
    updateContentSummary(data);
  }

  // ── applyFirstRunLayout ───────────────────────────────────────

  function applyFirstRunLayout() {
    var firstRun = document.getElementById('app-first-run-hero');
    var evidenceHero = document.getElementById('app-evidence-hero');
    var historyRail = document.getElementById('app-history-card');
    var workflowStage = document.getElementById('app-workflow-stage');
    var modePill = document.getElementById('app-hero-mode');
    var activeRunPill = document.getElementById('app-hero-active-run');
    if (!firstRun) return;

    var historyLoaded = _d.getAnalysisHistoryLoaded ? _d.getAnalysisHistoryLoaded() : false;
    var historyRuns = _d.getAnalysisHistoryRuns ? _d.getAnalysisHistoryRuns() : [];
    var isEmpty = historyLoaded && historyRuns.length === 0 && !latestAnalysisRun;
    firstRun.hidden = !isEmpty;
    if (evidenceHero) evidenceHero.hidden = isEmpty;

    // Collapse first-load noise: hide history rail + extra pills for new users
    if (historyRail) historyRail.hidden = isEmpty;
    if (workflowStage) workflowStage.classList.toggle('first-run', isEmpty);
    if (modePill) modePill.closest('.app-stat-pill').hidden = isEmpty;
    if (activeRunPill) activeRunPill.closest('.app-stat-pill').hidden = isEmpty;
  }

  // ── stopAnalysisPolling ───────────────────────────────────────

  function stopAnalysisPolling() {
    if (activeAnalysisPoll) {
      clearInterval(activeAnalysisPoll);
      activeAnalysisPoll = null;
    }
  }

  // ── pollAnalysisRun ───────────────────────────────────────────

  async function pollAnalysisRun(instanceId) {
    stopAnalysisPolling();
    const thisGeneration = ++analysisPollGeneration;
    let consecutiveFailures = 0;
    const MAX_CONSECUTIVE_FAILURES = 5;

    async function refreshRun() {
      // Bail out if a newer poll has started while we were awaiting.
      if (analysisPollGeneration !== thisGeneration) return null;
      try {
        var res = await _d.apiFetch('/api/orchestrator/' + instanceId);
        var data = await res.json();
        consecutiveFailures = 0;
        // Re-check after await — another selectAnalysisRun may have fired.
        if (analysisPollGeneration !== thisGeneration) return null;
        upsertHistoryRun(data);
        updateAnalysisRun(data);

        var runtime = data.runtimeStatus || '';
        var phase = _d.mapAnalysisPhase ? _d.mapAnalysisPhase(data.customStatus, runtime) : (data.customStatus && data.customStatus.phase) || 'queued';
        if (_d.setAnalysisProgressVisible) _d.setAnalysisProgressVisible(true);
        if (runtime === 'Completed') {
          stopAnalysisPolling();
          if (_d.setAnalysisStep) _d.setAnalysisStep('complete', 'done');
          if (_d.updateAnalysisStory) _d.updateAnalysisStory('complete', runtime, data);
          if (_d.clearCacheKey) { _d.clearCacheKey('billing'); _d.clearCacheKey('history'); }
          if (_d.loadBillingStatus) _d.loadBillingStatus();
          if (_d.loadAnalysisHistory) _d.loadAnalysisHistory({ preferInstanceId: instanceId });
          if (_d.loadRunEvidence) _d.loadRunEvidence(instanceId);
          var evidenceHero = document.getElementById('app-evidence-hero');
          if (evidenceHero) {
            setTimeout(function () {
              var scrollBehavior = 'smooth';
              if (typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
                scrollBehavior = 'auto';
              }
              evidenceHero.scrollIntoView({ behavior: scrollBehavior, block: 'start' });
            }, 400);
          }
        } else if (runtime === 'Failed' || runtime === 'Canceled' || runtime === 'Terminated') {
          stopAnalysisPolling();
          if (_d.setAnalysisStep) _d.setAnalysisStep(phase, 'failed');
          if (_d.updateAnalysisStory) _d.updateAnalysisStory(phase, runtime, data);
          if (_d.loadAnalysisHistory) _d.loadAnalysisHistory({ preferInstanceId: instanceId });
        } else {
          if (_d.setAnalysisStep) _d.setAnalysisStep(phase, 'active');
          if (_d.updateAnalysisStory) _d.updateAnalysisStory(phase, runtime || 'Pending', data);
        }
        return data;
      } catch {
        consecutiveFailures++;
        if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
          stopAnalysisPolling();
          if (_d.setAnalysisStatus) _d.setAnalysisStatus('Connection lost \u2014 pipeline updates have stopped. Reload the page to resume.', 'error');
        }
        return null;
      }
    }

    var initialData = await refreshRun();
    if (analysisPollGeneration !== thisGeneration) return; // superseded during initial fetch
    if (initialData) {
      var initialRuntime = initialData.runtimeStatus || '';
      if (initialRuntime === 'Completed' || initialRuntime === 'Failed' || initialRuntime === 'Canceled' || initialRuntime === 'Terminated') {
        return;
      }
    }

    activeAnalysisPoll = setInterval(function () {
      refreshRun();
    }, 3000);
  }

  // ── queueAnalysis ─────────────────────────────────────────────

  async function queueAnalysis() {
    var currentAccount = _d.getAccount ? _d.getAccount() : null;
    if (!currentAccount) {
      if (_d.login) _d.login();
      return;
    }

    // EUDR entitlement gate: show subscribe modal when trial is exhausted.
    // If billing hasn't loaded yet, fetch it before deciding.
    var activeProfile = _d.getActiveProfile ? _d.getActiveProfile() : {};
    if (activeProfile.requiresEudrBillingGate && typeof window.eudrBillingData === 'function') {
      var billing = window.eudrBillingData();
      if (!billing) {
        try {
          var apiReady0 = _d.getApiReady ? _d.getApiReady() : Promise.resolve();
          await apiReady0;
          var billingRes = await _d.apiFetch('/api/eudr/billing');
          billing = await billingRes.json();
        } catch (_) { /* proceed — server will enforce */ }
      }
      if (billing && !billing.subscribed && billing.trial_remaining != null && billing.trial_remaining <= 0) {
        if (typeof window.showEudrSubscribeModal === 'function') {
          window.showEudrSubscribeModal();
        }
        return;
      }
    }

    var button = document.getElementById('app-analysis-submit-btn');
    var textarea = document.getElementById('app-analysis-kml');
    if (!button || !textarea) return;

    var kmlContent = _parseKmlText(textarea.value);
    if (!kmlContent) {
      if (_d.setAnalysisStatus) _d.setAnalysisStatus('Paste KML content or load a KML/KMZ file first.', 'error');
      updateAnalysisRun(null);
      if (_d.resetAnalysisProgress) _d.resetAnalysisProgress();
      return;
    }

    var preflight = (_d.getAnalysisDraftSummary ? _d.getAnalysisDraftSummary() : null) || (_d.updateAnalysisPreflight ? _d.updateAnalysisPreflight(kmlContent) : null);
    if (preflight && preflight.error) {
      if (_d.setAnalysisStatus) _d.setAnalysisStatus(preflight.error, 'error');
      if (_d.resetAnalysisProgress) _d.resetAnalysisProgress();
      return;
    }

    button.disabled = true;
    button.textContent = 'Queueing\u2026';
    if (_d.resetAnalysisProgress) _d.resetAnalysisProgress();
    if (_d.setAnalysisProgressVisible) _d.setAnalysisProgressVisible(true);
    if (_d.setAnalysisStep) _d.setAnalysisStep('submit', 'active');
    if (_d.updateAnalysisStory) _d.updateAnalysisStory('submit', 'Pending', null);
    updateAnalysisRun(null);

    var workspaceRole = _d.getWorkspaceRole ? _d.getWorkspaceRole() : 'conservation';
    var workspacePreference = _d.getWorkspacePreference ? _d.getWorkspacePreference() : 'investigate';

    try {
      var apiReady = _d.getApiReady ? _d.getApiReady() : Promise.resolve();
      await apiReady;
      var submissionContext = null;
      if (preflight) {
        submissionContext = {
          feature_count: preflight.featureCount,
          aoi_count: preflight.aoiCount,
          max_spread_km: preflight.maxSpreadKm,
          total_area_ha: preflight.totalAreaHa,
          largest_area_ha: preflight.largestAreaHa,
          processing_mode: preflight.processingMode,
          provider_name: 'planetary_computer',
          workspace_role: workspaceRole,
          workspace_preference: workspacePreference
        };
      }

      // Step 1: Get SAS token from Container Apps FA.
      // apiFetch handles cross-origin routing and auth forwarding.
      var tokenBody = {};
      if (submissionContext) {
        tokenBody.provider_name = submissionContext.provider_name;
        tokenBody.submission_context = submissionContext;
      }

      // EUDR compliance mode (#600)
      var eudrCheckbox = document.getElementById('app-eudr-mode');
      if (eudrCheckbox && eudrCheckbox.checked) {
        tokenBody.eudr_mode = true;
      }

      var tokenRes;
      try {
        tokenRes = await _d.apiFetch('/api/upload/token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(tokenBody)
        });
      } catch (tokenFetchErr) {
        // 401 is handled centrally by apiFetch (clears session, shows re-login prompt).
        if (tokenFetchErr.status === 401) {
          if (_d.resetAnalysisProgress) _d.resetAnalysisProgress();
          return;
        }
        if (_d.setAnalysisStatus) _d.setAnalysisStatus((tokenFetchErr.body && tokenFetchErr.body.error) || 'Could not prepare upload. Please try again.', 'error');
        updateContentSummary(null);
        if (_d.resetAnalysisProgress) _d.resetAnalysisProgress();
        return;
      }

      var tokenData = await tokenRes.json();
      var submissionId = tokenData.submissionId || tokenData.submission_id;
      var sasUrl = tokenData.sasUrl || tokenData.sas_url;

      // Step 2: Upload KML directly to blob storage via SAS URL
      button.textContent = 'Uploading\u2026';
      if (_d.setAnalysisStep) _d.setAnalysisStep('submit', 'active');

      var kmlBytes = new TextEncoder().encode(kmlContent);
      var uploadRes = await fetch(sasUrl, {
        method: 'PUT',
        headers: {
          'x-ms-blob-type': 'BlockBlob',
          'Content-Type': 'application/vnd.google-earth.kml+xml'
        },
        body: kmlBytes
      });
      if (!uploadRes || !uploadRes.ok) {
        if (_d.setAnalysisStatus) _d.setAnalysisStatus('Upload failed. Please try again.', 'error');
        if (_d.resetAnalysisProgress) _d.resetAnalysisProgress();
        return;
      }

      // Step 3: Track the submission
      if (_d.clearCacheKey) { _d.clearCacheKey('history'); _d.clearCacheKey('billing'); }
      var data = { instance_id: submissionId };
      if (_d.setAnalysisHistoryLoaded) _d.setAnalysisHistoryLoaded(true);
      applyFirstRunLayout();
      var queuedAt = new Date().toISOString();
      upsertHistoryRun({
        instanceId: data.instance_id,
        submittedAt: queuedAt,
        createdTime: queuedAt,
        lastUpdatedTime: queuedAt,
        runtimeStatus: 'Pending',
        customStatus: { phase: 'queued' },
        providerName: 'planetary_computer',
        featureCount: preflight && preflight.featureCount,
        aoiCount: preflight && preflight.aoiCount,
        processingMode: preflight && preflight.processingMode,
        maxSpreadKm: preflight && preflight.maxSpreadKm,
        totalAreaHa: preflight && preflight.totalAreaHa,
        largestAreaHa: preflight && preflight.largestAreaHa,
        workspaceRole: workspaceRole,
        workspacePreference: workspacePreference
      });
      if (_d.selectAnalysisRun) _d.selectAnalysisRun(data.instance_id, { resume: true });
      if (_d.setAnalysisStatus) _d.setAnalysisStatus('Analysis queued. The app will walk through each stage as the pipeline advances.', 'info');
      if (_d.loadBillingStatus) _d.loadBillingStatus();
    } catch (err) {
      console.error('queueAnalysis failed:', err);
      if (_d.setAnalysisStatus) _d.setAnalysisStatus('Could not queue analysis request.', 'error');
      if (_d.resetAnalysisProgress) _d.resetAnalysisProgress();
    } finally {
      button.disabled = false;
      var draftSummary = _d.getAnalysisDraftSummary ? _d.getAnalysisDraftSummary() : null;
      button.textContent = draftSummary && !draftSummary.error ? 'Confirm & Queue' : 'Queue Analysis';
    }
  }

  // ── Public API ────────────────────────────────────────────────

  window.CanopexRunLifecycle = {
    init: init,
    getLatestRun: getLatestRun,
    updateContentSummary: updateContentSummary,
    updateRunDetail: updateRunDetail,
    downloadRunExport: downloadRunExport,
    updateAnalysisRun: updateAnalysisRun,
    applyFirstRunLayout: applyFirstRunLayout,
    stopAnalysisPolling: stopAnalysisPolling,
    pollAnalysisRun: pollAnalysisRun,
    queueAnalysis: queueAnalysis,
  };
})();
