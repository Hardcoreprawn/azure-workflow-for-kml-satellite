(function () {
  'use strict';

  var _d = {};

  function init(deps) {
    _d = deps || {};
  }

  function currentRoleConfig() {
    return _d.currentRoleConfig ? _d.currentRoleConfig() : {};
  }

  function currentPreferenceConfig() {
    return _d.currentPreferenceConfig ? _d.currentPreferenceConfig() : {};
  }

  function actionLabelForTarget(target) {
    var role = currentRoleConfig();
    if (target === 'history') return role.reviewLabel;
    if (target === 'content') return role.deliverableLabel;
    return role.runLabel;
  }

  function revealWorkflowTarget(target) {
    var cardId = target === 'history'
      ? 'app-history-card'
      : target === 'content'
        ? 'app-content-card'
        : 'app-analysis-card';
    var card = document.getElementById(cardId);
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderWorkspaceGuidance() {
    var role = currentRoleConfig();
    var preference = currentPreferenceConfig();
    var setText = _d.setText || function () {};
    var workspaceRole = _d.getWorkspaceRole ? _d.getWorkspaceRole() : 'conservation';
    var workspacePreference = _d.getWorkspacePreference ? _d.getWorkspacePreference() : 'investigate';

    var dashboard = document.getElementById('app-dashboard');
    if (dashboard) {
      dashboard.setAttribute('data-role', workspaceRole);
      dashboard.setAttribute('data-preference', workspacePreference);
    }

    document.querySelectorAll('[data-role-choice]').forEach(function (button) {
      button.setAttribute('aria-pressed', button.getAttribute('data-role-choice') === workspaceRole ? 'true' : 'false');
    });
    document.querySelectorAll('[data-preference-choice]').forEach(function (button) {
      button.setAttribute('aria-pressed', button.getAttribute('data-preference-choice') === workspacePreference ? 'true' : 'false');
    });

    setText('app-role-title', role.title);
    setText('app-role-tag', role.tag);
    setText('app-role-summary', role.summary);
    setText('app-role-outcome', role.outcome);
    setText('app-role-risk', role.risk);
    setText('app-role-rhythm', role.rhythm);

    setText('app-preference-title', preference.title);
    setText('app-preference-tag', preference.tag);
    setText('app-preference-summary', preference.summary);
    setText('app-guided-deliverable', preference.deliverable);
    setText('app-guided-stance', preference.stance);

    var primaryButton = document.getElementById('app-guided-primary-btn');
    var secondaryButton = document.getElementById('app-guided-secondary-btn');
    if (primaryButton) {
      primaryButton.textContent = actionLabelForTarget(preference.primaryTarget);
      primaryButton.setAttribute('data-target', preference.primaryTarget);
    }
    if (secondaryButton) {
      secondaryButton.textContent = actionLabelForTarget(preference.secondaryTarget);
      secondaryButton.setAttribute('data-target', preference.secondaryTarget);
    }

    setText('app-history-copy', role.historyCopy);
    setText('app-run-copy', role.runCopy);
    setText('app-content-copy', role.contentCopy);
    var lensTitle = document.getElementById('app-analysis-lens-title');
    var lensNote = document.getElementById('app-analysis-lens-note');
    if (lensTitle) lensTitle.textContent = role.runLensTitle;
    if (lensNote) lensNote.textContent = role.runLensNote + ' ' + preference.summary;

    var latestAnalysisRun = _d.getLatestAnalysisRun ? _d.getLatestAnalysisRun() : null;
    var analysisHistoryLoaded = _d.getAnalysisHistoryLoaded ? _d.getAnalysisHistoryLoaded() : false;
    var currentAccount = _d.getAccount ? _d.getAccount() : null;
    if (!latestAnalysisRun && _d.setHeroRunSummary) {
      if (!analysisHistoryLoaded && currentAccount) {
        _d.setHeroRunSummary('Checking recent runs', 'Loading your recent runs.');
      } else {
        _d.setHeroRunSummary('Ready to queue', role.readyNote);
      }
    }

    var latestBillingStatus = _d.getLatestBillingStatus ? _d.getLatestBillingStatus() : null;
    if (latestBillingStatus) updateHeroSummary(latestBillingStatus);
    updateHistorySummary(latestAnalysisRun);

    if (_d.renderAnalysisHistoryList) _d.renderAnalysisHistoryList();
    if (_d.updateContentSummary) _d.updateContentSummary(latestAnalysisRun);

    var draftTextarea = document.getElementById('app-analysis-kml');
    if (_d.updateAnalysisPreflight) {
      _d.updateAnalysisPreflight(draftTextarea ? draftTextarea.value : '');
    }
  }

  function updateHeroSummary(data) {
    var role = currentRoleConfig();
    var preference = currentPreferenceConfig();
    var capabilityHeadline = _d.capabilityHeadline || function () { return 'Standard'; };
    var formatRetention = _d.formatRetention || function (days) { return String(days || '-'); };
    var caps = data.capabilities || {};
    var planEl = document.getElementById('app-hero-plan');
    var planNoteEl = document.getElementById('app-hero-plan-note');
    var runsEl = document.getElementById('app-hero-runs');
    var runsNoteEl = document.getElementById('app-hero-runs-note');
    var modeEl = document.getElementById('app-hero-mode');
    var modeNoteEl = document.getElementById('app-hero-mode-note');
    if (!planEl || !planNoteEl || !runsEl || !runsNoteEl || !modeEl || !modeNoteEl) return;

    if (data.preview_mode) {
      planEl.textContent = 'Free plan preview';
      planNoteEl.textContent = 'Sign in to turn this preview into a real workspace.';
      runsEl.textContent = data.runs_remaining == null ? '-' : String(data.runs_remaining);
      runsNoteEl.textContent = 'Free-plan limits shown here only activate after sign-in.';
      modeEl.textContent = capabilityHeadline(caps);
      modeNoteEl.textContent = role.label + ' | ' + preference.label + ' | Preview mode only until you authenticate.';
      return;
    }

    planEl.textContent = (caps.label || data.tier || 'Free') + (data.tier_source === 'emulated' ? ' (emulated)' : '');
    planNoteEl.textContent = data.tier_source === 'emulated'
      ? 'Local override for product testing.'
      : 'Based on your account.';
    runsEl.textContent = data.runs_remaining == null ? '-' : String(data.runs_remaining);
    runsNoteEl.textContent = data.runs_remaining == null
      ? 'Quota unavailable in this environment.'
      : 'Remaining analyses before the current limit is reached.';
    modeEl.textContent = capabilityHeadline(caps);
    modeNoteEl.textContent = role.label + ' | ' + preference.label + ' | Retention ' + formatRetention(caps.retention_days) + ' | ' + (caps.api_access ? 'API enabled' : 'API not included');
  }

  function updateHistorySummary(data) {
    var role = currentRoleConfig();
    var displayAnalysisPhase = _d.displayAnalysisPhase || function () { return 'unknown'; };
    var summarizeRunTiming = _d.summarizeRunTiming || function () { return {}; };
    var analysisHistoryRuns = _d.getAnalysisHistoryRuns ? _d.getAnalysisHistoryRuns() : [];
    var selectedAnalysisRunId = _d.getSelectedAnalysisRunId ? _d.getSelectedAnalysisRunId() : null;
    var analysisHistoryLoaded = _d.getAnalysisHistoryLoaded ? _d.getAnalysisHistoryLoaded() : false;
    var currentAccount = _d.getAccount ? _d.getAccount() : null;

    var statusEl = document.getElementById('app-history-latest-status');
    var noteEl = document.getElementById('app-history-latest-note');
    var instanceEl = document.getElementById('app-history-latest-instance');
    var phaseEl = document.getElementById('app-history-latest-phase');
    var pathEl = document.getElementById('app-history-latest-path');
    if (!statusEl || !noteEl || !instanceEl || !phaseEl || !pathEl) return;

    renderPortfolioSummary();

    if (!data) {
      if (!analysisHistoryLoaded && currentAccount) {
        statusEl.textContent = 'Loading recent runs';
        noteEl.textContent = 'Loading your history and checking for active runs.';
        instanceEl.textContent = '...';
        phaseEl.textContent = 'loading';
        pathEl.textContent = role.activePath;
        return;
      }
      statusEl.textContent = 'No runs yet';
      noteEl.textContent = role.emptyHistoryNote;
      instanceEl.textContent = '-';
      phaseEl.textContent = '-';
      pathEl.textContent = role.completedPath;
      return;
    }

    var instanceId = data.instanceId || data.instance_id || '-';
    var runtimeStatus = data.runtimeStatus || 'Pending';
    var phase = displayAnalysisPhase(data.customStatus, runtimeStatus);
    var timing = summarizeRunTiming(data);
    var summaryLabel = analysisHistoryRuns.length > 1 && selectedAnalysisRunId
      ? 'Selected analysis'
      : 'Latest analysis';
    statusEl.textContent = runtimeStatus;
    noteEl.textContent = runtimeStatus === 'Completed'
      ? summaryLabel + ' completed and is ready to become a ' + role.completedHistoryOutcome + '.'
      : summaryLabel + ' is active. This rail keeps ' + role.activeHistoryContext + ' visible while you stay centered on the run.';
    if (runtimeStatus !== 'Completed' && timing.sinceUpdate) {
      noteEl.textContent += ' Last backend update ' + timing.sinceUpdate + ' ago.';
    }
    instanceEl.textContent = instanceId;
    phaseEl.textContent = phase;
    pathEl.textContent = runtimeStatus === 'Completed' ? role.completedPath : role.activePath;
  }

  function renderPortfolioSummary() {
    var summaryEl = document.getElementById('app-portfolio-summary');
    if (!summaryEl) return;

    var setText = _d.setText || function () {};
    var latestPortfolioSummary = _d.getLatestPortfolioSummary ? _d.getLatestPortfolioSummary() : null;
    var scope = latestPortfolioSummary && latestPortfolioSummary.scope;
    var stats = latestPortfolioSummary && latestPortfolioSummary.stats;
    if (scope !== 'org' || !stats) {
      summaryEl.hidden = true;
      return;
    }

    summaryEl.hidden = false;
    setText('app-portfolio-total-runs', String(stats.totalRuns || 0));
    setText('app-portfolio-active-runs', String(stats.activeRuns || 0));
    setText('app-portfolio-completed-runs', String(stats.completedRuns || 0));
    setText('app-portfolio-total-parcels', String(stats.totalParcels || 0));

    var memberCount = latestPortfolioSummary.memberCount || 1;
    var scopeNote = memberCount > 1
      ? 'Org portfolio view (' + memberCount + ' members)'
      : 'Org portfolio view';
    setText('app-portfolio-scope-note', scopeNote);

    var exportRow = document.getElementById('app-summary-export-row');
    if (exportRow) exportRow.hidden = false;
  }

  window.CanopexSummaryUi = {
    init: init,
    actionLabelForTarget: actionLabelForTarget,
    revealWorkflowTarget: revealWorkflowTarget,
    renderWorkspaceGuidance: renderWorkspaceGuidance,
    updateHeroSummary: updateHeroSummary,
    updateHistorySummary: updateHistorySummary,
    renderPortfolioSummary: renderPortfolioSummary,
  };
})();
