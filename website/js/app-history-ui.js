(function(){
  'use strict';

  var _d = {}; // deps

  // ── renderAnalysisHistoryList ──────────────────────────────────────
  // Populate DOM with run list. Calls selectAnalysisRun on click.

  function renderAnalysisHistoryList() {
    var container = document.getElementById('app-history-list');
    if (!container) return;

    container.replaceChildren();
    var analysisHistoryLoaded = _d.getAnalysisHistoryLoaded ? _d.getAnalysisHistoryLoaded() : false;
    var currentAccount = _d.getAccount ? _d.getAccount() : null;
    var selectedAnalysisRunId = _d.getSelectedAnalysisRunId ? _d.getSelectedAnalysisRunId() : null;
    var analysisHistoryRuns = _d.getAnalysisHistoryRuns ? _d.getAnalysisHistoryRuns() : [];

    if (!analysisHistoryLoaded && currentAccount) {
      var loading = document.createElement('div');
      loading.className = 'app-history-empty';
      loading.textContent = 'Loading your history…';
      container.appendChild(loading);
      return;
    }
    if (!analysisHistoryRuns.length) {
      var empty = document.createElement('div');
      empty.className = 'app-history-empty';
      var roleConfig = _d.currentRoleConfig ? _d.currentRoleConfig() : { emptyHistoryNote: 'No runs yet.' };
      empty.textContent = roleConfig.emptyHistoryNote;
      container.appendChild(empty);
      return;
    }

    analysisHistoryRuns.forEach(function(run) {
      var instanceId = run.instanceId || run.instance_id;
      var runtimeStatus = run.runtimeStatus || 'Pending';
      var displayAnalysisPhase = _d.displayAnalysisPhase || function() { return 'unknown'; };
      var phase = displayAnalysisPhase(run.customStatus, runtimeStatus);
      var button = document.createElement('button');
      var header = document.createElement('div');
      var title = document.createElement('strong');
      var status = document.createElement('span');
      var meta = document.createElement('div');
      var submitted = document.createElement('span');
      var phaseMeta = document.createElement('span');
      var scopeMeta = document.createElement('span');
      var note = document.createElement('div');

      button.type = 'button';
      button.className = 'app-history-item';
      button.setAttribute('data-selected', instanceId === selectedAnalysisRunId ? 'true' : 'false');
      button.addEventListener('click', function(event) {
        event.stopPropagation();
        selectAnalysisRun(instanceId, { resume: historyRunIsActive(run) });
      });

      header.className = 'app-history-item-header';
      title.className = 'app-history-item-title';
      var titleParts = [];
      var formatCountLabel = _d.formatCountLabel || function(n, singular) { return n + ' ' + singular; };
      if (run.aoiCount) titleParts.push(formatCountLabel(run.aoiCount, 'AOI'));
      if (run.totalAreaHa) titleParts.push(Number(run.totalAreaHa).toFixed(1) + ' ha');
      var titleLabel = titleParts.length ? titleParts.join(' · ') : shortInstanceId(instanceId);
      title.textContent = (historyRunIsActive(run) ? 'Resume: ' : '') + titleLabel;
      status.className = 'app-history-item-status';
      status.textContent = runtimeStatus;
      header.appendChild(title);
      header.appendChild(status);

      meta.className = 'app-history-item-meta';
      var formatHistoryTimestamp = _d.formatHistoryTimestamp || function(t) { return t; };
      var providerLabel = _d.providerLabel || function(p) { return p || ''; };
      submitted.textContent = formatHistoryTimestamp(run.submittedAt || run.createdTime);
      phaseMeta.textContent = 'Phase ' + phase;
      scopeMeta.textContent = [formatCountLabel(run.aoiCount, 'AOI'), providerLabel(run.providerName)].filter(Boolean).join(' • ') || 'Tracked run';
      meta.appendChild(submitted);
      meta.appendChild(phaseMeta);
      meta.appendChild(scopeMeta);

      note.className = 'app-history-item-note';
      if (historyRunIsActive(run)) {
        note.textContent = 'Resume this run from ' + phase + '.';
      } else if (runtimeStatus === 'Completed') {
        note.textContent = 'View completed results and download exports.';
      } else {
        note.textContent = 'Review this run state.';
      }

      button.appendChild(header);
      button.appendChild(meta);
      button.appendChild(note);
      container.appendChild(button);
    });
  }

  // ── selectAnalysisRun ──────────────────────────────────────────────

  function selectAnalysisRun(instanceId, options) {
    options = options || {};
    var analysisHistoryRuns = _d.getAnalysisHistoryRuns ? _d.getAnalysisHistoryRuns() : [];
    var run = analysisHistoryRuns.find(function(entry) {
      return (entry.instanceId || entry.instance_id) === instanceId;
    });
    if (!run) return;

    if (_d.setSelectedAnalysisRunId) _d.setSelectedAnalysisRunId(instanceId);
    renderAnalysisHistoryList();
    if (_d.updateRunSelectionLocation) _d.updateRunSelectionLocation(instanceId);

    if (_d.stopAnalysisPolling) _d.stopAnalysisPolling();
    if (_d.stopPlay) _d.stopPlay(); // Evidence display timelapse
    if (_d.updateAnalysisRun) _d.updateAnalysisRun(run);
    if (_d.resetAnalysisProgress) _d.resetAnalysisProgress();
    if (_d.setAnalysisProgressVisible) _d.setAnalysisProgressVisible(true);

    var runtimeStatus = run.runtimeStatus || 'Pending';
    var mapAnalysisPhase = _d.mapAnalysisPhase || function() { return 'unknown'; };
    var phase = mapAnalysisPhase(run.customStatus, runtimeStatus);
    if (runtimeStatus === 'Completed') {
      if (_d.setAnalysisStep) _d.setAnalysisStep('complete', 'done');
      if (_d.updateAnalysisStory) _d.updateAnalysisStory('complete', runtimeStatus, run);
      if (_d.loadRunEvidence) _d.loadRunEvidence(instanceId);
      return;
    }
    if (runtimeStatus === 'Failed' || runtimeStatus === 'Canceled' || runtimeStatus === 'Terminated') {
      if (_d.setAnalysisStep) _d.setAnalysisStep(phase, 'failed');
      if (_d.updateAnalysisStory) _d.updateAnalysisStory(phase, runtimeStatus, run);
      return;
    }

    if (_d.setAnalysisStep) _d.setAnalysisStep(phase, 'active');
    if (_d.updateAnalysisStory) _d.updateAnalysisStory(phase, runtimeStatus || 'Pending', run);
    if (options.resume !== false && _d.pollAnalysisRun) _d.pollAnalysisRun(instanceId);
  }

  // ── applyAnalysisHistory ───────────────────────────────────────────
  // Load history payload, apply selection logic, update UI.

  function applyAnalysisHistory(payload, options) {
    options = options || {};
    var readRunSelectionFromLocation = _d.readRunSelectionFromLocation || function() { return { instanceId: '' }; };
    var locationSelection = readRunSelectionFromLocation();

    if (typeof appRuns.applyHistoryPayload === 'function') {
      var getSelectedAnalysisRunId = _d.getSelectedAnalysisRunId || function() { return null; };
      var getLatestAnalysisRun = _d.getLatestAnalysisRun || function() { return null; };
      var getAnalysisHistoryRuns = _d.getAnalysisHistoryRuns || function() { return []; };
      var parseStatusTimestamp = _d.parseStatusTimestamp || function(t) { return t; };

      var applied = appRuns.applyHistoryPayload(
        payload,
        options,
        getSelectedAnalysisRunId(),
        getLatestAnalysisRun(),
        locationSelection.instanceId,
        parseStatusTimestamp
      );

      if (_d.setLatestPortfolioSummary) _d.setLatestPortfolioSummary(applied.portfolioSummary);
      if (_d.setAnalysisHistoryRuns) _d.setAnalysisHistoryRuns(applied.runs);

      if (!applied.selectedId) {
        if (_d.setSelectedAnalysisRunId) _d.setSelectedAnalysisRunId(null);
        if (_d.updateRunSelectionLocation) _d.updateRunSelectionLocation('');
        if (_d.stopAnalysisPolling) _d.stopAnalysisPolling();
        if (_d.resetAnalysisProgress) _d.resetAnalysisProgress();
        renderAnalysisHistoryList();
        if (_d.updateAnalysisRun) _d.updateAnalysisRun(null);
        if (_d.updateHistorySummary) _d.updateHistorySummary(null);
        return;
      }

      var selectedRun = applied.runs.find(function(run) { return run.instanceId === applied.selectedId; });
      selectAnalysisRun(applied.selectedId, { resume: historyRunIsActive(selectedRun) });
      return;
    }

    // Fallback: apply history manually
    if (_d.setLatestPortfolioSummary) {
      _d.setLatestPortfolioSummary({
        scope: payload && payload.scope,
        orgId: payload && payload.orgId,
        memberCount: payload && payload.memberCount,
        stats: payload && payload.stats
      });
    }

    var normalizeAnalysisRun = _d.normalizeAnalysisRun || function(r) { return r; };
    var sortAnalysisHistoryRuns = _d.sortAnalysisHistoryRuns || function(r) { return r; };
    var normalizedActiveRun = normalizeAnalysisRun(payload && payload.activeRun);
    var runs = sortAnalysisHistoryRuns(payload && payload.runs);
    if (_d.setAnalysisHistoryRuns) _d.setAnalysisHistoryRuns(runs);

    if (normalizedActiveRun && !runs.some(function(run) { return run.instanceId === normalizedActiveRun.instanceId; })) {
      runs.unshift(normalizedActiveRun);
      runs = sortAnalysisHistoryRuns(runs);
      if (_d.setAnalysisHistoryRuns) _d.setAnalysisHistoryRuns(runs);
    }

    var getLatestAnalysisRun = _d.getLatestAnalysisRun || function() { return null; };
    if (options.preferInstanceId && getLatestAnalysisRun() &&
        (getLatestAnalysisRun().instanceId || getLatestAnalysisRun().instance_id) === options.preferInstanceId &&
        !runs.some(function(run) { return run.instanceId === options.preferInstanceId; })) {
      var preserved = normalizeAnalysisRun(getLatestAnalysisRun());
      if (preserved) {
        runs.unshift(preserved);
        runs = sortAnalysisHistoryRuns(runs);
        if (_d.setAnalysisHistoryRuns) _d.setAnalysisHistoryRuns(runs);
      }
    }

    var getSelectedAnalysisRunId = _d.getSelectedAnalysisRunId || function() { return null; };
    var nextSelectedId = options.preferInstanceId || getSelectedAnalysisRunId() || locationSelection.instanceId;
    if (nextSelectedId && !runs.some(function(run) { return run.instanceId === nextSelectedId; })) {
      nextSelectedId = null;
    }
    if (!nextSelectedId && normalizedActiveRun) nextSelectedId = normalizedActiveRun.instanceId;
    if (!nextSelectedId && runs[0]) nextSelectedId = runs[0].instanceId;

    if (!nextSelectedId) {
      if (_d.setSelectedAnalysisRunId) _d.setSelectedAnalysisRunId(null);
      if (_d.updateRunSelectionLocation) _d.updateRunSelectionLocation('');
      if (_d.stopAnalysisPolling) _d.stopAnalysisPolling();
      if (_d.resetAnalysisProgress) _d.resetAnalysisProgress();
      renderAnalysisHistoryList();
      if (_d.updateAnalysisRun) _d.updateAnalysisRun(null);
      if (_d.updateHistorySummary) _d.updateHistorySummary(null);
      return;
    }

    var selectedRun = runs.find(function(run) { return run.instanceId === nextSelectedId; });
    selectAnalysisRun(nextSelectedId, { resume: historyRunIsActive(selectedRun) });
  }

  // ── Helpers ────────────────────────────────────────────────────────

  function shortInstanceId(id) {
    if (!id) return '—';
    return id.substring(0, 8) + '…';
  }

  function historyRunIsActive(run) {
    if (typeof appRuns.isRunActive === 'function') {
      return appRuns.isRunActive(run);
    }
    var runtimeStatus = String(run && run.runtimeStatus || '').trim().toLowerCase();
    return ['completed', 'failed', 'terminated', 'canceled'].indexOf(runtimeStatus) === -1;
  }

  // --- init ---

  function init(deps) {
    _d = deps || {};
  }

  // --- Export ---

  window.CanopexHistoryUi = {
    init: init,
    renderAnalysisHistoryList: renderAnalysisHistoryList,
    selectAnalysisRun: selectAnalysisRun,
    applyAnalysisHistory: applyAnalysisHistory,
  };
})();
