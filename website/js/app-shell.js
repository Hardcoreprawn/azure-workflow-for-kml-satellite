(function(){
  'use strict';

  const POST_LOGIN_DESTINATION_KEY = 'canopex-post-login';
  const WORKSPACE_ROLE_STORAGE_KEY = 'canopex-workspace-role';
  const WORKSPACE_PREFERENCE_STORAGE_KEY = 'canopex-workspace-preference';
  const WORKSPACE_ROLES = {
    conservation: {
      label: 'Conservation',
      tag: 'Field evidence',
      title: 'Conservation monitoring',
      summary: 'Built for protected-area coordinators who need rapid, plain-English evidence they can take to rangers, directors, or donors.',
      outcome: 'Evidence packs',
      risk: 'No silent fallback',
      rhythm: 'Monthly watchlist',
      historyCopy: 'Keep the most recent incident visible while you compare new reports against what already ran.',
      runCopy: 'Queue an analysis for a protected area or reported clearing.',
      contentCopy: 'Use this rail to understand what evidence is being assembled and what will be ready for a field or donor brief.',
      runLensTitle: 'Conservation analysis',
      runLensNote: 'Frame this run around vegetation change, weather context, and plain-English proof.',
      readyNote: 'Ready to run a conservation analysis.',
      emptyHistoryNote: 'Your next submission will appear here.',
      activeHistoryContext: 'field evidence',
      completedHistoryOutcome: 'shareable evidence brief',
      activePath: 'Tracking evidence build',
      completedPath: 'Review results',
      runLabel: 'Start analysis',
      reviewLabel: 'Review latest incident',
      deliverableLabel: 'Open evidence rail',
      emptyContent: {
        imageryTitle: 'Waiting for a run',
        imageryNote: 'Before/after imagery and NDVI layers will appear here as the evidence stack forms.',
        enrichmentTitle: 'Context pending',
        enrichmentNote: 'Weather and narrative context will follow once the imagery pipeline is stable.',
        exportsTitle: 'Evidence pack next',
        exportsNote: 'Saved maps, narrative, and donor-ready exports will land here once run detail is wired.'
      },
      completedContent: {
        exportsTitle: 'Evidence pack next',
        exportsNote: 'Maps, narrative, and a field-ready evidence pack will be available after results load.'
      }
    },
    eudr: {
      label: 'EUDR',
      tag: 'Audit trail',
      title: 'EUDR due diligence',
      summary: 'Support compliance teams that need post-2020 evidence, clear audit language, and no ambiguity about what the product actually processed.',
      outcome: 'Due diligence dossier',
      risk: 'Audit-ready trust',
      rhythm: 'Quarterly refresh cadence',
      historyCopy: 'Keep the most recent assessment visible while you decide whether another supplier plot needs review.',
      runCopy: 'Queue a due diligence run with explicit product-path status.',
      contentCopy: 'Use this rail to understand what audit evidence is forming before it becomes a saved due diligence dossier.',
      runLensTitle: 'EUDR compliance check',
      runLensNote: 'Keep baseline integrity, plain-English findings, and product-path reliability front and center.',
      readyNote: 'Ready to run a due diligence check.',
      emptyHistoryNote: 'Your next submission will appear here.',
      activeHistoryContext: 'audit context',
      completedHistoryOutcome: 'due diligence dossier',
      activePath: 'Tracking audit evidence',
      completedPath: 'Prepare audit dossier',
      runLabel: 'Start due diligence run',
      reviewLabel: 'Review latest assessment',
      deliverableLabel: 'Open dossier rail',
      emptyContent: {
        imageryTitle: 'Awaiting baseline review',
        imageryNote: 'Before/after imagery will anchor the post-2020 evidence trail once you queue a run.',
        enrichmentTitle: 'Assessment pending',
        enrichmentNote: 'Narrative findings and methodology framing follow after imagery is stable.',
        exportsTitle: 'Audit dossier next',
        exportsNote: 'Saved evidence packages with coordinates, methods, and narrative will land here once run detail is wired.'
      },
      completedContent: {
        exportsTitle: 'Audit dossier next',
        exportsNote: 'Coordinates, methods, and exportable due diligence evidence will be available after results load.'
      }
    },
    portfolio: {
      label: 'Portfolio Ops',
      tag: 'Batch triage',
      title: 'Portfolio operations',
      summary: 'Support advisors, insurers, and ops teams who need to scan many parcels quickly, keep batch context visible, and decide what needs follow-up.',
      outcome: 'Batch triage',
      risk: 'Scale without guesswork',
      rhythm: 'Event-driven review',
      historyCopy: 'Keep the most recent batch visible so you can triage new uploads against what already moved.',
      runCopy: 'Queue a batch-style analysis and keep scale warnings visible.',
      contentCopy: 'Use this rail to understand what the current run is building before you reopen it as a parcel-level review.',
      runLensTitle: 'Portfolio triage run',
      runLensNote: 'Bias the workspace toward batch readiness, AOI spread, and which runs need deeper follow-up.',
      readyNote: 'Ready to run a batch analysis.',
      emptyHistoryNote: 'Your next submission will appear here.',
      activeHistoryContext: 'batch context',
      completedHistoryOutcome: 'triage summary',
      activePath: 'Tracking batch progress',
      completedPath: 'Open triage summary',
      runLabel: 'Start batch triage run',
      reviewLabel: 'Review latest batch',
      deliverableLabel: 'Open triage rail',
      emptyContent: {
        imageryTitle: 'Awaiting parcel stack',
        imageryNote: 'Imagery layers will appear here as batch-ready AOIs begin resolving into usable review outputs.',
        enrichmentTitle: 'Triage context pending',
        enrichmentNote: 'Context layers follow once the imagery stack shows where deeper review is needed.',
        exportsTitle: 'Triage summary next',
        exportsNote: 'Saved parcel review packs and export actions will land here once run detail is wired.'
      },
      completedContent: {
        exportsTitle: 'Triage summary next',
        exportsNote: 'Parcel-level review and export actions will be available after results load.'
      }
    }
  };
  const WORKSPACE_PREFERENCES = {
    investigate: {
      label: 'Investigate',
      tag: 'Run-first',
      title: 'Investigate suspicious change',
      summary: 'Stay centered on the live run while you prove what changed, why it changed, and what to do next.',
      deliverable: 'Operator brief',
      stance: 'Prove the change before escalation',
      focusLabel: 'Run rail',
      focusTarget: 'run',
      primaryTarget: 'run',
      secondaryTarget: 'history'
    },
    monitor: {
      label: 'Monitor',
      tag: 'Queue-first',
      title: 'Monitor for movement over time',
      summary: 'Bias the workspace toward what changed recently so recurring reviews and follow-up runs stay efficient.',
      deliverable: 'Monitoring cadence',
      stance: 'Spot movement early and repeat',
      focusLabel: 'History rail',
      focusTarget: 'history',
      primaryTarget: 'history',
      secondaryTarget: 'run'
    },
    report: {
      label: 'Report',
      tag: 'Deliverable-first',
      title: 'Package findings for action',
      summary: 'Focus on outputs, evidence language, and what to deliver next.',
      deliverable: 'Decision packet',
      stance: 'Translate signal into action',
      focusLabel: 'Content rail',
      focusTarget: 'content',
      primaryTarget: 'content',
      secondaryTarget: 'run'
    }
  };

  let apiDiscoveryReady = null;

  // Container Apps FA: API calls go cross-origin to the Function App
  // hostname discovered from /api-config.json (injected at deploy time).
  // Auth principal is forwarded via X-MS-CLIENT-PRINCIPAL header.
  let _apiBase = '';          // Container Apps FA hostname, e.g. 'https://func-kmlsat-dev.azurecontainerapps.io'
  let _clientPrincipal = null; // raw clientPrincipal from /.auth/me — base64-encoded for X-MS-CLIENT-PRINCIPAL
  let currentAccount = null;   // populated by /.auth/me
  let latestBillingStatus = null;
  let latestAnalysisRun = null;
  let analysisHistoryRuns = [];
  let analysisHistoryLoaded = false;
  let selectedAnalysisRunId = null;
  let analysisDraftSummary = null;
  let workspaceRole = 'conservation';
  let workspacePreference = 'investigate';
  let activeAnalysisPoll = null;
  const ANALYSIS_PHASES = ['submit', 'ingestion', 'acquisition', 'fulfilment', 'enrichment', 'complete'];
  const ANALYSIS_PHASE_DETAILS = {
    submit: 'Uploading your KML and reserving a pipeline worker for this run.',
    ingestion: 'Parsing the file, validating AOI geometry, and preparing the analysis package.',
    acquisition: 'Searching NAIP and Sentinel-2 coverage to find the best imagery for each AOI.',
    fulfilment: 'Downloading scenes, clipping to your AOIs, and reprojecting them into the output stack.',
    enrichment: 'Adding NDVI, weather context, and cached artifacts so the workspace has richer outputs ready.',
    complete: 'Analysis complete — scroll down to review satellite imagery, vegetation health, and export options.'
  };

  function authEnabled() { return true; /* SWA built-in auth — always available */ }

  function rememberPostLoginDestination() {
    try { sessionStorage.setItem(POST_LOGIN_DESTINATION_KEY, 'app'); } catch { /* ignore */ }
  }

  function setServiceStatus(text, className) {
    var badge = document.getElementById('status-badge');
    if (!badge) return;
    badge.textContent = text;
    badge.className = className || '';
  }

  function runningOnLocalDevOrigin() {
    return window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  }



  async function discoverApiBase() {
    // Read the Container Apps FA hostname from /api-config.json (injected at deploy time).
    // Falls back to same-origin for local dev (func start serves /api/* locally).
    try {
      const cfgRes = await fetch('/api-config.json');
      if (cfgRes.ok) {
        const cfg = await cfgRes.json();
        if (cfg.apiBase) {
          _apiBase = cfg.apiBase.replace(/\/+$/, ''); // strip trailing slashes
        }
      }
    } catch { /* local dev — no api-config.json, use same-origin */ }

    // Probe health to confirm the API is reachable.
    try {
      const healthUrl = _apiBase ? _apiBase + '/api/health' : '/api/health';
      const res = await fetch(healthUrl);
      if (res.ok) {
        setServiceStatus('Online', 'online');
        return;
      }
    } catch { /* ignore */ }
    setServiceStatus('Unavailable', 'offline');
  }

  function login() {
    rememberPostLoginDestination();
    window.location.href = '/.auth/login/aad';
  }

  function logout() {
    try { sessionStorage.removeItem(POST_LOGIN_DESTINATION_KEY); } catch { /* ignore */ }
    window.location.href = '/.auth/logout';
  }

  async function apiFetch(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    // Forward the SWA client principal to Container Apps FA so the
    // require_auth decorator can identify the user on cross-origin calls.
    if (_clientPrincipal) {
      // UTF-8 safe base64: encode to bytes first, then btoa on Latin-1 string.
      var jsonStr = JSON.stringify(_clientPrincipal);
      var bytes = new TextEncoder().encode(jsonStr);
      var binStr = Array.from(bytes, function (b) { return String.fromCharCode(b); }).join('');
      opts.headers['X-MS-CLIENT-PRINCIPAL'] = btoa(binStr);
    }
    const url = _apiBase ? _apiBase + path : path;
    const resp = await fetch(url, opts);
    if (!resp.ok) {
      const body = await resp.json().catch(function () { return {}; });
      const msg = body.error || ('API request failed: ' + resp.status + ' ' + resp.statusText);
      const err = new Error(msg);
      err.status = resp.status;
      err.body = body;
      throw err;
    }
    return resp;
  }

  function setAnalysisStatus(message, tone) {
    var status = document.getElementById('app-analysis-status');
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
    var titleEl = document.getElementById('app-hero-active-run');
    var noteEl = document.getElementById('app-hero-active-run-note');
    if (!titleEl || !noteEl) return;
    titleEl.textContent = title || 'Ready to queue';
    noteEl.textContent = note || 'Ready to run an analysis.';
  }

  function setWorkflowFocus(focus) {
    var stage = document.getElementById('app-workflow-stage');
    if (!stage || !focus) return;
    // Evidence is now in its own hero section — map 'content' to scroll there
    if (focus === 'content') {
      var hero = document.getElementById('app-evidence-hero');
      if (hero) hero.scrollIntoView({ behavior: 'smooth', block: 'start' });
      stage.setAttribute('data-focus', 'run');
    } else {
      stage.setAttribute('data-focus', focus);
    }
    if (selectedAnalysisRunId) updateRunSelectionLocation(selectedAnalysisRunId, focus);
  }

  function readRunSelectionFromLocation() {
    try {
      var params = new URLSearchParams(window.location.search || '');
      return {
        instanceId: params.get('run') || '',
        focus: params.get('focus') || ''
      };
    } catch {
      return { instanceId: '', focus: '' };
    }
  }

  function selectedRunPermalink(instanceId, focus) {
    try {
      var url = new URL(window.location.href);
      if (instanceId) {
        url.searchParams.set('run', instanceId);
      } else {
        url.searchParams.delete('run');
      }
      if (focus) {
        url.searchParams.set('focus', focus);
      } else {
        url.searchParams.delete('focus');
      }
      var nextPath = url.pathname;
      var nextSearch = url.searchParams.toString();
      return nextSearch ? nextPath + '?' + nextSearch : nextPath;
    } catch {
      return '/app/';
    }
  }

  function updateRunSelectionLocation(instanceId, focus) {
    if (!window.history || typeof window.history.replaceState !== 'function') return;
    try {
      window.history.replaceState({}, '', selectedRunPermalink(instanceId, focus));
    } catch { /* ignore */ }
  }

  function readStoredUiValue(key) {
    try { return localStorage.getItem(key); } catch { return null; }
  }

  function storeUiValue(key, value) {
    try { localStorage.setItem(key, value); } catch { /* ignore */ }
  }

  function currentRoleConfig() {
    return WORKSPACE_ROLES[workspaceRole] || WORKSPACE_ROLES.conservation;
  }

  function currentPreferenceConfig() {
    return WORKSPACE_PREFERENCES[workspacePreference] || WORKSPACE_PREFERENCES.investigate;
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
    setWorkflowFocus(target || 'run');
    var card = document.getElementById(cardId);
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderWorkspaceGuidance() {
    var role = currentRoleConfig();
    var preference = currentPreferenceConfig();
    var dashboard = document.getElementById('app-dashboard');
    if (dashboard) {
      dashboard.setAttribute('data-role', workspaceRole);
      dashboard.setAttribute('data-preference', workspacePreference);
    }

    document.querySelectorAll('[data-role-choice]').forEach(function(button) {
      button.setAttribute('aria-pressed', button.getAttribute('data-role-choice') === workspaceRole ? 'true' : 'false');
    });
    document.querySelectorAll('[data-preference-choice]').forEach(function(button) {
      button.setAttribute('aria-pressed', button.getAttribute('data-preference-choice') === workspacePreference ? 'true' : 'false');
    });

    document.getElementById('app-role-title').textContent = role.title;
    document.getElementById('app-role-tag').textContent = role.tag;
    document.getElementById('app-role-summary').textContent = role.summary;
    document.getElementById('app-role-outcome').textContent = role.outcome;
    document.getElementById('app-role-risk').textContent = role.risk;
    document.getElementById('app-role-rhythm').textContent = role.rhythm;

    document.getElementById('app-preference-title').textContent = preference.title;
    document.getElementById('app-preference-tag').textContent = preference.tag;
    document.getElementById('app-preference-summary').textContent = preference.summary;
    document.getElementById('app-guided-deliverable').textContent = preference.deliverable;
    document.getElementById('app-guided-stance').textContent = preference.stance;
    document.getElementById('app-guided-focus').textContent = preference.focusLabel;

    var primaryButton = document.getElementById('app-guided-primary-btn');
    var secondaryButton = document.getElementById('app-guided-secondary-btn');
    primaryButton.textContent = actionLabelForTarget(preference.primaryTarget);
    primaryButton.setAttribute('data-target', preference.primaryTarget);
    secondaryButton.textContent = actionLabelForTarget(preference.secondaryTarget);
    secondaryButton.setAttribute('data-target', preference.secondaryTarget);

    document.getElementById('app-history-copy').textContent = role.historyCopy;
    document.getElementById('app-run-copy').textContent = role.runCopy;
    document.getElementById('app-content-copy').textContent = role.contentCopy;
    var lensTitle = document.getElementById('app-analysis-lens-title');
    var lensNote = document.getElementById('app-analysis-lens-note');
    if (lensTitle) lensTitle.textContent = role.runLensTitle;
    if (lensNote) lensNote.textContent = role.runLensNote + ' ' + preference.summary;

    if (!latestAnalysisRun) {
      if (!analysisHistoryLoaded && currentAccount) {
        setHeroRunSummary('Checking recent runs', 'Loading your recent runs.');
      } else {
        setHeroRunSummary('Ready to queue', role.readyNote);
      }
    }
    if (latestBillingStatus) updateHeroSummary(latestBillingStatus);
    updateHistorySummary(latestAnalysisRun);
    renderAnalysisHistoryList();
    updateContentSummary(latestAnalysisRun);
    var draftTextarea = document.getElementById('app-analysis-kml');
    updateAnalysisPreflight(draftTextarea ? draftTextarea.value : '');
  }

  function setWorkspaceRole(roleKey, options) {
    if (!WORKSPACE_ROLES[roleKey]) return;
    workspaceRole = roleKey;
    if (!options || options.persist !== false) storeUiValue(WORKSPACE_ROLE_STORAGE_KEY, roleKey);
    renderWorkspaceGuidance();
    if (!options || options.alignFocus !== false) setWorkflowFocus(currentPreferenceConfig().focusTarget);
  }

  function setWorkspacePreference(preferenceKey, options) {
    if (!WORKSPACE_PREFERENCES[preferenceKey]) return;
    workspacePreference = preferenceKey;
    if (!options || options.persist !== false) storeUiValue(WORKSPACE_PREFERENCE_STORAGE_KEY, preferenceKey);
    renderWorkspaceGuidance();
    if (!options || options.alignFocus !== false) setWorkflowFocus(currentPreferenceConfig().focusTarget);
  }

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

  function updateHeroSummary(data) {
    var role = currentRoleConfig();
    var preference = currentPreferenceConfig();
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
      runsEl.textContent = data.runs_remaining == null ? '—' : String(data.runs_remaining);
      runsNoteEl.textContent = 'Free-plan limits shown here only activate after sign-in.';
      modeEl.textContent = capabilityHeadline(caps);
      modeNoteEl.textContent = role.label + ' • ' + preference.label + ' • Preview mode only until you authenticate.';
      return;
    }

    planEl.textContent = (caps.label || data.tier || 'Free') + (data.tier_source === 'emulated' ? ' (emulated)' : '');
    planNoteEl.textContent = data.tier_source === 'emulated'
      ? 'Local override for product testing.'
      : 'Based on your account.';
    runsEl.textContent = data.runs_remaining == null ? '—' : String(data.runs_remaining);
    runsNoteEl.textContent = data.runs_remaining == null
      ? 'Quota unavailable in this environment.'
      : 'Remaining analyses before the current limit is reached.';
    modeEl.textContent = capabilityHeadline(caps);
    modeNoteEl.textContent = role.label + ' • ' + preference.label + ' • Retention ' + formatRetention(caps.retention_days) + ' • ' + (caps.api_access ? 'API enabled' : 'API not included');
  }

  function updateHistorySummary(data) {
    var role = currentRoleConfig();
    var statusEl = document.getElementById('app-history-latest-status');
    var noteEl = document.getElementById('app-history-latest-note');
    var instanceEl = document.getElementById('app-history-latest-instance');
    var phaseEl = document.getElementById('app-history-latest-phase');
    var pathEl = document.getElementById('app-history-latest-path');
    if (!statusEl || !noteEl || !instanceEl || !phaseEl || !pathEl) return;

    if (!data) {
      if (!analysisHistoryLoaded && currentAccount) {
        statusEl.textContent = 'Loading recent runs';
        noteEl.textContent = 'Loading your history and checking for active runs.';
        instanceEl.textContent = '…';
        phaseEl.textContent = 'loading';
        pathEl.textContent = role.activePath;
        return;
      }
      statusEl.textContent = 'No runs yet';
      noteEl.textContent = role.emptyHistoryNote;
      instanceEl.textContent = '—';
      phaseEl.textContent = '—';
      pathEl.textContent = role.completedPath;
      return;
    }

    var instanceId = data.instanceId || data.instance_id || '—';
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

  function normalizeAnalysisRun(run) {
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

  function historyRunSortValue(run) {
    return parseStatusTimestamp((run && (run.submittedAt || run.createdTime || run.lastUpdatedTime)) || '') || 0;
  }

  function sortAnalysisHistoryRuns(runs) {
    return (runs || [])
      .map(normalizeAnalysisRun)
      .filter(Boolean)
      .sort(function(a, b) {
        return historyRunSortValue(b) - historyRunSortValue(a);
      });
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

  function historyRunIsActive(run) {
    var runtimeStatus = String(run && run.runtimeStatus || '').trim().toLowerCase();
    return ['completed', 'failed', 'terminated', 'canceled'].indexOf(runtimeStatus) === -1;
  }

  function renderAnalysisHistoryList() {
    var container = document.getElementById('app-history-list');
    if (!container) return;

    container.replaceChildren();
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
      empty.textContent = currentRoleConfig().emptyHistoryNote;
      container.appendChild(empty);
      return;
    }

    analysisHistoryRuns.forEach(function(run) {
      var instanceId = run.instanceId || run.instance_id;
      var runtimeStatus = run.runtimeStatus || 'Pending';
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
        selectAnalysisRun(instanceId, { focus: 'history', resume: historyRunIsActive(run) });
      });

      header.className = 'app-history-item-header';
      title.className = 'app-history-item-title';
      var titleParts = [];
      if (run.aoiCount) titleParts.push(formatCountLabel(run.aoiCount, 'AOI'));
      if (run.totalAreaHa) titleParts.push(Number(run.totalAreaHa).toFixed(1) + ' ha');
      var titleLabel = titleParts.length ? titleParts.join(' · ') : shortInstanceId(instanceId);
      title.textContent = (historyRunIsActive(run) ? 'Resume: ' : '') + titleLabel;
      status.className = 'app-history-item-status';
      status.textContent = runtimeStatus;
      header.appendChild(title);
      header.appendChild(status);

      meta.className = 'app-history-item-meta';
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

  function upsertAnalysisHistoryRun(run) {
    var normalized = normalizeAnalysisRun(run);
    if (!normalized) return;

    var replaced = false;
    analysisHistoryRuns = analysisHistoryRuns.map(function(existing) {
      var existingId = existing.instanceId || existing.instance_id;
      if (existingId !== normalized.instanceId) return existing;
      replaced = true;
      return Object.assign({}, existing, normalized);
    });
    if (!replaced) analysisHistoryRuns.unshift(normalized);
    analysisHistoryRuns = sortAnalysisHistoryRuns(analysisHistoryRuns);
    renderAnalysisHistoryList();
  }

  function selectAnalysisRun(instanceId, options) {
    options = options || {};
    var run = analysisHistoryRuns.find(function(entry) {
      return (entry.instanceId || entry.instance_id) === instanceId;
    });
    if (!run) return;

    selectedAnalysisRunId = instanceId;
    renderAnalysisHistoryList();
    if (options.focus) setWorkflowFocus(options.focus);
    updateRunSelectionLocation(instanceId, options.focus || document.getElementById('app-workflow-stage').getAttribute('data-focus') || 'run');

    stopAnalysisPolling();
    updateAnalysisRun(run);
    resetAnalysisProgress();
    setAnalysisProgressVisible(true);

    var runtimeStatus = run.runtimeStatus || 'Pending';
    var phase = mapAnalysisPhase(run.customStatus, runtimeStatus);
    if (runtimeStatus === 'Completed') {
      setAnalysisStep('complete', 'done');
      updateAnalysisStory('complete', runtimeStatus, run);
      loadRunEvidence(instanceId);
      return;
    }
    if (runtimeStatus === 'Failed' || runtimeStatus === 'Canceled' || runtimeStatus === 'Terminated') {
      setAnalysisStep(phase, 'failed');
      updateAnalysisStory(phase, runtimeStatus, run);
      return;
    }

    setAnalysisStep(phase, 'active');
    updateAnalysisStory(phase, runtimeStatus || 'Pending', run);
    if (options.resume !== false) pollAnalysisRun(instanceId);
  }

  function applyAnalysisHistory(payload, options) {
    options = options || {};
    var locationSelection = readRunSelectionFromLocation();

    if (locationSelection.focus) setWorkflowFocus(locationSelection.focus);

    var normalizedActiveRun = normalizeAnalysisRun(payload && payload.activeRun);
    analysisHistoryRuns = sortAnalysisHistoryRuns(payload && payload.runs);
    if (normalizedActiveRun && !analysisHistoryRuns.some(function(run) {
      return run.instanceId === normalizedActiveRun.instanceId;
    })) {
      analysisHistoryRuns.unshift(normalizedActiveRun);
      analysisHistoryRuns = sortAnalysisHistoryRuns(analysisHistoryRuns);
    }

    var nextSelectedId = options.preferInstanceId || selectedAnalysisRunId || locationSelection.instanceId;
    if (nextSelectedId && !analysisHistoryRuns.some(function(run) { return run.instanceId === nextSelectedId; })) {
      nextSelectedId = null;
    }
    if (!nextSelectedId && normalizedActiveRun) nextSelectedId = normalizedActiveRun.instanceId;
    if (!nextSelectedId && analysisHistoryRuns[0]) nextSelectedId = analysisHistoryRuns[0].instanceId;

    if (!nextSelectedId) {
      selectedAnalysisRunId = null;
      updateRunSelectionLocation('', document.getElementById('app-workflow-stage').getAttribute('data-focus') || 'run');
      stopAnalysisPolling();
      resetAnalysisProgress();
      renderAnalysisHistoryList();
      updateAnalysisRun(null);
      return;
    }

    var selectedRun = analysisHistoryRuns.find(function(run) { return run.instanceId === nextSelectedId; });
    selectAnalysisRun(nextSelectedId, { resume: historyRunIsActive(selectedRun) });
  }

  /* ------------------------------------------------------------------ */
  /*  First-run layout — toggle onboarding vs standard dashboard        */
  /* ------------------------------------------------------------------ */

  function applyFirstRunLayout() {
    var firstRun = document.getElementById('app-first-run-hero');
    var evidenceHero = document.getElementById('app-evidence-hero');
    var historyRail = document.getElementById('app-history-card');
    var workflowStage = document.getElementById('app-workflow-stage');
    var modePill = document.getElementById('app-hero-mode');
    var activeRunPill = document.getElementById('app-hero-active-run');
    if (!firstRun) return;

    var isEmpty = analysisHistoryLoaded && analysisHistoryRuns.length === 0 && !latestAnalysisRun;
    firstRun.hidden = !isEmpty;
    if (evidenceHero) evidenceHero.hidden = isEmpty;

    // Collapse first-load noise: hide history rail + extra pills for new users
    if (historyRail) historyRail.hidden = isEmpty;
    if (workflowStage) workflowStage.classList.toggle('first-run', isEmpty);
    if (modePill) modePill.closest('.app-stat-pill').hidden = isEmpty;
    if (activeRunPill) activeRunPill.closest('.app-stat-pill').hidden = isEmpty;
  }

  /* ------------------------------------------------------------------ */
  /*  Evidence surface — fetches and renders real data for completed runs */
  /* ------------------------------------------------------------------ */

  let evidenceMap = null;
  let evidenceMapLayers = [];
  let evidenceFrameIndex = 0;
  let evidenceLayerMode = 'rgb'; // 'rgb' | 'ndvi'
  let evidencePlayInterval = null;
  let evidenceManifest = null;
  let evidenceAnalysis = null;
  let evidenceInstanceId = null;
  let evidenceMapExpanded = false;

  function expandEvidenceMap() {
    var mapEl = document.getElementById('app-evidence-map');
    var backdrop = document.getElementById('app-map-expanded-backdrop');
    var body = document.getElementById('app-map-expanded-body');
    if (!mapEl || !backdrop || !body || evidenceMapExpanded) return;

    body.appendChild(mapEl);
    backdrop.hidden = false;
    evidenceMapExpanded = true;

    // Sync expanded controls state
    syncExpandedControls();

    setTimeout(function() { if (evidenceMap) evidenceMap.invalidateSize(); }, 100);
    document.addEventListener('keydown', expandedEscHandler);
  }

  function collapseEvidenceMap() {
    var mapEl = document.getElementById('app-evidence-map');
    var backdrop = document.getElementById('app-map-expanded-backdrop');
    var wrap = document.getElementById('app-evidence-map-wrap');
    if (!mapEl || !backdrop || !wrap || !evidenceMapExpanded) return;

    wrap.insertBefore(mapEl, wrap.firstChild);
    backdrop.hidden = true;
    evidenceMapExpanded = false;

    setTimeout(function() { if (evidenceMap) evidenceMap.invalidateSize(); }, 100);
    document.removeEventListener('keydown', expandedEscHandler);
  }

  function expandedEscHandler(e) {
    if (e.key === 'Escape') collapseEvidenceMap();
  }

  function syncExpandedControls() {
    var slider = document.getElementById('app-map-expanded-slider');
    var counter = document.getElementById('app-map-expanded-counter');
    var label = document.getElementById('app-map-expanded-label');
    var rgbBtn = document.getElementById('app-map-expanded-btn-rgb');
    var ndviBtn = document.getElementById('app-map-expanded-btn-ndvi');

    if (slider && evidenceMapLayers.length) {
      slider.max = evidenceMapLayers.length - 1;
      slider.value = evidenceFrameIndex;
    }
    if (counter) counter.textContent = (evidenceFrameIndex + 1) + '/' + evidenceMapLayers.length;
    if (label && evidenceMapLayers[evidenceFrameIndex]) {
      label.textContent = evidenceMapLayers[evidenceFrameIndex].label + ' — ' + evidenceMapLayers[evidenceFrameIndex].info;
    }
    if (rgbBtn) rgbBtn.classList.toggle('active', evidenceLayerMode === 'rgb');
    if (ndviBtn) ndviBtn.classList.toggle('active', evidenceLayerMode === 'ndvi');
  }

  function showEvidenceSurface(visible) {
    var surface = document.getElementById('app-evidence-surface');
    var phaseStatus = document.getElementById('app-content-phase-status');
    if (surface) surface.hidden = !visible;
    if (phaseStatus) phaseStatus.hidden = visible;
  }

  async function loadRunEvidence(instanceId) {
    if (evidenceInstanceId === instanceId && evidenceManifest) return;
    evidenceInstanceId = instanceId;
    evidenceManifest = null;
    evidenceAnalysis = null;
    showEvidenceSurface(true);
    clearEvidencePanels();

    var footerEl = document.getElementById('app-content-footer');
    if (footerEl) footerEl.textContent = 'Loading evidence for run ' + instanceId.slice(0, 8) + '…';

    try {
      await apiDiscoveryReady;
      var manifestRes = await apiFetch('/api/timelapse-data/' + encodeURIComponent(instanceId));
      evidenceManifest = await manifestRes.json();
    } catch (err) {
      if (footerEl) footerEl.textContent = 'Could not load enrichment data: ' + ((err && err.message) || 'unknown error');
      return;
    }

    renderEvidenceNdvi(evidenceManifest);
    renderEvidenceWeather(evidenceManifest);
    renderEvidenceChangeDetection(evidenceManifest);
    initEvidenceMap(evidenceManifest);

    // Load saved AI analysis (non-blocking)
    loadSavedAnalysis(instanceId);

    // Show EUDR block for eudr role
    var eudrBlock = document.getElementById('app-evidence-eudr-block');
    if (eudrBlock) eudrBlock.hidden = (workspaceRole !== 'eudr');

    // Show AI block if tier supports it
    var aiBlock = document.getElementById('app-evidence-ai-block');
    if (aiBlock) {
      aiBlock.hidden = !(latestBillingStatus && latestBillingStatus.capabilities && latestBillingStatus.capabilities.ai_insights);
    }

    if (footerEl) {
      footerEl.textContent = 'Evidence loaded for run ' + instanceId.slice(0, 8) + '.';
    }
  }

  function clearEvidencePanels() {
    var ids = ['app-evidence-ndvi-grid', 'app-evidence-weather-grid', 'app-evidence-change-list', 'app-evidence-ai-content', 'app-evidence-eudr-content'];
    ids.forEach(function(id) { var el = document.getElementById(id); if (el) el.textContent = ''; });
    var noteEl = document.getElementById('app-evidence-ndvi-note');
    if (noteEl) noteEl.textContent = '';
    var canvases = ['app-evidence-ndvi-canvas', 'app-evidence-weather-canvas'];
    canvases.forEach(function(id) {
      var c = document.getElementById(id);
      if (c) { var ctx = c.getContext('2d'); ctx.clearRect(0, 0, c.width, c.height); }
    });
    if (evidencePlayInterval) { clearInterval(evidencePlayInterval); evidencePlayInterval = null; }
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
    stats.forEach(function(s) { grid.appendChild(createStatEl(s[0], s[1], s[2])); });
  }

  function createCallout(tone, message) {
    var div = document.createElement('div');
    div.className = 'app-callout';
    div.setAttribute('data-tone', tone);
    div.textContent = message;
    return div;
  }

  function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* ---- NDVI evidence ---- */
  function renderEvidenceNdvi(manifest) {
    var grid = document.getElementById('app-evidence-ndvi-grid');
    var note = document.getElementById('app-evidence-ndvi-note');
    var canvas = document.getElementById('app-evidence-ndvi-canvas');
    if (!grid) return;

    var ndvi = (manifest.ndvi_stats || []).filter(function(f) { return f != null; });
    if (!ndvi.length) {
      setStatGrid(grid, [['Status', 'No NDVI data', '']]);
      return;
    }

    var means = ndvi.map(function(f) { return f.mean; }).filter(function(v) { return v != null && !isNaN(v); });
    var overallMean = means.length ? (means.reduce(function(a, b) { return a + b; }, 0) / means.length) : null;
    var overallMin = means.length ? Math.min.apply(null, means) : null;
    var overallMax = means.length ? Math.max.apply(null, means) : null;

    // Trajectory — prefer backend season-aware change detection
    var trajectory = 'Stable';
    var trajectoryTone = '';
    var cdSummary = manifest.change_detection && manifest.change_detection.summary;
    if (cdSummary && cdSummary.trajectory) {
      var t = cdSummary.trajectory;
      if (t === 'Improving') { trajectory = 'Improving ↑'; trajectoryTone = 'positive'; }
      else if (t === 'Declining') { trajectory = 'Declining ↓'; trajectoryTone = 'negative'; }
      else { trajectory = 'Stable'; trajectoryTone = ''; }
    } else if (means.length >= 4) {
      var firstHalf = means.slice(0, Math.floor(means.length / 2));
      var secondHalf = means.slice(Math.floor(means.length / 2));
      var avgFirst = firstHalf.reduce(function(a, b) { return a + b; }, 0) / firstHalf.length;
      var avgSecond = secondHalf.reduce(function(a, b) { return a + b; }, 0) / secondHalf.length;
      var delta = avgSecond - avgFirst;
      if (delta > 0.05) { trajectory = 'Improving ↑'; trajectoryTone = 'positive'; }
      else if (delta < -0.05) { trajectory = 'Declining ↓'; trajectoryTone = 'negative'; }
    }

    var meanLabel = overallMean != null ? overallMean.toFixed(3) : '\u2014';
    var meanTone = '';
    if (overallMean != null && overallMean > 0.4) meanTone = 'positive';
    else if (overallMean != null && overallMean < 0.2) meanTone = 'negative';
    var rangeLabel = overallMin != null ? overallMin.toFixed(2) + ' \u2013 ' + overallMax.toFixed(2) : '\u2014';

    setStatGrid(grid, [
      ['Mean NDVI', meanLabel, meanTone],
      ['Range', rangeLabel, ''],
      ['Trajectory', trajectory, trajectoryTone]
    ]);

    if (note) note.textContent = means.length + ' frames sampled across the analysis period.';

    // Draw sparkline
    if (canvas && means.length > 1) drawNdviSparkline(canvas, ndvi);
  }

  function drawNdviSparkline(canvas, ndviStats) {
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.clientWidth;
    var h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    var means = ndviStats.map(function(f) { return f ? f.mean : null; });
    var valid = means.filter(function(v) { return v != null && !isNaN(v); });
    if (valid.length < 2) return;
    var minV = Math.min.apply(null, valid) - 0.05;
    var maxV = Math.max.apply(null, valid) + 0.05;
    var range = maxV - minV || 1;
    var pad = 4;

    // Background
    ctx.fillStyle = 'rgba(13,17,23,.4)';
    ctx.beginPath();
    ctx.roundRect(0, 0, w, h, 8);
    ctx.fill();

    // Line
    ctx.strokeStyle = 'rgba(63,185,80,.8)';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    var drawn = false;
    for (var i = 0; i < means.length; i++) {
      if (means[i] == null || isNaN(means[i])) continue;
      var x = pad + (i / (means.length - 1)) * (w - 2 * pad);
      var y = h - pad - ((means[i] - minV) / range) * (h - 2 * pad);
      if (!drawn) { ctx.moveTo(x, y); drawn = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Drop markers
    ctx.fillStyle = 'rgba(248,81,73,.9)';
    for (var j = 1; j < means.length; j++) {
      if (means[j] == null || means[j - 1] == null) continue;
      var drop = means[j] - means[j - 1];
      if (drop <= -0.1) {
        var dx = pad + (j / (means.length - 1)) * (w - 2 * pad);
        var dy = h - pad - ((means[j] - minV) / range) * (h - 2 * pad);
        ctx.beginPath();
        ctx.arc(dx, dy, 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  /* ---- Weather evidence ---- */
  function renderEvidenceWeather(manifest) {
    var grid = document.getElementById('app-evidence-weather-grid');
    var canvas = document.getElementById('app-evidence-weather-canvas');
    if (!grid) return;

    var monthly = manifest.weather_monthly;
    var daily = manifest.weather_daily;
    if (!monthly && !daily) {
      setStatGrid(grid, [['Status', 'No weather data', '']]);
      return;
    }

    var temps = [];
    var precips = [];
    var source = [];

    // weather_monthly may be { labels, temp, precip } parallel arrays
    if (monthly && monthly.labels && Array.isArray(monthly.labels)) {
      source = monthly.labels.map(function(lbl, i) {
        return {
          label: lbl,
          temperature: (monthly.temp && monthly.temp[i] != null) ? monthly.temp[i] : null,
          precipitation: (monthly.precip && monthly.precip[i] != null) ? monthly.precip[i] : null
        };
      });
    } else if (Array.isArray(monthly)) {
      source = monthly;
    }

    if (!source.length && daily) {
      // aggregate daily to monthly — daily may be { dates, temp, precip }
      var byMonth = {};
      var dates = daily.dates || daily.time || [];
      var dTemps = daily.temp || daily.temperature_2m_mean || [];
      var dPrecip = daily.precip || daily.precipitation_sum || [];
      dates.forEach(function(d, i) {
        var key = d.slice(0, 7);
        if (!byMonth[key]) byMonth[key] = { temps: [], precips: [] };
        if (dTemps[i] != null) byMonth[key].temps.push(dTemps[i]);
        if (dPrecip[i] != null) byMonth[key].precips.push(dPrecip[i]);
      });
      source = Object.keys(byMonth).sort().map(function(key) {
        var m = byMonth[key];
        return {
          label: key,
          temperature: m.temps.length ? m.temps.reduce(function(a, b) { return a + b; }, 0) / m.temps.length : null,
          precipitation: m.precips.length ? m.precips.reduce(function(a, b) { return a + b; }, 0) : null
        };
      });
    }

    source.forEach(function(m) {
      if (m.temperature != null) temps.push(m.temperature);
      if (m.precipitation != null) precips.push(m.precipitation);
    });

    var avgTemp = temps.length ? (temps.reduce(function(a, b) { return a + b; }, 0) / temps.length) : null;
    var totalPrecip = precips.reduce(function(a, b) { return a + b; }, 0);

    setStatGrid(grid, [
      ['Avg temp', avgTemp != null ? avgTemp.toFixed(1) + '\u00B0C' : '\u2014', ''],
      ['Total precip', totalPrecip ? Math.round(totalPrecip) + ' mm' : '\u2014', ''],
      ['Months', source.length + ' months', '']
    ]);

    if (canvas && source.length > 1) drawWeatherSparkline(canvas, source);
  }

  function drawWeatherSparkline(canvas, monthly) {
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.clientWidth;
    var h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    var pad = 4;

    ctx.fillStyle = 'rgba(13,17,23,.4)';
    ctx.beginPath();
    ctx.roundRect(0, 0, w, h, 8);
    ctx.fill();

    var temps = monthly.map(function(m) { return m.temperature; });
    var precips = monthly.map(function(m) { return m.precipitation; });
    var validTemps = temps.filter(function(v) { return v != null; });
    var validPrecips = precips.filter(function(v) { return v != null; });
    var maxPrecip = validPrecips.length ? Math.max.apply(null, validPrecips) : 1;
    var minT = validTemps.length ? Math.min.apply(null, validTemps) - 2 : 0;
    var maxT = validTemps.length ? Math.max.apply(null, validTemps) + 2 : 30;

    // Precipitation bars
    var barW = Math.max(2, (w - 2 * pad) / monthly.length - 1);
    ctx.fillStyle = 'rgba(88,166,255,.35)';
    for (var i = 0; i < precips.length; i++) {
      if (precips[i] == null) continue;
      var bx = pad + (i / monthly.length) * (w - 2 * pad);
      var bh = (precips[i] / (maxPrecip || 1)) * (h - 2 * pad) * 0.8;
      ctx.fillRect(bx, h - pad - bh, barW, bh);
    }

    // Temperature line
    ctx.strokeStyle = 'rgba(210,153,34,.9)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    var drawn = false;
    for (var j = 0; j < temps.length; j++) {
      if (temps[j] == null) continue;
      var tx = pad + ((j + 0.5) / monthly.length) * (w - 2 * pad);
      var ty = h - pad - ((temps[j] - minT) / (maxT - minT)) * (h - 2 * pad);
      if (!drawn) { ctx.moveTo(tx, ty); drawn = true; } else ctx.lineTo(tx, ty);
    }
    ctx.stroke();
  }

  /* ---- Change detection ---- */
  function renderEvidenceChangeDetection(manifest) {
    var block = document.getElementById('app-evidence-change-block');
    var list = document.getElementById('app-evidence-change-list');
    if (!block || !list) return;

    var cd = manifest.change_detection;
    if (!cd || (!cd.season_changes && !cd.significant_changes && !cd.events && !cd.summary)) {
      block.hidden = true;
      return;
    }

    block.hidden = false;
    var items = cd.season_changes || cd.significant_changes || cd.events || [];

    // Summary may be an object { comparisons, total_loss_ha, total_gain_ha, avg_mean_delta, trajectory }
    if (cd.summary) {
      var s = cd.summary;
      var summaryText = typeof s === 'string' ? s :
        (s.trajectory || 'Stable') + ' \u2014 ' + (s.comparisons || 0) + ' comparisons, ' +
        'net loss ' + (s.total_loss_ha ? s.total_loss_ha.toFixed(0) + ' ha' : '\u2014') +
        ', net gain ' + (s.total_gain_ha ? s.total_gain_ha.toFixed(0) + ' ha' : '\u2014');
      var summaryDiv = document.createElement('div');
      summaryDiv.className = 'app-evidence-change-item positive';
      summaryDiv.textContent = summaryText;
      list.appendChild(summaryDiv);
    }

    // Show notable season changes (loss_pct > 20% or gain_pct > 20%)
    var notable = items.filter(function(item) {
      return typeof item === 'object' && (item.loss_pct > 20 || item.gain_pct > 20);
    });
    if (!notable.length && items.length > 3) notable = items.slice(0, 5);
    else if (!notable.length) notable = items;

    notable.forEach(function(item) {
      var text;
      if (typeof item === 'string') {
        text = item;
      } else if (item.label) {
        var parts = [item.label];
        if (item.mean_delta != null) parts.push('Δ ' + (item.mean_delta > 0 ? '+' : '') + item.mean_delta.toFixed(3));
        if (item.loss_pct != null) parts.push('loss ' + item.loss_pct + '%');
        if (item.gain_pct != null) parts.push('gain ' + item.gain_pct + '%');
        text = parts.join(' — ');
      } else {
        text = item.description || item.text || JSON.stringify(item);
      }
      var cls = 'app-evidence-change-item';
      if (typeof item === 'object' && (item.gain_pct > item.loss_pct || item.mean_delta > 0.02)) cls += ' positive';
      var el = document.createElement('div');
      el.className = cls;
      el.textContent = text;
      list.appendChild(el);
    });
  }

  /* ---- Map viewer ---- */
  function initEvidenceMap(manifest) {
    var container = document.getElementById('app-evidence-map');
    var overlay = document.getElementById('app-evidence-map-overlay');
    var controls = document.getElementById('app-evidence-frame-controls');
    if (!container) return;

    // Clean up old map
    if (evidenceMap) { evidenceMap.remove(); evidenceMap = null; }
    evidenceMapLayers = [];
    evidenceFrameIndex = 0;
    if (evidencePlayInterval) { clearInterval(evidencePlayInterval); evidencePlayInterval = null; }

    var center = manifest.center || manifest.coords;
    if (!center) {
      if (overlay) overlay.textContent = 'No location data available.';
      return;
    }

    var lat = Array.isArray(center) ? center[0] : center.lat || center.latitude;
    var lon = Array.isArray(center) ? center[1] : center.lon || center.longitude;
    if (!lat || !lon) {
      if (overlay) overlay.textContent = 'Invalid coordinates in manifest.';
      return;
    }

    evidenceMap = L.map(container, { zoomControl: true, attributionControl: false }).setView([lat, lon], 13);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 18
    }).addTo(evidenceMap);

    // AOI polygon outlines (coords are [lon, lat] GeoJSON; Leaflet needs [lat, lon])
    // Multi-AOI runs concatenate all rings; split on ring-closure (first == last point)
    if (manifest.coords && Array.isArray(manifest.coords)) {
      try {
        var rings = [];
        var ringStart = 0;
        for (var ci = ringStart + 3; ci < manifest.coords.length; ci++) {
          if (Math.abs(manifest.coords[ci][0] - manifest.coords[ringStart][0]) < 1e-5 &&
              Math.abs(manifest.coords[ci][1] - manifest.coords[ringStart][1]) < 1e-5) {
            rings.push(manifest.coords.slice(ringStart, ci + 1));
            ringStart = ci + 1;
            ci = ringStart + 2;
          }
        }
        if (ringStart < manifest.coords.length) rings.push(manifest.coords.slice(ringStart));
        if (!rings.length) rings.push(manifest.coords);

        var allBounds = L.latLngBounds([]);
        rings.forEach(function(ring) {
          var ll = ring.map(function(c) { return [c[1], c[0]]; });
          L.polygon(ll, { color: 'rgba(88,166,255,.7)', weight: 2, fillOpacity: 0.05 }).addTo(evidenceMap);
          allBounds.extend(L.polygon(ll).getBounds());
        });
        evidenceMap.fitBounds(allBounds.pad(0.1));
      } catch (e) { /* skip polygon */ }
    }

    if (overlay) overlay.hidden = true;

    // Add PC timelapse frames if search_ids available
    var searchIds = manifest.search_ids || [];
    var ndviSearchIds = manifest.ndvi_search_ids || [];
    var framePlan = manifest.frame_plan || [];

    if (searchIds.length && framePlan.length) {
      buildEvidenceFrames(framePlan, searchIds, ndviSearchIds);
      if (controls) controls.hidden = false;
    } else if (controls) {
      controls.hidden = true;
    }

    // Force resize
    setTimeout(function() { if (evidenceMap) evidenceMap.invalidateSize(); }, 200);
  }

  function pcTileUrl(searchId, collection, asset) {
    asset = asset || 'visual';
    return 'https://planetarycomputer.microsoft.com/api/data/v1/mosaic/tiles/' +
      encodeURIComponent(searchId) + '/WebMercatorQuad/{z}/{x}/{y}@2x?' +
      'collection=' + encodeURIComponent(collection) + '&assets=' + encodeURIComponent(asset);
  }

  function pcNdviTileUrl(searchId) {
    return 'https://planetarycomputer.microsoft.com/api/data/v1/mosaic/tiles/' +
      encodeURIComponent(searchId) + '/WebMercatorQuad/{z}/{x}/{y}@2x?' +
      'collection=sentinel-2-l2a&expression=(B08-B04)/(B08%2BB04)&rescale=-0.2,0.8&colormap_name=rdylgn';
  }

  function buildEvidenceFrames(framePlan, searchIds, ndviSearchIds) {
    evidenceMapLayers = [];
    var slider = document.getElementById('app-map-frame-slider');
    if (slider) { slider.max = framePlan.length - 1; slider.value = 0; }

    framePlan.forEach(function(frame, idx) {
      var sid = searchIds[idx];
      var ndviSid = ndviSearchIds[idx] || sid;
      var collection = frame.collection || 'sentinel-2-l2a';
      var asset = collection.indexOf('naip') >= 0 ? 'image' : 'visual';

      var rgbLayer = null;
      var ndviLayer = null;
      if (sid) {
        rgbLayer = L.tileLayer(pcTileUrl(sid, collection, asset), { maxZoom: 18, opacity: 0 });
        rgbLayer.addTo(evidenceMap);
      }
      if (ndviSid && collection.indexOf('sentinel') >= 0) {
        ndviLayer = L.tileLayer(pcNdviTileUrl(ndviSid), { maxZoom: 18, opacity: 0 });
        ndviLayer.addTo(evidenceMap);
      }

      evidenceMapLayers.push({
        rgb: rgbLayer,
        ndvi: ndviLayer,
        label: frame.label || ('Frame ' + (idx + 1)),
        info: [collection, frame.start_date, frame.end_date].filter(Boolean).join(' | ')
      });
    });

    showEvidenceFrame(0);
  }

  function showEvidenceFrame(idx) {
    if (idx < 0 || idx >= evidenceMapLayers.length) return;
    evidenceFrameIndex = idx;

    evidenceMapLayers.forEach(function(frame, i) {
      var showRgb = (i === idx && evidenceLayerMode === 'rgb');
      var showNdvi = (i === idx && evidenceLayerMode === 'ndvi');
      if (frame.rgb) frame.rgb.setOpacity(showRgb ? 1 : 0);
      if (frame.ndvi) frame.ndvi.setOpacity(showNdvi ? 1 : 0);
    });

    var slider = document.getElementById('app-map-frame-slider');
    var counter = document.getElementById('app-map-frame-counter');
    var label = document.getElementById('app-map-frame-label');
    if (slider) slider.value = idx;
    if (counter) counter.textContent = (idx + 1) + '/' + evidenceMapLayers.length;
    if (label) label.textContent = evidenceMapLayers[idx].label + ' — ' + evidenceMapLayers[idx].info;

    // Sync expanded controls if open
    if (evidenceMapExpanded) syncExpandedControls();
  }

  function toggleEvidencePlay() {
    var btn = document.getElementById('app-map-play-btn');
    var expBtn = document.getElementById('app-map-expanded-play-btn');
    if (evidencePlayInterval) {
      clearInterval(evidencePlayInterval);
      evidencePlayInterval = null;
      if (btn) btn.textContent = '▶ Play';
      if (expBtn) expBtn.textContent = '▶ Play';
      return;
    }
    if (btn) btn.textContent = '⏸ Pause';
    if (expBtn) expBtn.textContent = '⏸ Pause';
    evidencePlayInterval = setInterval(function() {
      var next = (evidenceFrameIndex + 1) % evidenceMapLayers.length;
      showEvidenceFrame(next);
    }, 1500);
  }

  /* ---- AI analysis ---- */
  async function loadSavedAnalysis(instanceId) {
    var aiBlock = document.getElementById('app-evidence-ai-block');
    var content = document.getElementById('app-evidence-ai-content');
    if (!aiBlock || !content) return;

    try {
      await apiDiscoveryReady;
      var res = await apiFetch('/api/timelapse-analysis-load/' + encodeURIComponent(instanceId));
      evidenceAnalysis = await res.json();
      if (evidenceAnalysis && (evidenceAnalysis.observations || evidenceAnalysis.summary)) {
        aiBlock.hidden = false;
        renderEvidenceAnalysis(evidenceAnalysis);
      }
    } catch (e) { /* ignore — no saved analysis yet */ }
  }

  async function requestAiAnalysis() {
    var loading = document.getElementById('app-evidence-ai-loading');
    var content = document.getElementById('app-evidence-ai-content');
    var btn = document.getElementById('app-evidence-ai-btn');
    if (!loading || !content || !evidenceManifest) return;

    var originalLabel = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Analyzing…'; }
    loading.hidden = false;
    content.textContent = '';

    try {
      await apiDiscoveryReady;

      var ndviTimeseries = (evidenceManifest.ndvi_stats || []).map(function(f, i) {
        if (!f) return null;
        var fp = (evidenceManifest.frame_plan || [])[i] || {};
        return { date: f.datetime || fp.label, mean: f.mean, min: f.min, max: f.max, year: fp.year, season: fp.season };
      }).filter(Boolean);

      // weather_monthly may be { labels, temp, precip } parallel arrays
      var wm = evidenceManifest.weather_monthly;
      var weatherTimeseries = [];
      if (wm && wm.labels && Array.isArray(wm.labels)) {
        weatherTimeseries = wm.labels.map(function(lbl, i) {
          return { month_index: i, label: lbl, temperature: wm.temp ? wm.temp[i] : null, precipitation: wm.precip ? wm.precip[i] : null };
        });
      } else if (Array.isArray(wm)) {
        weatherTimeseries = wm.map(function(m, i) {
          return { month_index: i, temperature: m.temperature, precipitation: m.precipitation };
        });
      }

      var center = evidenceManifest.center || evidenceManifest.coords;
      var lat = Array.isArray(center) ? center[0] : (center && center.lat) || 0;
      var lon = Array.isArray(center) ? center[1] : (center && center.lon) || 0;

      var body = {
        context: {
          aoi_name: 'Analysis area',
          latitude: lat,
          longitude: lon,
          frame_count: ndviTimeseries.length,
          date_range_start: ndviTimeseries.length ? ndviTimeseries[0].date : '',
          date_range_end: ndviTimeseries.length ? ndviTimeseries[ndviTimeseries.length - 1].date : '',
          ndvi_timeseries: ndviTimeseries,
          weather_timeseries: weatherTimeseries
        }
      };

      var res = await apiFetch('/api/timelapse-analysis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      evidenceAnalysis = await res.json();
      renderEvidenceAnalysis(evidenceAnalysis);

      // Save the analysis
      apiFetch('/api/timelapse-analysis-save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instance_id: evidenceInstanceId, analysis: evidenceAnalysis })
      }).catch(function() {});
    } catch (err) {
      content.textContent = '';
      content.appendChild(createCallout('error', (err && err.message) || 'Could not run AI analysis.'));
    } finally {
      loading.hidden = true;
      if (btn) { btn.disabled = false; btn.textContent = originalLabel; }
    }
  }

  function renderEvidenceAnalysis(analysis) {
    var content = document.getElementById('app-evidence-ai-content');
    if (!content) return;
    content.textContent = '';

    if (analysis.summary) {
      var summaryEl = document.createElement('div');
      summaryEl.className = 'app-evidence-summary';
      summaryEl.textContent = analysis.summary;
      content.appendChild(summaryEl);
    }

    (analysis.observations || []).forEach(function(obs) {
      var card = document.createElement('div');
      card.className = 'app-evidence-obs';

      var header = document.createElement('div');
      header.className = 'app-evidence-obs-header';

      var cat = document.createElement('span');
      cat.className = 'app-evidence-obs-category';
      cat.textContent = (obs.category || 'observation').replace(/_/g, ' ');

      var sev = document.createElement('span');
      sev.className = 'app-evidence-obs-severity severity-' + (obs.severity || 'normal');
      sev.textContent = obs.severity || 'normal';

      header.appendChild(cat);
      header.appendChild(sev);
      card.appendChild(header);

      if (obs.description) {
        var desc = document.createElement('p');
        desc.textContent = obs.description;
        card.appendChild(desc);
      }
      if (obs.recommendation) {
        var rec = document.createElement('p');
        rec.className = 'obs-recommendation';
        rec.textContent = '💡 ' + obs.recommendation;
        card.appendChild(rec);
      }

      content.appendChild(card);
    });
  }

  /* ---- EUDR assessment ---- */
  async function requestEudrAssessment() {
    var loading = document.getElementById('app-evidence-eudr-loading');
    var content = document.getElementById('app-evidence-eudr-content');
    var btn = document.getElementById('app-evidence-eudr-btn');
    if (!loading || !content || !evidenceManifest) return;

    if (btn) btn.disabled = true;
    loading.hidden = false;
    content.textContent = '';

    try {
      await apiDiscoveryReady;

      var ndviTimeseries = (evidenceManifest.ndvi_stats || []).map(function(f) {
        return { date: f.date || f.label, mean: f.mean, min: f.min, max: f.max, year: f.year, season: f.season };
      });
      var center = evidenceManifest.center || evidenceManifest.coords;
      var lat = Array.isArray(center) ? center[0] : (center && center.lat) || 0;
      var lon = Array.isArray(center) ? center[1] : (center && center.lon) || 0;

      var body = {
        context: {
          aoi_name: 'Analysis area',
          latitude: lat,
          longitude: lon,
          ndvi_timeseries: ndviTimeseries,
          reference_date: '2020-12-31'
        }
      };

      var res = await apiFetch('/api/eudr-assessment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      var result = await res.json();
      var cls = (result.compliant || result.deforestation_free) ? 'compliant' : 'non-compliant';
      var label = cls === 'compliant' ? '\u2713 No deforestation detected since Dec 2020' : '\u26A0 Potential deforestation detected';
      content.textContent = '';
      var resultDiv = document.createElement('div');
      resultDiv.className = 'app-evidence-eudr-result ' + cls;
      var strong = document.createElement('strong');
      strong.textContent = label;
      resultDiv.appendChild(strong);
      if (result.summary) {
        var p = document.createElement('p');
        p.textContent = result.summary;
        resultDiv.appendChild(p);
      }
      content.appendChild(resultDiv);
    } catch (err) {
      content.textContent = '';
      content.appendChild(createCallout('error', (err && err.message) || 'Could not run EUDR assessment.'));
    } finally {
      loading.hidden = true;
      if (btn) btn.disabled = false;
    }
  }

  /* ------------------------------------------------------------------ */
  /*  END Evidence surface                                               */
  /* ------------------------------------------------------------------ */

  function updateContentSummary(data) {
    var role = currentRoleConfig();
    var imageryEl = document.getElementById('app-content-imagery');
    var imageryNoteEl = document.getElementById('app-content-imagery-note');
    var enrichmentEl = document.getElementById('app-content-enrichment');
    var enrichmentNoteEl = document.getElementById('app-content-enrichment-note');
    var exportsEl = document.getElementById('app-content-exports');
    var exportsNoteEl = document.getElementById('app-content-exports-note');
    if (!imageryEl || !imageryNoteEl || !enrichmentEl || !enrichmentNoteEl || !exportsEl || !exportsNoteEl) return;

    if (!data) {
      showEvidenceSurface(false);
      imageryEl.textContent = role.emptyContent.imageryTitle;
      imageryNoteEl.textContent = role.emptyContent.imageryNote;
      enrichmentEl.textContent = role.emptyContent.enrichmentTitle;
      enrichmentNoteEl.textContent = role.emptyContent.enrichmentNote;
      exportsEl.textContent = role.emptyContent.exportsTitle;
      exportsNoteEl.textContent = role.emptyContent.exportsNote;
      return;
    }

    var runtimeStatus = data.runtimeStatus || 'Pending';
    var phase = (data.customStatus && data.customStatus.phase) || 'queued';

    if (runtimeStatus === 'Completed') {
      // Evidence surface is loaded by loadRunEvidence(), triggered from selectAnalysisRun
      // Phase status is hidden; evidence surface is shown
      return;
    }

    showEvidenceSurface(false);

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
      exportsEl.textContent = 'No outputs yet';
      exportsNoteEl.textContent = 'Saved artifacts stay unavailable until a real run starts producing outputs.';
      return;
    }

    if (phase === 'acquisition') {
      imageryEl.textContent = 'Scene search underway';
      imageryNoteEl.textContent = 'NAIP and Sentinel-2 discovery is in progress so the run can pick the right source imagery.';
      enrichmentEl.textContent = 'Queued behind acquisition';
      enrichmentNoteEl.textContent = 'Context layers are staged after the imagery stack is selected.';
      exportsEl.textContent = 'Awaiting artefacts';
      exportsNoteEl.textContent = 'There is nothing to export until imagery is actually acquired.';
      return;
    }

    if (phase === 'fulfilment') {
      imageryEl.textContent = 'Clipping and reprojection';
      imageryNoteEl.textContent = 'The pipeline is producing imagery assets for your analysis.';
      enrichmentEl.textContent = 'Preparing next';
      enrichmentNoteEl.textContent = 'NDVI and weather context will follow immediately after fulfilment finishes.';
      exportsEl.textContent = 'Outputs staging next';
      exportsNoteEl.textContent = 'The run is close enough that saved outputs should feel tangible, not hypothetical.';
      return;
    }

    imageryEl.textContent = 'Imagery stack stabilizing';
    imageryNoteEl.textContent = 'Core imagery is in place and the workspace is adding the last supporting layers.';
    enrichmentEl.textContent = 'Context packaging';
    enrichmentNoteEl.textContent = 'NDVI, weather, and derived context are being assembled for the run detail experience.';
    exportsEl.textContent = 'Preparing results view';
    exportsNoteEl.textContent = 'Saved outputs, exports, and revisit paths will be available shortly.';
  }

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

    if (!data) {
      submittedEl.textContent = '—';
      submittedNoteEl.textContent = 'Run details restore here after reload.';
      scopeEl.textContent = '—';
      scopeNoteEl.textContent = 'Feature and AOI counts appear when known.';
      deliveryEl.textContent = '—';
      deliveryNoteEl.textContent = 'Failure counts and tracked artifacts will appear here.';
      linkLabelEl.textContent = 'Dashboard state';
      linkEl.href = '/app/';
      linkEl.textContent = 'Open dashboard';
      document.querySelectorAll('[data-export-format]').forEach(function(button) {
        button.disabled = true;
      });
      return;
    }

    var runtimeStatus = data.runtimeStatus || 'Pending';
    var timing = summarizeRunTiming(data);
    var scopeSummary = [
      formatCountLabel(data.featureCount, 'feature'),
      formatCountLabel(data.aoiCount, 'AOI'),
      data.processingMode,
    ].filter(Boolean).join(' • ');
    var scopeNote = [
      data.maxSpreadKm != null ? 'Spread ' + formatDistance(data.maxSpreadKm) : null,
      data.totalAreaHa != null ? 'Area ' + formatHectares(data.totalAreaHa) : null,
      providerLabel(data.providerName),
    ].filter(Boolean).join(' • ');
    var failureSummary = summarizeFailureCounts(data.partialFailures);
    var artifactCount = data.artifactCount || 0;

    submittedEl.textContent = formatHistoryTimestamp(data.submittedAt || data.createdTime);
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
    linkEl.href = selectedRunPermalink(data.instanceId || data.instance_id, 'run');
    linkEl.textContent = 'Open this run directly';

    document.querySelectorAll('[data-export-format]').forEach(function(button) {
      button.disabled = runtimeStatus !== 'Completed';
    });
    var evidenceExportNote = document.getElementById('app-evidence-export-note');
    if (evidenceExportNote) {
      evidenceExportNote.textContent = runtimeStatus === 'Completed'
        ? 'Download GeoJSON, CSV, or PDF for this completed run.'
        : 'Exports unlock when the selected run completes.';
    }
  }

  async function downloadRunExport(format) {
    var run = latestAnalysisRun;
    if (!run || !(run.instanceId || run.instance_id)) {
      setAnalysisStatus('Select a run first.', 'error');
      return;
    }

    var instanceId = run.instanceId || run.instance_id;
    if ((run.runtimeStatus || '') !== 'Completed') {
      setAnalysisStatus('Exports become available once the selected run completes.', 'info');
      return;
    }

    var button = document.querySelector('[data-export-format="' + format + '"]');
    var originalText = button ? button.textContent : format.toUpperCase();
    if (button) {
      button.disabled = true;
      button.textContent = 'Preparing…';
    }

    try {
      await apiDiscoveryReady;
      var res = await apiFetch('/api/export/' + encodeURIComponent(instanceId) + '/' + format);
      var blob = await res.blob();
      var blobUrl = URL.createObjectURL(blob);
      var link = document.createElement('a');
      link.href = blobUrl;
      link.download = parseDownloadFilename(res, 'canopex_' + instanceId + '.' + format);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(blobUrl);
      setAnalysisStatus(format.toUpperCase() + ' export downloaded for the selected run.', 'success');
    } catch (err) {
      setAnalysisStatus((err && err.message) || 'Could not download the selected export.', 'error');
    } finally {
      if (button) {
        button.disabled = (latestAnalysisRun && latestAnalysisRun.runtimeStatus !== 'Completed');
        button.textContent = originalText;
      }
    }
  }

  function updateAnalysisRun(data) {
    var panel = document.getElementById('app-analysis-run');
    latestAnalysisRun = data || null;
    if (!panel) return;
    if (!data) {
      panel.hidden = true;
      setHeroRunSummary('Ready to queue', currentRoleConfig().readyNote);
      updateHistorySummary(null);
      updateRunDetail(null);
      updateContentSummary(null);
      return;
    }
    panel.hidden = false;
    var instanceId = data.instanceId || data.instance_id || '—';
    var runtimeStatus = data.runtimeStatus || 'queued';
    var phase = displayAnalysisPhase(data.customStatus, runtimeStatus);
    var timing = summarizeRunTiming(data);
    document.getElementById('app-analysis-instance').textContent = instanceId;
    document.getElementById('app-analysis-runtime').textContent = runtimeStatus;
    document.getElementById('app-analysis-phase').textContent = phase;
    setHeroRunSummary(
      runtimeStatus,
      runtimeStatus === 'Completed'
        ? 'Pipeline finished successfully — results are ready.'
        : 'Current phase: ' + phase + '.' + (timing.elapsed ? ' Elapsed ' + timing.elapsed + '.' : '')
    );
    updateHistorySummary(data);
    updateRunDetail(data);
    updateContentSummary(data);
  }

  function resetAnalysisProgress() {
    var progress = document.getElementById('app-analysis-progress');
    if (!progress) return;
    progress.hidden = true;
    progress.querySelectorAll('.pipeline-step').forEach(function(el) {
      el.className = 'pipeline-step';
      var icon = el.querySelector('.step-icon');
      if (icon) icon.textContent = '○';
    });
  }

  function setAnalysisProgressVisible(visible) {
    var progress = document.getElementById('app-analysis-progress');
    if (!progress) return;
    progress.hidden = !visible;
  }

  function setAnalysisStep(phase, state) {
    var steps = document.querySelectorAll('#app-analysis-progress .pipeline-step');
    steps.forEach(function(el) {
      var stepPhase = el.getAttribute('data-phase');
      var icon = el.querySelector('.step-icon');
      el.className = 'pipeline-step';

      if (stepPhase === phase) {
        if (state === 'failed') el.classList.add('failed');
        else if (state === 'done') el.classList.add('done');
        else el.classList.add('active');
        if (!icon) return;
        if (state === 'done') {
          icon.textContent = '✓';
        } else if (state === 'failed') {
          icon.textContent = '✗';
        } else {
          icon.replaceChildren();
          var spinner = document.createElement('span');
          spinner.className = 'spinner';
          icon.appendChild(spinner);
        }
        return;
      }

      if (!icon) return;
      var stepIndex = ANALYSIS_PHASES.indexOf(stepPhase);
      var currentIndex = ANALYSIS_PHASES.indexOf(phase);
      if (stepIndex > -1 && currentIndex > -1 && stepIndex < currentIndex) {
        el.classList.add('done');
        icon.textContent = '✓';
      } else {
        icon.textContent = '○';
      }
    });
  }

  function mapAnalysisPhase(customStatus, runtimeStatus) {
    if (runtimeStatus === 'Completed') return 'complete';
    if (customStatus && customStatus.phase && ANALYSIS_PHASES.indexOf(customStatus.phase) > -1) {
      return customStatus.phase;
    }
    return 'submit';
  }

  function updateAnalysisStory(phase, runtimeStatus, data) {
    var runtime = runtimeStatus || 'Pending';
    var detail = ANALYSIS_PHASE_DETAILS[phase] || 'Working through the analysis pipeline.';
    var timing = summarizeRunTiming(data);

    if (runtime !== 'Completed' && phase === 'enrichment') {
      detail += ' Enrichment is the slowest local step because it batches weather, flood/fire checks, mosaic registration, NDVI, change detection, and manifest generation.';
      if (timing.sinceUpdate) {
        detail += ' Last backend update ' + timing.sinceUpdate + ' ago.';
      }
      if (timing.stale) {
        detail += ' The UI will stay on this message until the enrichment activity finishes because the backend only publishes the next status after that activity returns.';
      }
    } else if (runtime !== 'Completed' && timing.elapsed) {
      detail += ' Elapsed ' + timing.elapsed + '.';
    }

    if (runtime === 'Completed') {
      setAnalysisStatus(detail, 'success');
      return;
    }
    if (runtime === 'Failed' || runtime === 'Canceled' || runtime === 'Terminated') {
      setAnalysisStatus('Analysis stopped during ' + phase + '. ' + detail, 'error');
      return;
    }
    setAnalysisStatus(detail, 'info');
  }

  function parseKmlText(text) {
    if (!text) return '';
    return String(text).trim();
  }

  function parseCoordText(text) {
    var raw = String(text || '').trim().split(/\s+/).filter(Boolean);
    var coords = raw.map(function(chunk) {
      var parts = chunk.split(',');
      return [parseFloat(parts[1]), parseFloat(parts[0])];
    }).filter(function(coord) {
      return !isNaN(coord[0]) && !isNaN(coord[1]);
    });
    if (coords.length < 3) return null;
    if (coords[0][0] !== coords[coords.length - 1][0] || coords[0][1] !== coords[coords.length - 1][1]) {
      coords.push(coords[0].slice());
    }
    return coords;
  }

  function parseKmlGeometry(text) {
    var parser = new DOMParser();
    var doc = parser.parseFromString(text, 'text/xml');
    if (doc.getElementsByTagName('parsererror').length) {
      return { error: 'Could not parse the KML markup. Check that the XML is complete.' };
    }

    var placemarks = doc.getElementsByTagName('Placemark');
    var polygons = [];
    for (var p = 0; p < placemarks.length; p++) {
      var coordEls = placemarks[p].getElementsByTagName('coordinates');
      var nameEl = placemarks[p].getElementsByTagName('name')[0];
      var polygonName = nameEl ? nameEl.textContent.trim() : 'Polygon ' + (polygons.length + 1);
      for (var c = 0; c < coordEls.length; c++) {
        var coords = parseCoordText(coordEls[c].textContent);
        if (coords) polygons.push({ name: polygonName, coords: coords });
      }
    }

    if (!polygons.length) {
      var allCoords = doc.getElementsByTagName('coordinates');
      for (var i = 0; i < allCoords.length; i++) {
        var fallbackCoords = parseCoordText(allCoords[i].textContent);
        if (fallbackCoords) polygons.push({ name: 'Polygon ' + (polygons.length + 1), coords: fallbackCoords });
      }
    }

    return {
      featureCount: placemarks.length || polygons.length,
      polygons: polygons,
    };
  }

  function haversineKm(lat1, lon1, lat2, lon2) {
    var radiusKm = 6371;
    var dLat = (lat2 - lat1) * Math.PI / 180;
    var dLon = (lon2 - lon1) * Math.PI / 180;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
      Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return radiusKm * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  function polygonCentroid(coords) {
    var latTotal = 0;
    var lonTotal = 0;
    var count = coords.length - 1;
    for (var i = 0; i < count; i++) {
      latTotal += coords[i][0];
      lonTotal += coords[i][1];
    }
    return [latTotal / count, lonTotal / count];
  }

  function polygonAreaHa(coords) {
    if (!coords || coords.length < 4) return 0;
    var usable = coords.slice(0, -1);
    var meanLat = usable.reduce(function(sum, coord) { return sum + coord[0]; }, 0) / usable.length;
    var metresPerDegreeLat = 111320;
    var metresPerDegreeLon = Math.cos(meanLat * Math.PI / 180) * metresPerDegreeLat;
    var areaM2 = 0;
    for (var i = 0; i < coords.length - 1; i++) {
      var x1 = coords[i][1] * metresPerDegreeLon;
      var y1 = coords[i][0] * metresPerDegreeLat;
      var x2 = coords[i + 1][1] * metresPerDegreeLon;
      var y2 = coords[i + 1][0] * metresPerDegreeLat;
      areaM2 += (x1 * y2) - (x2 * y1);
    }
    return Math.abs(areaM2) / 2 / 10000;
  }

  function formatDistance(km) {
    if (km == null || isNaN(km)) return '—';
    if (km < 1) return '<1 km';
    return (km >= 10 ? km.toFixed(0) : km.toFixed(1)) + ' km';
  }

  function formatHectares(ha) {
    if (ha == null || isNaN(ha)) return '—';
    if (ha < 1) return ha.toFixed(1) + ' ha';
    return Math.round(ha).toLocaleString() + ' ha';
  }

  function determineProcessingMode(aoiCount, maxSpreadKm) {
    if (aoiCount > 30 || maxSpreadKm > 100) return 'May batch';
    if (aoiCount > 6 || maxSpreadKm > 25) return 'Bulk-ready';
    return 'Single run';
  }

  function buildPreflightWarnings(preflight) {
    var warnings = [];
    if (preflight.aoiCount > 30) {
      warnings.push({ tone: 'warning', text: preflight.aoiCount + ' AOIs detected. Large batches may take longer and could be split across runs.' });
    } else if (preflight.aoiCount > 6) {
      warnings.push({ tone: 'info', text: preflight.aoiCount + ' AOIs — this will queue as a bulk-ready run.' });
    }
    if (preflight.largestAreaHa > 50000) {
      warnings.push({ tone: 'warning', text: 'At least one AOI covers ' + formatHectares(preflight.largestAreaHa) + '. Very large areas may produce lower-resolution output.' });
    }
    if (preflight.maxSpreadKm > 100) {
      warnings.push({ tone: 'warning', text: 'AOI spread is ' + formatDistance(preflight.maxSpreadKm) + '. Widely spread areas may need batching in a future release.' });
    } else if (preflight.maxSpreadKm > 25) {
      warnings.push({ tone: 'info', text: 'AOI spread is ' + formatDistance(preflight.maxSpreadKm) + '. All areas will be processed in one run.' });
    }
    if (workspaceRole === 'eudr') {
      warnings.push({ tone: 'info', text: 'This due diligence lens frames evidence for review and audit support. It is not a legal compliance certificate.' });
    }
    if (workspaceRole === 'portfolio' && preflight.aoiCount > 10) {
      warnings.push({ tone: 'info', text: 'Large parcel sets work well with batch analysis. This run still enters your tracked workflow.' });
    }
    if (!warnings.length) {
      warnings.push({ tone: 'info', text: 'No warnings. This will queue as one tracked analysis run.' });
    }
    return warnings;
  }

  function buildAnalysisPreflight(text) {
    var trimmed = parseKmlText(text);
    if (!trimmed) return null;

    var parsed = parseKmlGeometry(trimmed);
    if (parsed.error) return { error: parsed.error };
    if (!parsed.polygons || !parsed.polygons.length) {
      return { error: 'No polygon boundaries were detected. Canopex expects polygon AOIs.' };
    }

    var centroids = parsed.polygons.map(function(polygon) { return polygonCentroid(polygon.coords); });
    var groupLat = centroids.reduce(function(sum, coord) { return sum + coord[0]; }, 0) / centroids.length;
    var groupLon = centroids.reduce(function(sum, coord) { return sum + coord[1]; }, 0) / centroids.length;
    var maxSpreadKm = centroids.reduce(function(maxDistance, coord) {
      return Math.max(maxDistance, haversineKm(groupLat, groupLon, coord[0], coord[1]));
    }, 0);
    var totalAreaHa = parsed.polygons.reduce(function(sum, polygon) {
      return sum + polygonAreaHa(polygon.coords);
    }, 0);
    var largestAreaHa = parsed.polygons.reduce(function(maxArea, polygon) {
      return Math.max(maxArea, polygonAreaHa(polygon.coords));
    }, 0);
    var processingMode = determineProcessingMode(parsed.polygons.length, maxSpreadKm);
    var preference = currentPreferenceConfig();

    var preflight = {
      featureCount: parsed.featureCount,
      aoiCount: parsed.polygons.length,
      maxSpreadKm: maxSpreadKm,
      totalAreaHa: totalAreaHa,
      largestAreaHa: largestAreaHa,
      processingMode: processingMode,
      quotaImpact: latestBillingStatus && latestBillingStatus.runs_remaining != null
        ? '1 of ' + latestBillingStatus.runs_remaining + ' runs'
        : '1 analysis',
      summary: parsed.featureCount + ' features across ' + parsed.polygons.length + ' AOIs covering about ' + formatHectares(totalAreaHa) + '. ' + processingMode + ' keeps the ' + preference.focusLabel.toLowerCase() + ' in focus for this request.'
    };
    preflight.warnings = buildPreflightWarnings(preflight);
    return preflight;
  }

  function renderPreflightWarnings(items) {
    var list = document.getElementById('app-preflight-warnings');
    if (!list) return;
    list.replaceChildren();
    items.forEach(function(item) {
      var el = document.createElement('div');
      el.className = 'app-preflight-item';
      el.setAttribute('data-tone', item.tone || 'info');
      el.textContent = item.text;
      list.appendChild(el);
    });
  }

  function updateAnalysisPreflight(text) {
    var headlineEl = document.getElementById('app-preflight-headline');
    var modeEl = document.getElementById('app-preflight-mode');
    var summaryEl = document.getElementById('app-preflight-summary');
    var featuresEl = document.getElementById('app-preflight-features');
    var aoisEl = document.getElementById('app-preflight-aois');
    var spreadEl = document.getElementById('app-preflight-spread');
    var quotaEl = document.getElementById('app-preflight-quota');
    if (!headlineEl || !modeEl || !summaryEl || !featuresEl || !aoisEl || !spreadEl || !quotaEl) return null;

    var role = currentRoleConfig();
    var trimmed = parseKmlText(text);
    if (!trimmed) {
      analysisDraftSummary = null;
      headlineEl.textContent = 'Awaiting KML';
      modeEl.textContent = 'No file yet';
      summaryEl.textContent = 'Paste KML to see feature count, area spread, and guidance for the ' + role.label + ' view.';
      featuresEl.textContent = '0';
      aoisEl.textContent = '0';
      spreadEl.textContent = '—';
      quotaEl.textContent = '—';
      renderPreflightWarnings([{ tone: 'info', text: 'Preflight will show warnings here after you paste or upload KML.' }]);
      return null;
    }

    var preflight = buildAnalysisPreflight(trimmed);
    analysisDraftSummary = preflight;
    if (preflight && preflight.error) {
      headlineEl.textContent = 'KML needs attention';
      modeEl.textContent = 'Check geometry';
      summaryEl.textContent = preflight.error;
      featuresEl.textContent = '—';
      aoisEl.textContent = '—';
      spreadEl.textContent = '—';
      quotaEl.textContent = '—';
      renderPreflightWarnings([{ tone: 'error', text: preflight.error }]);
      return preflight;
    }

    headlineEl.textContent = preflight.aoiCount + '-AOI request ready';
    modeEl.textContent = preflight.processingMode;
    summaryEl.textContent = preflight.summary;
    featuresEl.textContent = String(preflight.featureCount);
    aoisEl.textContent = String(preflight.aoiCount);
    spreadEl.textContent = formatDistance(preflight.maxSpreadKm);
    quotaEl.textContent = preflight.quotaImpact;
    renderPreflightWarnings(preflight.warnings);
    return preflight;
  }

  function readKmlFile(file) {
    return new Promise(function(resolve, reject) {
      var reader = new FileReader();
      reader.onload = function(e) { resolve(String(e.target.result || '')); };
      reader.onerror = function() { reject(new Error('Could not read KML file')); };
      reader.readAsText(file);
    });
  }

  async function readKmzFile(file) {
    var buffer = await file.arrayBuffer();
    var view = new DataView(buffer);
    var offset = 0;

    while (offset < buffer.byteLength - 4) {
      var signature = view.getUint32(offset, true);
      if (signature !== 0x04034b50) break;
      var compressionMethod = view.getUint16(offset + 8, true);
      var compressedSize = view.getUint32(offset + 18, true);
      var fileNameLength = view.getUint16(offset + 26, true);
      var extraLength = view.getUint16(offset + 28, true);
      var fileNameBytes = new Uint8Array(buffer, offset + 30, fileNameLength);
      var fileName = new TextDecoder().decode(fileNameBytes);
      var dataStart = offset + 30 + fileNameLength + extraLength;

      if (fileName.toLowerCase().endsWith('.kml')) {
        var compressed = new Uint8Array(buffer, dataStart, compressedSize);
        if (compressionMethod === 0) {
          return new TextDecoder().decode(compressed);
        }
        if (compressionMethod === 8) {
          var stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
          return await new Response(stream).text();
        }
      }
      offset = dataStart + compressedSize;
    }

    throw new Error('No .kml found inside KMZ archive');
  }

  async function loadAnalysisFile(file) {
    var note = document.getElementById('app-analysis-file-note');
    var textarea = document.getElementById('app-analysis-kml');
    if (!file || !note || !textarea) return;

    try {
      var name = file.name.toLowerCase();
      var content = name.endsWith('.kmz') ? await readKmzFile(file) : await readKmlFile(file);
      textarea.value = content;
      note.textContent = 'Loaded ' + file.name + ' into the analysis form.';
      updateAnalysisPreflight(content);
    } catch (err) {
      note.textContent = err.message || 'Could not read file';
    }
  }

  function stopAnalysisPolling() {
    if (activeAnalysisPoll) {
      clearInterval(activeAnalysisPoll);
      activeAnalysisPoll = null;
    }
  }

  async function pollAnalysisRun(instanceId) {
    stopAnalysisPolling();
    async function refreshRun() {
      try {
        var res = await apiFetch('/api/orchestrator/' + instanceId);
        var data = await res.json();
        upsertAnalysisHistoryRun(data);
        updateAnalysisRun(data);

        var runtime = data.runtimeStatus || '';
        var phase = mapAnalysisPhase(data.customStatus, runtime);
        setAnalysisProgressVisible(true);
        if (runtime === 'Completed') {
          stopAnalysisPolling();
          setAnalysisStep('complete', 'done');
          updateAnalysisStory('complete', runtime, data);
          loadBillingStatus();
          loadAnalysisHistory({ preferInstanceId: instanceId });
          loadRunEvidence(instanceId);
          var evidenceHero = document.getElementById('app-evidence-hero');
          if (evidenceHero) {
            setTimeout(function() {
              evidenceHero.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 400);
          }
        } else if (runtime === 'Failed' || runtime === 'Canceled' || runtime === 'Terminated') {
          stopAnalysisPolling();
          setAnalysisStep(phase, 'failed');
          updateAnalysisStory(phase, runtime, data);
          loadAnalysisHistory({ preferInstanceId: instanceId });
        } else {
          setAnalysisStep(phase, 'active');
          updateAnalysisStory(phase, runtime || 'Pending', data);
        }
        return data;
      } catch {
        return null;
      }
    }

    var initialData = await refreshRun();
    if (initialData) {
      var initialRuntime = initialData.runtimeStatus || '';
      if (initialRuntime === 'Completed' || initialRuntime === 'Failed' || initialRuntime === 'Canceled' || initialRuntime === 'Terminated') {
        return;
      }
    }

    activeAnalysisPoll = setInterval(function() {
      refreshRun();
    }, 3000);
  }

  async function queueAnalysis() {
    if (!currentAccount) {
      login();
      return;
    }

    var button = document.getElementById('app-analysis-submit-btn');
    var textarea = document.getElementById('app-analysis-kml');
    if (!button || !textarea) return;

    var kmlContent = parseKmlText(textarea.value);
    if (!kmlContent) {
      setAnalysisStatus('Paste KML content or load a KML/KMZ file first.', 'error');
      updateAnalysisRun(null);
      resetAnalysisProgress();
      return;
    }

    var preflight = analysisDraftSummary || updateAnalysisPreflight(kmlContent);
    if (preflight && preflight.error) {
      setAnalysisStatus(preflight.error, 'error');
      resetAnalysisProgress();
      return;
    }

    button.disabled = true;
    button.textContent = 'Queueing…';
    resetAnalysisProgress();
    setAnalysisProgressVisible(true);
    setAnalysisStep('submit', 'active');
    setWorkflowFocus('run');
    updateAnalysisStory('submit', 'Pending', null);
    updateAnalysisRun(null);

    try {
      await apiDiscoveryReady;
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

      var tokenRes;
      try {
        tokenRes = await apiFetch('/api/upload/token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(tokenBody)
        });
      } catch (tokenFetchErr) {
        if (tokenFetchErr.status === 401) {
          // Session expired — redirect to login.
          resetAnalysisProgress();
          currentAccount = null;
          updateAuthUI();
          setAnalysisStatus('Your session has expired. Please sign in again to queue an analysis.', 'error');
          return;
        }
        setAnalysisStatus(tokenFetchErr.body && tokenFetchErr.body.error || 'Could not prepare upload. Please try again.', 'error');
        updateContentSummary(null);
        resetAnalysisProgress();
        return;
      }

      var tokenData = await tokenRes.json();
      var submissionId = tokenData.submissionId || tokenData.submission_id;
      var sasUrl = tokenData.sasUrl || tokenData.sas_url;

      // Step 2: Upload KML directly to blob storage via SAS URL
      button.textContent = 'Uploading…';
      setAnalysisStep('submit', 'active');

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
        setAnalysisStatus('Upload failed. Please try again.', 'error');
        resetAnalysisProgress();
        return;
      }

      // Step 3: Track the submission
      var data = { instance_id: submissionId };
      analysisHistoryLoaded = true;
      applyFirstRunLayout();
      var queuedAt = new Date().toISOString();
      upsertAnalysisHistoryRun({
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
      selectAnalysisRun(data.instance_id, { focus: 'run', resume: true });
      setAnalysisStatus('Analysis queued. The app will walk through each stage as the pipeline advances.', 'info');
      loadBillingStatus();
    } catch (err) {
      console.error('queueAnalysis failed:', err);
      setAnalysisStatus('Could not queue analysis request.', 'error');
      resetAnalysisProgress();
    } finally {
      button.disabled = false;
      button.textContent = 'Queue Analysis';
    }
  }

  async function manageBilling() {
    // If billing is gated for this user, redirect to express interest
    if (latestBillingStatus && latestBillingStatus.billing_gated) {
      window.location.href = '/#early-access';
      return;
    }

    if (!currentAccount) {
      login();
      return;
    }

    await apiDiscoveryReady;
    try {
      var res = await apiFetch('/api/billing/portal', { method: 'POST' });
      var data = await res.json();
      if (data.portal_url) window.location.href = data.portal_url;
    } catch (err) {
      alert((err && err.message) || 'Could not open billing portal. Please try again.');
    }
  }

  function formatRetention(days) {
    if (days == null) return 'Custom';
    if (days === 365) return '1 year';
    return String(days) + ' days';
  }

  function updateCapabilityFields(caps) {
    document.getElementById('app-concurrency').textContent = caps.concurrency == null ? '—' : String(caps.concurrency);
    document.getElementById('app-ai-access').textContent = caps.ai_insights ? 'Included' : 'Not included';
    document.getElementById('app-api-access').textContent = caps.api_access ? 'Enabled' : 'Not included';
    document.getElementById('app-retention').textContent = formatRetention(caps.retention_days);
  }

  function renderTierEmulation(data) {
    var card = document.getElementById('app-tier-emulation-card');
    var select = document.getElementById('app-tier-emulation-select');
    var note = document.getElementById('app-tier-emulation-note');

    if (!card || !select || !note) return;

    if (!data.emulation || !data.emulation.available) {
      card.hidden = true;
      return;
    }

    card.hidden = false;
    select.replaceChildren();

    var actualOption = document.createElement('option');
    actualOption.value = 'actual';
    actualOption.textContent = 'Actual billing state';
    select.appendChild(actualOption);

    (data.emulation.tiers || []).forEach(function(tier) {
      var option = document.createElement('option');
      option.value = tier;
      option.textContent = tier.charAt(0).toUpperCase() + tier.slice(1);
      select.appendChild(option);
    });

    select.value = data.emulation.active ? data.emulation.tier : 'actual';
    if (data.emulation.active) {
      note.textContent = 'Currently emulating ' + (data.capabilities.label || data.tier) + ' for your account. Billing remains ' + ((data.subscription && data.subscription.tier) || 'free') + '.';
    } else {
      note.textContent = 'Using the actual billing state for this account.';
    }
  }

  function applyBillingStatus(data) {
    var tierEl = document.getElementById('app-tier');
    var statusEl = document.getElementById('app-subscription-status');
    var remainingEl = document.getElementById('app-runs-remaining');
    var billingNoteEl = document.getElementById('app-billing-note');
    var billingBtn = document.getElementById('app-manage-billing-btn');
    var accountNote = document.getElementById('app-account-note');
    var caps = data.capabilities || {};

    latestBillingStatus = data;
    tierEl.textContent = (caps.label || data.tier || 'Free') + (data.tier_source === 'emulated' ? ' (emulated)' : '');
    statusEl.textContent = data.status || 'none';
    remainingEl.textContent = data.runs_remaining == null ? '—' : String(data.runs_remaining);
    var usedEl = document.getElementById('app-runs-used');
    if (usedEl) usedEl.textContent = data.runs_used == null ? '—' : String(data.runs_used);
    updateCapabilityFields(caps);

    if (data.tier_source === 'emulated') {
      billingNoteEl.textContent = 'Local tier override active. Real billing is ' + ((data.subscription && data.subscription.tier) || 'free') + '.';
      billingBtn.style.display = data.billing_configured ? 'inline-block' : 'none';
      accountNote.textContent = 'Use the role view and work preference controls to tune this workspace for the job at hand.';
    } else if (data.billing_gated) {
      billingNoteEl.textContent = 'Billing is not yet available for your account. Contact us to express interest.';
      billingBtn.textContent = 'Express Interest';
      billingBtn.style.display = 'inline-block';
      accountNote.textContent = 'You are on the free plan. Express interest to unlock paid tiers when billing becomes available.';
    } else if (data.billing_configured) {
      billingNoteEl.textContent = 'Stripe customer portal available';
      billingBtn.textContent = 'Billing';
      billingBtn.style.display = 'inline-block';
      accountNote.textContent = 'Use the role view and work preference controls to bias the workspace toward investigation, monitoring, or reporting.';
    } else {
      billingNoteEl.textContent = 'Billing is not configured in this environment';
      billingBtn.style.display = 'none';
      accountNote.textContent = 'Use the role view and work preference controls to bias the workspace toward investigation, monitoring, or reporting.';
    }

    updateHeroSummary(data);
    renderTierEmulation(data);
  }

  async function saveTierEmulation() {
    if (!currentAccount) {
      login();
      return;
    }

    var button = document.getElementById('app-apply-tier-emulation-btn');
    var select = document.getElementById('app-tier-emulation-select');
    if (!button || !select) return;

    button.disabled = true;
    button.textContent = 'Applying…';
    try {
      await apiDiscoveryReady;
      var res = await apiFetch('/api/billing/emulation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tier: select.value })
      });
      applyBillingStatus(await res.json());
    } catch (err) {
      alert((err && err.message) || 'Could not update plan emulation. Please try again.');
    } finally {
      button.disabled = false;
      button.textContent = 'Apply';
    }
  }

  async function loadBillingStatus() {
    await apiDiscoveryReady;
    if (!currentAccount) return;

    try {
      var res = await apiFetch('/api/billing/status');
      applyBillingStatus(await res.json());
    } catch {
      document.getElementById('app-tier').textContent = 'Unknown';
      document.getElementById('app-subscription-status').textContent = 'Unavailable';
      document.getElementById('app-runs-remaining').textContent = '—';
      document.getElementById('app-billing-note').textContent = 'Could not load billing state';
      document.getElementById('app-manage-billing-btn').style.display = 'none';
      updateCapabilityFields({});
      setHeroRunSummary('Ready to queue', 'Billing is unavailable, but analysis can still be launched locally.');
    }
  }

  async function loadAnalysisHistory(options) {
    await apiDiscoveryReady;
    if (!currentAccount && authEnabled()) return;

    try {
      var res = await apiFetch('/api/analysis/history?limit=6');
      analysisHistoryLoaded = true;
      applyAnalysisHistory(await res.json(), options || {});
      applyFirstRunLayout();
    } catch {
      analysisHistoryLoaded = true;
      if (!analysisHistoryRuns.length && !latestAnalysisRun) {
        analysisHistoryRuns = [];
        selectedAnalysisRunId = null;
        renderAnalysisHistoryList();
        updateHistorySummary(null);
      }
      applyFirstRunLayout();
    }
  }

  function updateAuthUI() {
    var loginBtn = document.getElementById('auth-login-btn');
    var logoutBtn = document.getElementById('auth-logout-btn');
    var userSpan = document.getElementById('auth-user');
    var gate = document.getElementById('app-unauthenticated');
    var dashboard = document.getElementById('app-dashboard');
    var userName = document.getElementById('app-user-name');
    var accountIdentifier = document.getElementById('app-account-identifier');
    var accountNote = document.getElementById('app-account-note');
    var billingBtn = document.getElementById('app-manage-billing-btn');

    if (!authEnabled()) {
      loginBtn.style.display = 'none';
      logoutBtn.style.display = 'none';
      userSpan.textContent = 'Local dev';
      userSpan.style.display = 'inline';
      gate.hidden = true;
      dashboard.hidden = false;
      var localAuthGate = document.getElementById('app-analysis-auth-gate');
      var localFormFields = document.getElementById('app-analysis-form-fields');
      if (localAuthGate) localAuthGate.hidden = true;
      if (localFormFields) localFormFields.hidden = false;
      userName.textContent = 'Local developer';
      accountIdentifier.textContent = 'Authentication disabled';
      accountNote.textContent = 'Auth is disabled in this environment, so this workspace is running in local development mode.';
      billingBtn.style.display = 'none';
      document.getElementById('app-tier').textContent = 'Local';
      document.getElementById('app-subscription-status').textContent = 'disabled';
      document.getElementById('app-runs-remaining').textContent = 'n/a';
      document.getElementById('app-concurrency').textContent = 'n/a';
      document.getElementById('app-ai-access').textContent = 'n/a';
      document.getElementById('app-api-access').textContent = 'n/a';
      document.getElementById('app-retention').textContent = 'n/a';
      document.getElementById('app-billing-note').textContent = 'Billing is unavailable when auth is disabled';
      document.getElementById('app-tier-emulation-card').hidden = true;
      apiDiscoveryReady.then(function() {
        loadAnalysisHistory();
      });
      return;
    }

    if (currentAccount) {
      var displayName = currentAccount.name || currentAccount.userId || 'User';
      var identifier = currentAccount.userId || currentAccount.name || 'Signed in';
      userSpan.textContent = displayName;
      userSpan.style.display = 'inline';
      loginBtn.style.display = 'none';
      logoutBtn.style.display = 'inline';
      gate.hidden = true;
      dashboard.hidden = false;
      userName.textContent = displayName;
      accountIdentifier.textContent = identifier;
      accountNote.textContent = 'This is your Canopex dashboard. Choose the analysis type and work preference that match the job at hand.';
      var analysisAuthGate = document.getElementById('app-analysis-auth-gate');
      var analysisFormFields = document.getElementById('app-analysis-form-fields');
      var historyCard = document.getElementById('app-history-card');
      if (analysisAuthGate) analysisAuthGate.hidden = true;
      if (analysisFormFields) analysisFormFields.hidden = false;
      if (historyCard) historyCard.hidden = false;
      if (!analysisHistoryLoaded && !latestAnalysisRun) {
        setHeroRunSummary('Checking recent runs', 'Loading your recent runs.');
        updateHistorySummary(null);
        renderAnalysisHistoryList();
      }
      apiDiscoveryReady.then(loadBillingStatus);
      apiDiscoveryReady.then(function() {
        loadAnalysisHistory();
      });
    } else {
      userSpan.style.display = 'none';
      loginBtn.style.display = 'inline';
      logoutBtn.style.display = 'none';
      gate.hidden = false;
      dashboard.hidden = true;
      billingBtn.style.display = 'none';
      var unauthGate = document.getElementById('app-analysis-auth-gate');
      var unauthFormFields = document.getElementById('app-analysis-form-fields');
      if (unauthGate) unauthGate.hidden = false;
      if (unauthFormFields) unauthFormFields.hidden = true;
      analysisHistoryRuns = [];
      analysisHistoryLoaded = false;
      selectedAnalysisRunId = null;
      stopAnalysisPolling();
      resetAnalysisProgress();
      renderAnalysisHistoryList();
      updateAnalysisRun(null);
    }
  }

  function initAuth() {
    // Strip legacy ?mode=demo from URL if present
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.get('mode') === 'demo') {
        url.searchParams.delete('mode');
        const nextUrl = url.pathname + (url.search || '') + (url.hash || '');
        window.history.replaceState({}, '', nextUrl || '/app/');
      }
    } catch { /* ignore */ }

    // SWA built-in auth: fetch /.auth/me to check if the user is signed in.
    fetch('/.auth/me').then(function(resp) {
      if (!resp.ok) throw new Error('auth/me failed');
      return resp.json();
    }).then(function(payload) {
      var principal = payload && payload.clientPrincipal;
      if (principal && principal.userId) {
        _clientPrincipal = principal; // store raw for X-MS-CLIENT-PRINCIPAL forwarding
        currentAccount = {
          userId: principal.userId,
          name: principal.userDetails || '',
          identityProvider: principal.identityProvider || 'aad',
          userRoles: principal.userRoles || [],
        };
      }
      updateAuthUI();
    }).catch(function(err) {
      console.warn('SWA auth check failed:', err);
      // When running locally without SWA CLI, auth/me won't exist.
      // Fall back to unauthenticated state — updateAuthUI handles it.
      updateAuthUI();
    });
  }

  apiDiscoveryReady = discoverApiBase();
  initAuth();
  workspaceRole = readStoredUiValue(WORKSPACE_ROLE_STORAGE_KEY) || workspaceRole;
  workspacePreference = readStoredUiValue(WORKSPACE_PREFERENCE_STORAGE_KEY) || workspacePreference;
  renderWorkspaceGuidance();
  setWorkflowFocus(currentPreferenceConfig().focusTarget);

  document.querySelectorAll('.app-workflow-rail').forEach(function(rail) {
    rail.addEventListener('click', function() {
      var target = rail.getAttribute('data-focus-target');
      if (target) setWorkflowFocus(target);
    });
  });

  document.querySelectorAll('[data-role-choice]').forEach(function(button) {
    button.addEventListener('click', function() {
      setWorkspaceRole(button.getAttribute('data-role-choice'));
    });
  });

  document.querySelectorAll('[data-preference-choice]').forEach(function(button) {
    button.addEventListener('click', function() {
      setWorkspacePreference(button.getAttribute('data-preference-choice'));
    });
  });

  document.getElementById('auth-login-btn').addEventListener('click', login);
  document.getElementById('auth-logout-btn').addEventListener('click', logout);
  document.getElementById('app-sign-in-btn').addEventListener('click', login);
  document.getElementById('app-analysis-sign-in-btn').addEventListener('click', login);
  document.getElementById('app-manage-billing-btn').addEventListener('click', manageBilling);
  document.getElementById('app-apply-tier-emulation-btn').addEventListener('click', saveTierEmulation);
  document.getElementById('app-guided-primary-btn').addEventListener('click', function() {
    revealWorkflowTarget(this.getAttribute('data-target') || currentPreferenceConfig().primaryTarget);
  });
  document.getElementById('app-guided-secondary-btn').addEventListener('click', function() {
    revealWorkflowTarget(this.getAttribute('data-target') || currentPreferenceConfig().secondaryTarget);
  });
  document.getElementById('app-analysis-submit-btn').addEventListener('click', queueAnalysis);
  document.querySelectorAll('[data-export-format]').forEach(function(button) {
    button.addEventListener('click', function(event) {
      event.stopPropagation();
      downloadRunExport(button.getAttribute('data-export-format'));
    });
  });
  document.getElementById('app-analysis-kml').addEventListener('input', function() {
    updateAnalysisPreflight(this.value);
  });
  document.getElementById('app-analysis-file').addEventListener('change', function() {
    if (this.files && this.files[0]) loadAnalysisFile(this.files[0]);
  });

  // Evidence surface controls
  document.getElementById('app-map-play-btn').addEventListener('click', toggleEvidencePlay);
  document.getElementById('app-map-frame-slider').addEventListener('input', function() {
    showEvidenceFrame(parseInt(this.value, 10));
  });
  document.getElementById('app-map-btn-rgb').addEventListener('click', function() {
    evidenceLayerMode = 'rgb';
    document.getElementById('app-map-btn-rgb').classList.add('active');
    document.getElementById('app-map-btn-ndvi').classList.remove('active');
    showEvidenceFrame(evidenceFrameIndex);
  });
  document.getElementById('app-map-btn-ndvi').addEventListener('click', function() {
    evidenceLayerMode = 'ndvi';
    document.getElementById('app-map-btn-ndvi').classList.add('active');
    document.getElementById('app-map-btn-rgb').classList.remove('active');
    showEvidenceFrame(evidenceFrameIndex);
  });
  document.getElementById('app-evidence-ai-btn').addEventListener('click', requestAiAnalysis);
  document.getElementById('app-evidence-eudr-btn').addEventListener('click', requestEudrAssessment);

  // Expanded map viewer controls
  document.getElementById('app-map-expand-btn').addEventListener('click', expandEvidenceMap);
  document.getElementById('app-map-collapse-btn').addEventListener('click', collapseEvidenceMap);
  document.getElementById('app-map-expanded-backdrop').addEventListener('click', function(e) {
    if (e.target === this) collapseEvidenceMap();
  });
  document.getElementById('app-map-expanded-play-btn').addEventListener('click', toggleEvidencePlay);
  document.getElementById('app-map-expanded-slider').addEventListener('input', function() {
    showEvidenceFrame(parseInt(this.value, 10));
  });
  document.getElementById('app-map-expanded-btn-rgb').addEventListener('click', function() {
    evidenceLayerMode = 'rgb';
    document.getElementById('app-map-expanded-btn-rgb').classList.add('active');
    document.getElementById('app-map-expanded-btn-ndvi').classList.remove('active');
    document.getElementById('app-map-btn-rgb').classList.add('active');
    document.getElementById('app-map-btn-ndvi').classList.remove('active');
    showEvidenceFrame(evidenceFrameIndex);
  });
  document.getElementById('app-map-expanded-btn-ndvi').addEventListener('click', function() {
    evidenceLayerMode = 'ndvi';
    document.getElementById('app-map-expanded-btn-ndvi').classList.add('active');
    document.getElementById('app-map-expanded-btn-rgb').classList.remove('active');
    document.getElementById('app-map-btn-ndvi').classList.add('active');
    document.getElementById('app-map-btn-rgb').classList.remove('active');
    showEvidenceFrame(evidenceFrameIndex);
  });
})();
