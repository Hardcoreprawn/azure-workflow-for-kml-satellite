(function(){
  'use strict';

  // Geo/parsing utilities extracted to canopex-geo.js
  var escHtml = CanopexGeo.escHtml;
  var parseKmlText = CanopexGeo.parseKmlText;
  var parseCoordText = CanopexGeo.parseCoordText;
  var parseKmlGeometry = CanopexGeo.parseKmlGeometry;
  var haversineKm = CanopexGeo.haversineKm;
  var polygonCentroid = CanopexGeo.polygonCentroid;
  var polygonAreaHa = CanopexGeo.polygonAreaHa;
  var formatDistance = CanopexGeo.formatDistance;
  var formatHectares = CanopexGeo.formatHectares;
  var determineProcessingMode = CanopexGeo.determineProcessingMode;

  // Formatting/display helpers extracted to canopex-helpers.js
  var displayAnalysisPhase = CanopexHelpers.displayAnalysisPhase;
  var parseStatusTimestamp = CanopexHelpers.parseStatusTimestamp;
  var formatRelativeDuration = CanopexHelpers.formatRelativeDuration;
  var summarizeRunTiming = CanopexHelpers.summarizeRunTiming;
  var capabilityHeadline = CanopexHelpers.capabilityHeadline;
  var shortInstanceId = CanopexHelpers.shortInstanceId;
  var formatHistoryTimestamp = CanopexHelpers.formatHistoryTimestamp;
  var formatCountLabel = CanopexHelpers.formatCountLabel;
  var providerLabel = CanopexHelpers.providerLabel;
  var summarizeFailureCounts = CanopexHelpers.summarizeFailureCounts;
  var parseDownloadFilename = CanopexHelpers.parseDownloadFilename;
  var createStatEl = CanopexHelpers.createStatEl;
  var setStatGrid = CanopexHelpers.setStatGrid;
  var createCallout = CanopexHelpers.createCallout;
  var formatRetention = CanopexHelpers.formatRetention;

  // Evidence rendering extracted to canopex-evidence-render.js
  var renderEvidenceNdvi = CanopexEvidenceRender.renderEvidenceNdvi;
  var renderEvidenceWeather = CanopexEvidenceRender.renderEvidenceWeather;
  var renderEvidenceChangeDetection = CanopexEvidenceRender.renderEvidenceChangeDetection;
  var renderEvidenceAnalysis = CanopexEvidenceRender.renderEvidenceAnalysis;
  var pcTileUrl = CanopexEvidenceRender.pcTileUrl;
  var pcNdviTileUrl = CanopexEvidenceRender.pcNdviTileUrl;
  var renderAoiDetail = CanopexEvidenceRender.renderAoiDetail;
  var clearAoiDetail = CanopexEvidenceRender.clearAoiDetail;
  var renderResourceUsage = CanopexEvidenceRender.renderResourceUsage;

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
      primaryTarget: 'content',
      secondaryTarget: 'run'
    }
  };

  // Detect EUDR-locked page: <body data-eudr-app> forces EUDR mode
  // and hides the workspace role/preference switcher.
  const EUDR_LOCKED = document.body.hasAttribute('data-eudr-app');

  // Base path for the current app entry (/eudr/ or /app/).
  const APP_BASE = EUDR_LOCKED ? '/eudr/' : '/app/';

  // Null-safe DOM text setter — used when elements may not exist
  // on all pages (e.g. settings panel absent on EUDR app).
  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  let apiDiscoveryReady = null;

  // Container Apps FA: API calls go cross-origin to the Function App
  // hostname discovered from /api-config.json (injected at deploy time).
  // Auth principal is forwarded via X-MS-CLIENT-PRINCIPAL header.
  let _apiBase = '';          // Container Apps FA hostname, e.g. 'https://func-kmlsat-dev.azurecontainerapps.io'
  let _clientPrincipal = null; // raw clientPrincipal from /.auth/me — base64-encoded for X-MS-CLIENT-PRINCIPAL
  let _sessionToken = '';      // HMAC session token from /api/auth/session (#534)
  let currentAccount = null;   // populated by /.auth/me
  let latestBillingStatus = null;
  let latestAnalysisRun = null;
  let latestPortfolioSummary = null;
  let analysisHistoryRuns = [];
  let analysisHistoryLoaded = false;
  let selectedAnalysisRunId = null;
  let analysisDraftSummary = null;
  let workspaceRole = 'conservation';
  let workspacePreference = 'investigate';
  let activeAnalysisPoll = null;
  let analysisPollGeneration = 0; // incremented on each pollAnalysisRun call to detect stale callbacks
  const ANALYSIS_PHASES = ['submit', 'ingestion', 'acquisition', 'fulfilment', 'enrichment', 'complete'];
  const ANALYSIS_PHASE_DETAILS = {
    submit: 'Uploading your KML and reserving a pipeline worker for this run.',
    ingestion: 'Parsing the file, validating AOI geometry, and preparing the analysis package.',
    acquisition: 'Searching NAIP and Sentinel-2 coverage to find the best imagery for each AOI.',
    fulfilment: 'Downloading scenes, clipping to your AOIs, and reprojecting them into the output stack.',
    enrichment: 'Adding NDVI, weather context, and cached artifacts so the workspace has richer outputs ready.',
    complete: 'Analysis complete — scroll down to review satellite imagery, vegetation health, and export options.'
  };
  const EUDR_ANALYSIS_PHASE_DETAILS = {
    submit: 'Uploading KML and reserving pipeline capacity for this compliance run.',
    ingestion: 'Parsing parcels, validating geometry, and preparing the evidence request.',
    acquisition: 'Searching post-2020 Sentinel-2 imagery and polling scene availability for each parcel.',
    fulfilment: 'Downloading scenes, clipping to parcel boundaries, and reprojecting into the evidence stack.',
    enrichment: 'Building NDVI time series, deforestation risk, weather, fire, and land-cover evidence layers.',
    complete: 'Evidence pack complete — scroll down to review per-parcel determination and export compliance records.'
  };

  // ---------------------------------------------------------------------------
  // localStorage stale-while-revalidate cache (#596)
  // Render cached data instantly, then refresh in background.
  // Keys are scoped per-user to prevent cross-account data leakage.
  // ---------------------------------------------------------------------------
  const CACHE_PREFIX = 'canopex:';
  const CACHE_TTL_HISTORY = 5 * 60 * 1000;   // 5 min
  const CACHE_TTL_BILLING = 30 * 60 * 1000;  // 30 min

  function cacheKey(key) {
    const uid = currentAccount && currentAccount.userId;
    return uid ? CACHE_PREFIX + uid + ':' + key : null;
  }

  function readCache(key) {
    try {
      const full = cacheKey(key);
      if (!full) return null;
      const raw = localStorage.getItem(full);
      if (!raw) return null;
      const entry = JSON.parse(raw);
      if (!entry || typeof entry.expires !== 'number' || Date.now() > entry.expires) {
        localStorage.removeItem(full);
        return null;
      }
      return entry.data;
    } catch { return null; }
  }

  function writeCache(key, data, ttlMs) {
    if (!Number.isFinite(ttlMs)) return;
    try {
      const full = cacheKey(key);
      if (!full) return;
      localStorage.setItem(full, JSON.stringify({
        data: data,
        expires: Date.now() + ttlMs
      }));
    } catch { /* quota exceeded or private browsing — degrade gracefully */ }
  }

  function clearCacheKey(key) {
    try {
      const full = cacheKey(key);
      if (full) localStorage.removeItem(full);
    } catch { /* ignore */ }
  }

  function clearAllCache() {
    try {
      const keys = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith(CACHE_PREFIX)) keys.push(k);
      }
      keys.forEach(function(k) { localStorage.removeItem(k); });
    } catch { /* ignore */ }
  }

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
    clearAllCache();
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
    if (_sessionToken) {
      opts.headers['X-Auth-Session'] = _sessionToken;
    }
    const url = _apiBase ? _apiBase + path : path;
    const resp = await fetch(url, opts);
    if (!resp.ok) {
      const body = await resp.json().catch(function () { return {}; });
      if (resp.status === 401 && authEnabled()) {
        // Session expired — clear local auth state and prompt re-login.
        currentAccount = null;
        _clientPrincipal = null;
        _sessionToken = '';
        updateAuthUI();
        setAnalysisStatus('Your session has expired. Please sign in again.', 'error');
        stopAnalysisPolling();
      }
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

  function readRunSelectionFromLocation() {
    try {
      const params = new URLSearchParams(window.location.search || '');
      return {
        instanceId: params.get('run') || ''
      };
    } catch {
      return { instanceId: '' };
    }
  }

  function selectedRunPermalink(instanceId) {
    try {
      const url = new URL(window.location.href);
      if (instanceId) {
        url.searchParams.set('run', instanceId);
      } else {
        url.searchParams.delete('run');
      }
      url.searchParams.delete('focus');
      const nextPath = url.pathname;
      const nextSearch = url.searchParams.toString();
      return nextSearch ? nextPath + '?' + nextSearch : nextPath;
    } catch {
      return APP_BASE;
    }
  }

  function updateRunSelectionLocation(instanceId) {
    if (!window.history || typeof window.history.replaceState !== 'function') return;
    try {
      window.history.replaceState({}, '', selectedRunPermalink(instanceId));
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
  }

  function setWorkspacePreference(preferenceKey, options) {
    if (!WORKSPACE_PREFERENCES[preferenceKey]) return;
    workspacePreference = preferenceKey;
    if (!options || options.persist !== false) storeUiValue(WORKSPACE_PREFERENCE_STORAGE_KEY, preferenceKey);
    renderWorkspaceGuidance();
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

    renderPortfolioSummary();

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

  function renderPortfolioSummary() {
    var summaryEl = document.getElementById('app-portfolio-summary');
    if (!summaryEl) return;

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
        selectAnalysisRun(instanceId, { resume: historyRunIsActive(run) });
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
    applyFirstRunLayout();
  }

  function selectAnalysisRun(instanceId, options) {
    options = options || {};
    var run = analysisHistoryRuns.find(function(entry) {
      return (entry.instanceId || entry.instance_id) === instanceId;
    });
    if (!run) return;

    selectedAnalysisRunId = instanceId;
    renderAnalysisHistoryList();
    updateRunSelectionLocation(instanceId);

    stopAnalysisPolling();
    // Stop any running timelapse animation from a previous run.
    if (evidencePlayInterval) { clearInterval(evidencePlayInterval); evidencePlayInterval = null; }
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

    latestPortfolioSummary = {
      scope: payload && payload.scope,
      orgId: payload && payload.orgId,
      memberCount: payload && payload.memberCount,
      stats: payload && payload.stats
    };

    var normalizedActiveRun = normalizeAnalysisRun(payload && payload.activeRun);
    analysisHistoryRuns = sortAnalysisHistoryRuns(payload && payload.runs);
    if (normalizedActiveRun && !analysisHistoryRuns.some(function(run) {
      return run.instanceId === normalizedActiveRun.instanceId;
    })) {
      analysisHistoryRuns.unshift(normalizedActiveRun);
      analysisHistoryRuns = sortAnalysisHistoryRuns(analysisHistoryRuns);
    }

    // If the history API hasn't propagated a just-completed run yet,
    // preserve it from latestAnalysisRun so the UI doesn't flash to empty.
    if (options.preferInstanceId && latestAnalysisRun &&
        (latestAnalysisRun.instanceId || latestAnalysisRun.instance_id) === options.preferInstanceId &&
        !analysisHistoryRuns.some(function(run) { return run.instanceId === options.preferInstanceId; })) {
      var preserved = normalizeAnalysisRun(latestAnalysisRun);
      if (preserved) {
        analysisHistoryRuns.unshift(preserved);
        analysisHistoryRuns = sortAnalysisHistoryRuns(analysisHistoryRuns);
      }
    }

    var nextSelectedId = options.preferInstanceId || selectedAnalysisRunId || locationSelection.instanceId;
    if (nextSelectedId && !analysisHistoryRuns.some(function(run) { return run.instanceId === nextSelectedId; })) {
      nextSelectedId = null;
    }
    if (!nextSelectedId && normalizedActiveRun) nextSelectedId = normalizedActiveRun.instanceId;
    if (!nextSelectedId && analysisHistoryRuns[0]) nextSelectedId = analysisHistoryRuns[0].instanceId;

    if (!nextSelectedId) {
      selectedAnalysisRunId = null;
      updateRunSelectionLocation('');
      stopAnalysisPolling();
      resetAnalysisProgress();
      renderAnalysisHistoryList();
      updateAnalysisRun(null);
      updateHistorySummary(null);
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
  let evidenceAoiPolygons = []; // Leaflet polygon layers for per-AOI click
  let evidenceSelectedAoi = -1;  // -1 = aggregate, >=0 = per-AOI index

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
      var expandedFrame = evidenceMapLayers[evidenceFrameIndex];
      label.textContent = expandedFrame.label + ' — ' + expandedFrame.info +
        (expandedFrame.rgbDisplayWarning ? ' — ' + expandedFrame.rgbDisplayWarning : '');
    }
    syncEvidenceLayerButtons(evidenceMapLayers[evidenceFrameIndex]);
    if (rgbBtn) rgbBtn.classList.toggle('active', evidenceLayerMode === 'rgb');
    if (ndviBtn) ndviBtn.classList.toggle('active', evidenceLayerMode === 'ndvi');
  }

  function pickEvidenceDefaultLayer(frame) {
    if (!frame) return 'rgb';
    if (frame.preferredLayer === 'ndvi' || frame.preferred_layer === 'ndvi') return 'ndvi';
    return 'rgb';
  }

  function pickInitialEvidenceFrameIndex(frames) {
    if (!Array.isArray(frames) || !frames.length) return 0;

    var bestIndex = 0;
    var bestScore = null;

    frames.forEach(function(frame, idx) {
      if (!frame) return;

      var rgbSuitable = frame.rgbDisplaySuitable !== false;
      var resolution = Number(frame.displayResolutionM || 9999);
      var score = {
        rgbSuitable: rgbSuitable ? 1 : 0,
        resolution: Number.isFinite(resolution) ? -resolution : -9999,
        recency: idx
      };

      if (!bestScore) {
        bestScore = score;
        bestIndex = idx;
        return;
      }

      if (score.rgbSuitable > bestScore.rgbSuitable) {
        bestScore = score;
        bestIndex = idx;
        return;
      }

      if (score.rgbSuitable < bestScore.rgbSuitable) return;

      if (score.resolution > bestScore.resolution) {
        bestScore = score;
        bestIndex = idx;
        return;
      }

      if (score.resolution === bestScore.resolution && score.recency > bestScore.recency) {
        bestScore = score;
        bestIndex = idx;
      }
    });

    return bestIndex;
  }

  function syncEvidenceLayerButtons(frame) {
    var rgbBtn = document.getElementById('app-map-btn-rgb');
    var ndviBtn = document.getElementById('app-map-btn-ndvi');
    var expandedRgbBtn = document.getElementById('app-map-expanded-btn-rgb');
    var expandedNdviBtn = document.getElementById('app-map-expanded-btn-ndvi');
    var rgbDisabled = !!(frame && frame.rgbDisplaySuitable === false);
    var warning = frame && frame.rgbDisplayWarning ? frame.rgbDisplayWarning : '';

    [rgbBtn, expandedRgbBtn].forEach(function(btn) {
      if (!btn) return;
      btn.disabled = rgbDisabled;
      btn.title = rgbDisabled ? warning : '';
      btn.classList.toggle('is-disabled', rgbDisabled);
    });
    [ndviBtn, expandedNdviBtn].forEach(function(btn) {
      if (!btn) return;
      btn.disabled = false;
      btn.title = '';
      btn.classList.remove('is-disabled');
    });
  }

  // #646 — update layer button aria-labels and titles with per-frame
  // collection and resolution so the picker is self-documenting.
  function updateLayerButtonLabels(frame) {
    var btnRgb = document.getElementById('app-map-btn-rgb');
    var btnNdvi = document.getElementById('app-map-btn-ndvi');
    var expRgb = document.getElementById('app-map-expanded-btn-rgb');
    var expNdvi = document.getElementById('app-map-expanded-btn-ndvi');
    if (!frame) return;
    var info = frame.collectionLabel
      ? (frame.collectionLabel + (frame.resLabel || ''))
      : '';
    [btnRgb, expRgb].forEach(function(btn) {
      if (!btn) return;
      var base = info ? 'True-colour RGB — ' + info : 'True-colour RGB';
      // Preserve quality warning set by syncEvidenceLayerButtons when disabled.
      if (!btn.disabled) btn.title = base;
      btn.setAttribute('aria-label', info ? 'RGB (' + info + ')' : 'RGB');
    });
    [btnNdvi, expNdvi].forEach(function(btn) {
      if (!btn) return;
      btn.title = info ? 'Vegetation index (NDVI) — ' + info : 'Vegetation index (NDVI)';
      btn.setAttribute('aria-label', info ? 'NDVI (' + info + ')' : 'NDVI');
    });
  }

  // Sync the active/inactive classes on all RGB and NDVI buttons (both inline
  // panel and expanded modal) to match the current evidenceLayerMode.
  // Called any time evidenceLayerMode is changed programmatically so the
  // visual state is always consistent with what is rendered on the map.
  function syncLayerModeButtons() {
    var isRgb = evidenceLayerMode === 'rgb';
    ['app-map-btn-rgb', 'app-map-expanded-btn-rgb'].forEach(function(id) {
      var btn = document.getElementById(id);
      if (btn) btn.classList.toggle('active', isRgb);
    });
    ['app-map-btn-ndvi', 'app-map-expanded-btn-ndvi'].forEach(function(id) {
      var btn = document.getElementById(id);
      if (btn) btn.classList.toggle('active', !isRgb);
    });
  }

  // #646 — update layer button aria-labels and titles with per-frame
  // collection and resolution so the picker is self-documenting.
  function updateLayerButtonLabels(frame) {
    var btnRgb = document.getElementById('app-map-btn-rgb');
    var btnNdvi = document.getElementById('app-map-btn-ndvi');
    var expRgb = document.getElementById('app-map-expanded-btn-rgb');
    var expNdvi = document.getElementById('app-map-expanded-btn-ndvi');
    if (!frame) return;
    var info = frame.collectionLabel
      ? (frame.collectionLabel + (frame.resLabel || ''))
      : '';
    [btnRgb, expRgb].forEach(function(btn) {
      if (!btn) return;
      var base = info ? 'True-colour RGB \u2014 ' + info : 'True-colour RGB';
      // Preserve any quality warning appended by syncEvidenceLayerButtons.
      if (!btn.disabled) btn.title = base;
      btn.setAttribute('aria-label', info ? 'RGB (' + info + ')' : 'RGB');
    });
    [btnNdvi, expNdvi].forEach(function(btn) {
      if (!btn) return;
      btn.title = info ? 'Vegetation index (NDVI) \u2014 ' + info : 'Vegetation index (NDVI)';
      btn.setAttribute('aria-label', info ? 'NDVI (' + info + ')' : 'NDVI');
    });
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

    var shortId = instanceId.slice(0, 8);
    var footerEl = document.getElementById('app-content-footer');
    if (footerEl) footerEl.textContent = 'Loading evidence for run ' + shortId + '…';

    try {
      await apiDiscoveryReady;
      var manifestRes = await apiFetch('/api/timelapse-data/' + encodeURIComponent(instanceId));
      var manifest = await manifestRes.json();
      // Guard: user may have switched runs while we were fetching.
      if (evidenceInstanceId !== instanceId) return;
      evidenceManifest = manifest;
    } catch (err) {
      // Retry once after a short delay — the orchestrator may have just
      // completed and storage propagation can lag a few seconds.
      if (err && err.status === 404 && !arguments[1]) {
        await new Promise(function (r) { setTimeout(r, 3000); });
        if (evidenceInstanceId !== instanceId) return;
        return loadRunEvidence(instanceId, true);
      }
      if (evidenceInstanceId !== instanceId) return;
      if (footerEl) footerEl.textContent = 'Could not load enrichment data: ' + ((err && err.message) || 'unknown error');
      return;
    }

    renderEvidenceNdvi(evidenceManifest);
    renderEvidenceWeather(evidenceManifest);
    renderEvidenceChangeDetection(evidenceManifest);
    renderResourceUsage(evidenceManifest);
    initEvidenceMap(evidenceManifest);
    initCompareView(evidenceManifest);  // #671 before/after compare button

    // Show persistent run reference in the evidence header.
    var runRefEl = document.getElementById('app-evidence-run-ref');
    if (runRefEl) {
      runRefEl.textContent = 'Run ' + shortId;
      runRefEl.title = instanceId;
      runRefEl.hidden = false;
    }

    // Per-AOI selector (multi-polygon runs)
    evidenceSelectedAoi = -1;
    populateAoiSelector(evidenceManifest.per_aoi_enrichment);

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

  let evidenceCompareMode = false; // #671 before/after compare state
  let evidenceCompareMaps = null;  // { before: L.Map, after: L.Map } | null

  /* ---- Before/after comparison view (#671) ---- */

  function initCompareView(manifest) {
    var compareWrap = document.getElementById('app-evidence-compare-wrap');
    var compareBtn = document.getElementById('app-map-btn-compare');
    if (!compareWrap) return;

    var searchIds = manifest.search_ids || [];
    var framePlan = manifest.frame_plan || [];
    if (searchIds.length < 2) {
      // Not enough frames for a meaningful before/after
      if (compareBtn) compareBtn.hidden = true;
      return;
    }

    if (compareBtn) compareBtn.hidden = false;
  }

  function openCompareView(manifest) {
    var mainWrap = document.getElementById('app-evidence-map-wrap');
    var compareWrap = document.getElementById('app-evidence-compare-wrap');
    var frameControls = document.getElementById('app-evidence-frame-controls');
    var frameLabel = document.getElementById('app-map-frame-label');
    var compareBtn = document.getElementById('app-map-btn-compare');
    if (!mainWrap || !compareWrap) return;

    // Stop playback
    if (evidencePlayInterval) { clearInterval(evidencePlayInterval); evidencePlayInterval = null; }

    mainWrap.hidden = true;
    if (frameControls) frameControls.hidden = true;
    if (frameLabel) frameLabel.textContent = '';
    compareWrap.hidden = false;
    evidenceCompareMode = true;
    if (compareBtn) compareBtn.classList.add('active');

    buildCompareView(manifest);
  }

  function closeCompareView() {
    var mainWrap = document.getElementById('app-evidence-map-wrap');
    var compareWrap = document.getElementById('app-evidence-compare-wrap');
    var compareBtn = document.getElementById('app-map-btn-compare');
    if (!mainWrap || !compareWrap) return;

    destroyCompareMaps();
    compareWrap.hidden = true;
    mainWrap.hidden = false;
    evidenceCompareMode = false;
    if (compareBtn) compareBtn.classList.remove('active');

    var frameControls = document.getElementById('app-evidence-frame-controls');
    if (frameControls && evidenceMapLayers.length) frameControls.hidden = false;
    showEvidenceFrame(evidenceFrameIndex);
  }

  function destroyCompareMaps() {
    if (evidenceCompareMaps) {
      if (evidenceCompareMaps.before) { evidenceCompareMaps.before.remove(); }
      if (evidenceCompareMaps.after) { evidenceCompareMaps.after.remove(); }
      evidenceCompareMaps = null;
    }
    var before = document.getElementById('app-evidence-compare-map-before');
    var after = document.getElementById('app-evidence-compare-map-after');
    if (before) before.textContent = '';
    if (after) after.textContent = '';
  }

  function buildCompareView(manifest) {
    destroyCompareMaps();

    var searchIds = manifest.search_ids || [];
    var framePlan = manifest.frame_plan || [];
    var center = manifest.center || manifest.coords;
    if (!center || !searchIds.length) return;

    var lat = Array.isArray(center) ? center[0] : center.lat || center.latitude;
    var lon = Array.isArray(center) ? center[1] : center.lon || center.longitude;
    if (!lat || !lon) return;

    var firstFrame = framePlan[0] || {};
    var lastFrame = framePlan[framePlan.length - 1] || {};
    var firstSid = searchIds[0];
    var lastSid = searchIds[searchIds.length - 1];

    var firstCollection = firstFrame.display_collection || firstFrame.collection || 'sentinel-2-l2a';
    var lastCollection = lastFrame.display_collection || lastFrame.collection || 'sentinel-2-l2a';
    var firstAsset = firstFrame.asset || (firstCollection.indexOf('naip') >= 0 ? 'image' : 'visual');
    var lastAsset = lastFrame.asset || (lastCollection.indexOf('naip') >= 0 ? 'image' : 'visual');

    var labelBefore = document.getElementById('app-evidence-compare-label-before');
    var labelAfter = document.getElementById('app-evidence-compare-label-after');
    if (labelBefore) labelBefore.textContent = 'Before — ' + (firstFrame.label || 'earliest');
    if (labelAfter) labelAfter.textContent = 'After — ' + (lastFrame.label || 'most recent');

    var mapOptions = { zoomControl: false, attributionControl: false };
    var basemapUrl = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

    var beforeEl = document.getElementById('app-evidence-compare-map-before');
    var afterEl = document.getElementById('app-evidence-compare-map-after');
    if (!beforeEl || !afterEl) return;

    var beforeMap = L.map(beforeEl, mapOptions).setView([lat, lon], 13);
    L.tileLayer(basemapUrl, { maxZoom: 18 }).addTo(beforeMap);
    if (firstSid) {
      L.tileLayer(pcTileUrl(firstSid, firstCollection, firstAsset), { maxZoom: 18 }).addTo(beforeMap);
    }

    var afterMap = L.map(afterEl, mapOptions).setView([lat, lon], 13);
    L.tileLayer(basemapUrl, { maxZoom: 18 }).addTo(afterMap);
    if (lastSid) {
      L.tileLayer(pcTileUrl(lastSid, lastCollection, lastAsset), { maxZoom: 18 }).addTo(afterMap);
    }

    // Keep the two maps in sync when panning/zooming
    function syncMaps(source, target) {
      source.on('moveend', function() {
        target.setView(source.getCenter(), source.getZoom(), { animate: false });
      });
    }
    syncMaps(beforeMap, afterMap);
    syncMaps(afterMap, beforeMap);

    evidenceCompareMaps = { before: beforeMap, after: afterMap };

    // Fit to AOI bounds if available
    var perAoi = manifest.per_aoi_enrichment || [];
    try {
      var allBounds = L.latLngBounds([]);
      perAoi.forEach(function(aoi) {
        if (!aoi.coords || !aoi.coords.length) return;
        aoi.coords.forEach(function(c) { allBounds.extend([c[1], c[0]]); });
      });
      if (!allBounds.isValid() && manifest.coords && manifest.coords.length) {
        manifest.coords.forEach(function(c) { allBounds.extend([c[1], c[0]]); });
      }
      if (allBounds.isValid()) {
        beforeMap.fitBounds(allBounds.pad(0.1));
        afterMap.fitBounds(allBounds.pad(0.1));
      }
    } catch (e) { /* keep default view */ }

    setTimeout(function() {
      beforeMap.invalidateSize();
      afterMap.invalidateSize();
    }, 150);
  }

  function toggleCompareView() {
    if (evidenceCompareMode) {
      closeCompareView();
    } else if (evidenceManifest) {
      openCompareView(evidenceManifest);
    }
  }


    var ids = [
      'app-evidence-ndvi-grid',
      'app-evidence-weather-grid',
      'app-evidence-change-list',
      'app-evidence-ai-content',
      'app-evidence-eudr-content',
      'app-evidence-resources-grid'
    ];
    ids.forEach(function(id) { var el = document.getElementById(id); if (el) el.textContent = ''; });
    var noteEl = document.getElementById('app-evidence-ndvi-note');
    if (noteEl) noteEl.textContent = '';
    var resourceNote = document.getElementById('app-evidence-resources-note');
    if (resourceNote) resourceNote.textContent = '';
    var resourcesBlock = document.getElementById('app-evidence-resources-block');
    if (resourcesBlock) resourcesBlock.hidden = true;
    var runRefEl = document.getElementById('app-evidence-run-ref');
    if (runRefEl) { runRefEl.textContent = ''; runRefEl.title = ''; runRefEl.hidden = true; }
    var canvases = ['app-evidence-ndvi-canvas', 'app-evidence-weather-canvas'];
    canvases.forEach(function(id) {
      var c = document.getElementById(id);
      if (c) { var ctx = c.getContext('2d'); ctx.clearRect(0, 0, c.width, c.height); }
    });
    if (evidencePlayInterval) { clearInterval(evidencePlayInterval); evidencePlayInterval = null; }
    evidenceAoiPolygons = [];
    evidenceSelectedAoi = -1;
    clearAoiDetail();
    var aoiBlock = document.getElementById('app-evidence-aoi-block');
    if (aoiBlock) aoiBlock.hidden = true;
    // Reset compare mode so it doesn't persist across runs
    destroyCompareMaps();
    evidenceCompareMode = false;
    var compareWrap = document.getElementById('app-evidence-compare-wrap');
    var mainWrap = document.getElementById('app-evidence-map-wrap');
    var compareBtn = document.getElementById('app-map-btn-compare');
    if (compareWrap) compareWrap.hidden = true;
    if (mainWrap) mainWrap.hidden = false;
    if (compareBtn) { compareBtn.hidden = true; compareBtn.classList.remove('active'); }
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
    evidenceAoiPolygons = [];
    var perAoi = manifest.per_aoi_enrichment || [];
    if (perAoi.length > 1) {
      // Per-AOI mode: draw each AOI polygon as interactive
      try {
        var allBounds = L.latLngBounds([]);
        perAoi.forEach(function(aoi, idx) {
          if (!aoi.coords || !aoi.coords.length) return;
          var ll = aoi.coords.map(function(c) { return [c[1], c[0]]; });
          var poly = L.polygon(ll, {
            color: 'rgba(88,166,255,.7)',
            weight: 2,
            fillOpacity: 0.05
          }).addTo(evidenceMap);
          var tip = document.createElement('span');
          tip.textContent = aoi.name || ('Parcel ' + (idx + 1));
          poly.bindTooltip(tip, { sticky: true });
          poly.on('click', function() { selectAoi(idx); });
          evidenceAoiPolygons.push(poly);
          allBounds.extend(poly.getBounds());
        });
        if (allBounds.isValid()) evidenceMap.fitBounds(allBounds.pad(0.1));
      } catch (e) { /* skip polygon */ }
    } else if (manifest.coords && Array.isArray(manifest.coords)) {
      // Single-AOI fallback: split concatenated ring
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

  /* ---- Per-AOI selection ---- */

  function populateAoiSelector(perAoi) {
    var block = document.getElementById('app-evidence-aoi-block');
    var list = document.getElementById('app-evidence-aoi-list');
    var resetBtn = document.getElementById('app-evidence-aoi-reset');
    if (!block || !list) return;

    if (!perAoi || perAoi.length < 2) {
      block.hidden = true;
      return;
    }

    block.hidden = false;
    list.textContent = '';

    perAoi.forEach(function(aoi, idx) {
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'app-evidence-aoi-chip';
      chip.textContent = aoi.name || ('Parcel ' + (idx + 1));
      chip.addEventListener('click', function() { selectAoi(idx); });
      list.appendChild(chip);
    });

    if (resetBtn) {
      resetBtn.addEventListener('click', function() { resetAoiSelection(); });
    }
  }

  function selectAoi(idx) {
    if (!evidenceManifest || !evidenceManifest.per_aoi_enrichment) return;
    var perAoi = evidenceManifest.per_aoi_enrichment;
    if (idx < 0 || idx >= perAoi.length) return;

    evidenceSelectedAoi = idx;
    var aoi = perAoi[idx];

    // Highlight selected polygon, dim others
    evidenceAoiPolygons.forEach(function(poly, i) {
      if (i === idx) {
        poly.setStyle({ color: '#5eecc4', weight: 3, fillOpacity: 0.15 });
      } else {
        poly.setStyle({ color: 'rgba(88,166,255,.3)', weight: 1, fillOpacity: 0.02 });
      }
    });

    // Zoom to selected AOI
    if (evidenceAoiPolygons[idx] && evidenceMap) {
      evidenceMap.fitBounds(evidenceAoiPolygons[idx].getBounds().pad(0.15));
    }

    // Update chip active state
    var chips = document.querySelectorAll('.app-evidence-aoi-chip');
    chips.forEach(function(chip, i) {
      chip.className = 'app-evidence-aoi-chip' + (i === idx ? ' active' : '');
    });

    // Render per-AOI detail
    renderAoiDetail(aoi);
  }

  function resetAoiSelection() {
    evidenceSelectedAoi = -1;

    // Reset polygon styles
    evidenceAoiPolygons.forEach(function(poly) {
      poly.setStyle({ color: 'rgba(88,166,255,.7)', weight: 2, fillOpacity: 0.05 });
    });

    // Zoom to fit all
    if (evidenceAoiPolygons.length && evidenceMap) {
      var allBounds = L.latLngBounds([]);
      evidenceAoiPolygons.forEach(function(poly) { allBounds.extend(poly.getBounds()); });
      if (allBounds.isValid()) evidenceMap.fitBounds(allBounds.pad(0.1));
    }

    // Clear chip active state
    var chips = document.querySelectorAll('.app-evidence-aoi-chip');
    chips.forEach(function(chip) { chip.className = 'app-evidence-aoi-chip'; });

    // Clear per-AOI detail
    clearAoiDetail();
  }

  function buildEvidenceFrames(framePlan, searchIds, ndviSearchIds) {
    evidenceMapLayers = [];
    var slider = document.getElementById('app-map-frame-slider');
    if (slider) { slider.max = framePlan.length - 1; slider.value = 0; }

    framePlan.forEach(function(frame, idx) {
      var sid = searchIds[idx];
      var ndviSid = ndviSearchIds[idx] || sid;
      var collection = frame.display_collection || frame.collection || 'sentinel-2-l2a';
      var asset = frame.asset || (collection.indexOf('naip') >= 0 ? 'image' : 'visual');

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

      // #646 — store human-readable collection label and resolution suffix so
      // updateLayerButtonLabels can build informative button titles per frame.
      var collectionLabel = collection.indexOf('naip') >= 0 ? 'NAIP'
        : collection.indexOf('sentinel') >= 0 ? 'Sentinel-2'
        : collection.indexOf('landsat') >= 0 ? 'Landsat'
        : collection;
      var resolutionM = (frame.provenance && frame.provenance.resolution_m)
        || frame.display_resolution_m
        || null;
      var resLabel = resolutionM ? (' \u00b7 ' + resolutionM + 'm') : '';

      evidenceMapLayers.push({
        rgb: rgbLayer,
        ndvi: ndviLayer,
        label: frame.label || ('Frame ' + (idx + 1)),
        info: [collection, frame.start_date, frame.end_date].filter(Boolean).join(' | '),
        rgbDisplaySuitable: frame.rgb_display_suitable !== false,
        rgbDisplayWarning: frame.rgb_display_warning || '',
        preferredLayer: frame.preferred_layer || 'rgb',
        displayResolutionM: frame.display_resolution_m || null,
        collectionLabel: collectionLabel,
        resLabel: resLabel
      });
    });

    evidenceFrameIndex = pickInitialEvidenceFrameIndex(evidenceMapLayers);
    evidenceLayerMode = pickEvidenceDefaultLayer(evidenceMapLayers[evidenceFrameIndex]);
    syncLayerModeButtons();
    showEvidenceFrame(evidenceFrameIndex);
  }

  function showEvidenceFrame(idx) {
    if (idx < 0 || idx >= evidenceMapLayers.length) return;
    evidenceFrameIndex = idx;
    var activeFrame = evidenceMapLayers[idx];

    // #646 — bidirectional mode adaptation:
    // Fall back to rgb when the user is in ndvi mode but this frame has no ndvi layer.
    if (evidenceLayerMode === 'ndvi' && !activeFrame.ndvi) {
      evidenceLayerMode = 'rgb';
    }
    // Promote to ndvi for coarse frames where rgb is unsuitable (established in #645).
    if (activeFrame.rgbDisplaySuitable === false && activeFrame.ndvi) {
      evidenceLayerMode = 'ndvi';
    }
    // Keep button active classes in sync after any programmatic mode change.
    syncLayerModeButtons();

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
    if (label) {
      label.textContent = activeFrame.label + ' — ' + activeFrame.info +
        (activeFrame.rgbDisplayWarning ? ' — ' + activeFrame.rgbDisplayWarning : '');
    }
    syncEvidenceLayerButtons(activeFrame);
    updateLayerButtonLabels(activeFrame);

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
    } catch (e) {
      // 404 = no saved analysis yet (expected). Other errors indicate a real problem.
      if (e && e.status && e.status !== 404) {
        console.warn('Failed to load saved analysis:', e.message || e);
      }
    }
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

      // Save the analysis (non-blocking but warn user on failure)
      apiFetch('/api/timelapse-analysis-save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instance_id: evidenceInstanceId, analysis: evidenceAnalysis })
      }).catch(function() {
        var saveWarn = document.getElementById('app-evidence-ai-content');
        if (saveWarn) saveWarn.appendChild(createCallout('warning', 'Analysis displayed but could not be saved. It will be lost on reload.'));
      });
    } catch (err) {
      content.textContent = '';
      content.appendChild(createCallout('error', (err && err.message) || 'Could not run AI analysis.'));
    } finally {
      loading.hidden = true;
      if (btn) { btn.disabled = false; btn.textContent = originalLabel; }
    }
  }

  /* ---- EUDR assessment ---- */
  function activeEvidenceContext() {
    if (!evidenceManifest) return null;
    var perAoi = evidenceManifest.per_aoi_enrichment || [];
    if (evidenceSelectedAoi >= 0 && evidenceSelectedAoi < perAoi.length) {
      return perAoi[evidenceSelectedAoi];
    }
    return evidenceManifest;
  }

  function buildEvidenceNdviTimeseries(source) {
    if (!source) return [];
    return (source.ndvi_stats || []).map(function(f, i) {
      if (!f) return null;
      var fp = (source.frame_plan || [])[i] || {};
      return {
        date: f.datetime || f.date || fp.start || fp.label,
        mean: f.mean,
        min: f.min,
        max: f.max,
        year: f.year || fp.year,
        season: f.season || fp.season
      };
    }).filter(Boolean);
  }

  function evidenceLatLon(source) {
    if (!source) return { lat: 0, lon: 0 };
    var center = source.center || source.coords;
    if (Array.isArray(center)) {
      return { lat: center[0] || 0, lon: center[1] || 0 };
    }
    return {
      lat: (center && (center.lat || center.latitude)) || 0,
      lon: (center && (center.lon || center.longitude)) || 0
    };
  }

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

      var source = activeEvidenceContext();
      var ndviTimeseries = buildEvidenceNdviTimeseries(source);
      var latLon = evidenceLatLon(source);

      var body = {
        context: {
          aoi_name: source && source.name ? source.name : 'Analysis area',
          latitude: latLon.lat,
          longitude: latLon.lon,
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
      imageryNoteEl.textContent = EUDR_LOCKED
        ? 'Sentinel-2 post-2020 imagery discovery is in progress for each parcel.'
        : 'NAIP and Sentinel-2 discovery is in progress so the run can pick the right source imagery.';
      enrichmentEl.textContent = 'Queued behind acquisition';
      enrichmentNoteEl.textContent = 'Context layers are staged after the imagery stack is selected.';
      exportsEl.textContent = 'Awaiting artefacts';
      exportsNoteEl.textContent = EUDR_LOCKED
        ? 'Evidence pack exports are unavailable until imagery is acquired.'
        : 'There is nothing to export until imagery is actually acquired.';
      return;
    }

    if (phase === 'fulfilment') {
      imageryEl.textContent = 'Clipping and reprojection';
      imageryNoteEl.textContent = EUDR_LOCKED
        ? 'The pipeline is clipping scenes to parcel boundaries for the evidence stack.'
        : 'The pipeline is producing imagery assets for your analysis.';
      enrichmentEl.textContent = 'Preparing next';
      enrichmentNoteEl.textContent = EUDR_LOCKED
        ? 'Deforestation risk, NDVI time series, and land-cover evidence will follow immediately.'
        : 'NDVI and weather context will follow immediately after fulfilment finishes.';
      exportsEl.textContent = 'Outputs staging next';
      exportsNoteEl.textContent = EUDR_LOCKED
        ? 'Compliance exports are close — the evidence pack is being assembled.'
        : 'The run is close enough that saved outputs should feel tangible, not hypothetical.';
      return;
    }

    imageryEl.textContent = 'Imagery stack stabilizing';
    imageryNoteEl.textContent = EUDR_LOCKED
      ? 'Sentinel-2 and land-cover layers are in place; final evidence layers being added.'
      : 'Core imagery is in place and the workspace is adding the last supporting layers.';
    enrichmentEl.textContent = 'Context packaging';
    enrichmentNoteEl.textContent = EUDR_LOCKED
      ? 'Per-parcel deforestation determination, NDVI, weather, fire, and land-cover evidence are being assembled.'
      : 'NDVI, weather, and derived context are being assembled for the run detail experience.';
    exportsEl.textContent = 'Preparing results view';
    exportsNoteEl.textContent = EUDR_LOCKED
      ? 'Audit-grade PDF, GeoJSON, and CSV exports for compliance records will be available shortly.'
      : 'Saved outputs, exports, and revisit paths will be available shortly.';
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
      linkEl.href = APP_BASE;
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
    linkEl.href = selectedRunPermalink(data.instanceId || data.instance_id);
    linkEl.textContent = 'Copy link to this run';

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
    resetEnrichmentSubSteps();
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

  const ENRICHMENT_STEP_LABELS = {
    data_sources_and_imagery: 'Fetching weather, flood/fire context, and registering satellite mosaics in parallel.',
    per_aoi: 'Running per-parcel enrichment across AOIs in parallel.',
    finalizing: 'Merging results and storing the analysis manifest.'
  };

  // Sub-step order for the enrichment phase progress UI.
  // 'data_sources_and_imagery' maps to both data_sources_and_imagery + imagery
  // sub-bullets since the orchestrator runs them in parallel under one status.
  const ENRICHMENT_SUB_ORDER = ['data_sources_and_imagery', 'imagery', 'per_aoi', 'finalizing'];

  function updateEnrichmentSubSteps(enrichmentStep) {
    const container = document.querySelector('#app-analysis-progress .pipeline-step[data-phase="enrichment"] .pipeline-sub-steps');
    if (!container) return;
    container.hidden = false;
    const currentIdx = ENRICHMENT_SUB_ORDER.indexOf(enrichmentStep);
    const subs = container.querySelectorAll('.pipeline-sub-step');
    subs.forEach(function(el) {
      const sub = el.getAttribute('data-sub');
      const icon = el.querySelector('.sub-icon');
      el.className = 'pipeline-sub-step';
      if (!icon) return;
      const subIdx = ENRICHMENT_SUB_ORDER.indexOf(sub);
      if (subIdx < 0) return;

      // data_sources_and_imagery and imagery run in parallel — treat
      // them as the same phase for status purposes.
      const isParallelPair = (sub === 'imagery' && enrichmentStep === 'data_sources_and_imagery')
        || (sub === 'data_sources_and_imagery' && enrichmentStep === 'imagery');

      if (sub === enrichmentStep || isParallelPair) {
        el.classList.add('active');
        icon.replaceChildren();
        const spinner = document.createElement('span');
        spinner.className = 'spinner';
        icon.appendChild(spinner);
      } else if (subIdx < currentIdx) {
        el.classList.add('done');
        icon.textContent = '✓';
      } else {
        icon.textContent = '○';
      }
    });
  }

  function resetEnrichmentSubSteps() {
    const container = document.querySelector('#app-analysis-progress .pipeline-step[data-phase="enrichment"] .pipeline-sub-steps');
    if (!container) return;
    container.hidden = true;
    const subs = container.querySelectorAll('.pipeline-sub-step');
    subs.forEach(function(el) {
      el.className = 'pipeline-sub-step';
      const icon = el.querySelector('.sub-icon');
      if (icon) icon.textContent = '○';
    });
  }

  function completeEnrichmentSubSteps() {
    const container = document.querySelector('#app-analysis-progress .pipeline-step[data-phase="enrichment"] .pipeline-sub-steps');
    if (!container) return;
    container.hidden = false;
    const subs = container.querySelectorAll('.pipeline-sub-step');
    subs.forEach(function(el) {
      el.className = 'pipeline-sub-step done';
      const icon = el.querySelector('.sub-icon');
      if (icon) icon.textContent = '✓';
    });
  }

  function updateAnalysisStory(phase, runtimeStatus, data) {
    var runtime = runtimeStatus || 'Pending';
    var phaseDetails = EUDR_LOCKED ? EUDR_ANALYSIS_PHASE_DETAILS : ANALYSIS_PHASE_DETAILS;
    var detail = phaseDetails[phase] || 'Working through the analysis pipeline.';
    var timing = summarizeRunTiming(data);

    if (runtime !== 'Completed' && phase === 'enrichment') {
      var cs = data && data.customStatus;
      var step = cs && cs.step;
      const stepLabel = step && ENRICHMENT_STEP_LABELS[step];
      if (stepLabel) {
        detail = stepLabel;
        if (step === 'per_aoi' && cs.aois) {
          detail += ' (' + cs.aois + ' AOIs)';
        }
      } else {
        detail += ' Enrichment batches weather, flood/fire checks, mosaic registration, NDVI, and change detection in parallel.';
      }
      if (timing.sinceUpdate) {
        detail += ' Last backend update ' + timing.sinceUpdate + ' ago.';
      }
      // Drive the nested sub-step progress indicators.
      if (step) updateEnrichmentSubSteps(step);
    } else if (phase !== 'enrichment') {
      // Past enrichment (complete) — mark all sub-steps done.
      // Before enrichment — keep sub-steps hidden.
      const enrichIdx = ANALYSIS_PHASES.indexOf('enrichment');
      const phaseIdx = ANALYSIS_PHASES.indexOf(phase);
      if (phaseIdx > enrichIdx) {
        completeEnrichmentSubSteps();
      } else {
        resetEnrichmentSubSteps();
      }
      if (runtime !== 'Completed' && timing.elapsed) {
        detail += ' Elapsed ' + timing.elapsed + '.';
      }
    } else {
      // Completed while on enrichment phase — mark all sub-steps done.
      completeEnrichmentSubSteps();
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
      polygons: parsed.polygons,
      maxSpreadKm: maxSpreadKm,
      totalAreaHa: totalAreaHa,
      largestAreaHa: largestAreaHa,
      processingMode: processingMode,
      quotaImpact: latestBillingStatus && latestBillingStatus.runs_remaining != null
        ? '1 of ' + latestBillingStatus.runs_remaining + ' runs'
        : '1 analysis',
      summary: parsed.featureCount + ' features across ' + parsed.polygons.length + ' AOIs covering about ' + formatHectares(totalAreaHa) + '. ' + processingMode + ' processing for this request.'
    };
    preflight.warnings = buildPreflightWarnings(preflight);
    return preflight;
  }

  var preflightMap = null;

  function renderPreflightMap(polygons) {
    var wrap = document.getElementById('app-preflight-map-wrap');
    var container = document.getElementById('app-preflight-map');
    if (!wrap || !container) return;

    if (!polygons || !polygons.length) {
      wrap.hidden = true;
      if (preflightMap) { preflightMap.remove(); preflightMap = null; }
      return;
    }

    wrap.hidden = false;

    if (preflightMap) { preflightMap.remove(); preflightMap = null; }

    preflightMap = L.map(container, {
      zoomControl: true,
      attributionControl: true,
      scrollWheelZoom: false,
      dragging: true
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>'
    }).addTo(preflightMap);

    var bounds = L.latLngBounds([]);
    polygons.forEach(function(polygon) {
      var layer = L.polygon(polygon.coords, {
        color: '#5eecc4',
        weight: 2,
        fillColor: '#5eecc4',
        fillOpacity: 0.15
      }).addTo(preflightMap);
      var tip = document.createElement('span');
      tip.textContent = polygon.name;
      layer.bindTooltip(tip, { sticky: true });
      bounds.extend(layer.getBounds());
    });

    preflightMap.fitBounds(bounds, { padding: [24, 24], maxZoom: 15 });
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

  // ── Cost estimator for EUDR preflight ────────────────────────
  function computeEudrCostEstimate(parcelCount) {
    if (!EUDR_LOCKED || !parcelCount) return '—';
    var billing = typeof window.eudrBillingData === 'function' ? window.eudrBillingData() : null;
    if (!billing) return '—';

    if (!billing.subscribed) {
      var remaining = billing.trial_remaining != null ? billing.trial_remaining : 0;
      if (remaining > 0) return parcelCount + ' parcel' + (parcelCount !== 1 ? 's' : '') + ' · ' + remaining + ' free assessment' + (remaining !== 1 ? 's' : '') + ' left';
      return 'Subscribe to continue';
    }

    // Pro subscriber — estimate only the incremental overage caused by this submission
    var used = billing.period_parcels_used || 0;
    var included = billing.included_parcels || 10;
    var remainingIncluded = Math.max(included - used, 0);
    var overageParcels = Math.max(parcelCount - remainingIncluded, 0);
    if (overageParcels === 0) {
      return parcelCount + ' parcel' + (parcelCount !== 1 ? 's' : '') + ' included';
    }
    var rate = overageParcels >= 500 ? 1.80 : overageParcels >= 100 ? 2.50 : 3.00;
    var cost = (overageParcels * rate).toFixed(2);
    return overageParcels + ' overage × £' + rate.toFixed(2) + ' = £' + cost;
  }

  // ── Input tab switching (KML / CSV) ──────────────────────────
  function switchInputTab(tabName) {
    var tabs = document.querySelectorAll('[data-input-tab]');
    tabs.forEach(function(tab) {
      var isActive = tab.getAttribute('data-input-tab') === tabName;
      tab.classList.toggle('active', isActive);
      tab.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
    var kmlPanel = document.getElementById('app-input-panel-kml');
    var csvPanel = document.getElementById('app-input-panel-csv');
    if (kmlPanel) kmlPanel.hidden = tabName !== 'kml';
    if (csvPanel) csvPanel.hidden = tabName !== 'csv';
  }

  // ── CSV coordinate parsing and conversion ───────────────────
  function parseCSVCoordinates(text) {
    var lines = text.trim().split(/\r?\n/).filter(Boolean);
    if (lines.length === 0) return { plots: [], errors: ['No data entered'] };

    var plots = [];
    var errors = [];
    var startIdx = 0;

    // Detect header row
    var firstLine = lines[0].toLowerCase().replace(/\s/g, '');
    if (firstLine.indexOf('name') >= 0 && (firstLine.indexOf('lat') >= 0 || firstLine.indexOf('lon') >= 0)) {
      startIdx = 1;
    }

    for (var i = startIdx; i < lines.length; i++) {
      var parts = lines[i].split(',').map(function(s) { return s.trim(); });
      if (parts.length < 3) {
        errors.push('Row ' + (i + 1) + ': expected name, lat, lon — got ' + parts.length + ' columns');
        continue;
      }
      var name = parts[0] || 'Parcel ' + (plots.length + 1);
      var lat = parseFloat(parts[1]);
      var lon = parseFloat(parts[2]);
      if (isNaN(lat) || isNaN(lon)) {
        errors.push('Row ' + (i + 1) + ': invalid coordinates (' + parts[1] + ', ' + parts[2] + ')');
        continue;
      }
      if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
        errors.push('Row ' + (i + 1) + ': coordinates out of range (lat: ' + lat + ', lon: ' + lon + ')');
        continue;
      }
      plots.push({ name: name, lat: lat, lon: lon });
    }
    return { plots: plots, errors: errors };
  }

  async function convertCSVToKml() {
    var textarea = document.getElementById('app-csv-input');
    var statusEl = document.getElementById('app-csv-status');
    var convertBtn = document.getElementById('app-csv-convert-btn');
    if (!textarea || !statusEl) return;

    var text = textarea.value.trim();
    if (!text) {
      statusEl.hidden = false;
      statusEl.setAttribute('data-tone', 'error');
      statusEl.textContent = 'Paste coordinate data first.';
      return;
    }

    var parsed = parseCSVCoordinates(text);
    if (parsed.errors.length > 0 && parsed.plots.length === 0) {
      statusEl.hidden = false;
      statusEl.setAttribute('data-tone', 'error');
      statusEl.textContent = parsed.errors.join('; ');
      return;
    }
    if (parsed.plots.length === 0) {
      statusEl.hidden = false;
      statusEl.setAttribute('data-tone', 'error');
      statusEl.textContent = 'No valid coordinates found.';
      return;
    }

    if (convertBtn) { convertBtn.disabled = true; convertBtn.textContent = 'Converting…'; }
    statusEl.hidden = false;
    statusEl.setAttribute('data-tone', 'info');
    var warningText = parsed.errors.length > 0 ? ' (' + parsed.errors.length + ' rows skipped)' : '';
    statusEl.textContent = 'Converting ' + parsed.plots.length + ' parcels…' + warningText;

    try {
      await apiDiscoveryReady;
      var res = await apiFetch('/api/convert-coordinates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_name: 'EUDR Parcels', buffer_m: 100, plots: parsed.plots })
      });
      var kmlText = await res.text();

      // Put converted KML into the KML textarea and switch to KML tab
      var kmlTextarea = document.getElementById('app-analysis-kml');
      if (kmlTextarea) {
        kmlTextarea.value = kmlText;
        updateAnalysisPreflight(kmlText);
      }
      switchInputTab('kml');
      statusEl.hidden = true;

      var fileNote = document.getElementById('app-analysis-file-note');
      if (fileNote) fileNote.textContent = 'Generated from ' + parsed.plots.length + ' coordinate' + (parsed.plots.length !== 1 ? 's' : '') + '.';
    } catch (err) {
      statusEl.setAttribute('data-tone', 'error');
      statusEl.textContent = (err.body && err.body.error) || 'Coordinate conversion failed. Check your data and try again.';
    } finally {
      if (convertBtn) { convertBtn.disabled = false; convertBtn.textContent = 'Convert to KML'; }
    }
  }

  function updateAnalysisPreflight(text) {
    var headlineEl = document.getElementById('app-preflight-headline');
    var modeEl = document.getElementById('app-preflight-mode');
    var summaryEl = document.getElementById('app-preflight-summary');
    var featuresEl = document.getElementById('app-preflight-features');
    var aoisEl = document.getElementById('app-preflight-aois');
    var spreadEl = document.getElementById('app-preflight-spread');
    var quotaEl = document.getElementById('app-preflight-quota');
    var costEl = document.getElementById('app-preflight-cost');
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
      if (costEl) costEl.textContent = '—';
      renderPreflightWarnings([{ tone: 'info', text: 'Preflight will show warnings here after you paste or upload KML.' }]);
      renderPreflightMap(null);
      var submitBtn = document.getElementById('app-analysis-submit-btn');
      if (submitBtn) submitBtn.textContent = 'Queue Analysis';
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
      if (costEl) costEl.textContent = '—';
      renderPreflightWarnings([{ tone: 'error', text: preflight.error }]);
      renderPreflightMap(null);
      return preflight;
    }

    headlineEl.textContent = preflight.aoiCount + '-AOI request ready';
    modeEl.textContent = preflight.processingMode;
    summaryEl.textContent = preflight.summary;
    featuresEl.textContent = String(preflight.featureCount);
    aoisEl.textContent = String(preflight.aoiCount);
    spreadEl.textContent = formatDistance(preflight.maxSpreadKm);
    quotaEl.textContent = preflight.quotaImpact;
    if (costEl) costEl.textContent = computeEudrCostEstimate(preflight.aoiCount);
    renderPreflightWarnings(preflight.warnings);
    renderPreflightMap(preflight.polygons);
    var submitBtn = document.getElementById('app-analysis-submit-btn');
    if (submitBtn) submitBtn.textContent = 'Confirm & Queue';
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
    const thisGeneration = ++analysisPollGeneration;
    let consecutiveFailures = 0;
    const MAX_CONSECUTIVE_FAILURES = 5;

    async function refreshRun() {
      // Bail out if a newer poll has started while we were awaiting.
      if (analysisPollGeneration !== thisGeneration) return null;
      try {
        var res = await apiFetch('/api/orchestrator/' + instanceId);
        var data = await res.json();
        consecutiveFailures = 0;
        // Re-check after await — another selectAnalysisRun may have fired.
        if (analysisPollGeneration !== thisGeneration) return null;
        upsertAnalysisHistoryRun(data);
        updateAnalysisRun(data);

        var runtime = data.runtimeStatus || '';
        var phase = mapAnalysisPhase(data.customStatus, runtime);
        setAnalysisProgressVisible(true);
        if (runtime === 'Completed') {
          stopAnalysisPolling();
          setAnalysisStep('complete', 'done');
          updateAnalysisStory('complete', runtime, data);
          clearCacheKey('billing');
          clearCacheKey('history');
          loadBillingStatus();
          loadAnalysisHistory({ preferInstanceId: instanceId });
          loadRunEvidence(instanceId);
          var evidenceHero = document.getElementById('app-evidence-hero');
          if (evidenceHero) {
            setTimeout(function() {
              var scrollBehavior = 'smooth';
              if (typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
                scrollBehavior = 'auto';
              }
              evidenceHero.scrollIntoView({ behavior: scrollBehavior, block: 'start' });
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
        consecutiveFailures++;
        if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
          stopAnalysisPolling();
          setAnalysisStatus('Connection lost — pipeline updates have stopped. Reload the page to resume.', 'error');
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

    activeAnalysisPoll = setInterval(function() {
      refreshRun();
    }, 3000);
  }

  async function queueAnalysis() {
    if (!currentAccount) {
      login();
      return;
    }

    // EUDR entitlement gate: show subscribe modal when trial is exhausted.
    // If billing hasn't loaded yet, fetch it before deciding.
    if (EUDR_LOCKED && typeof window.eudrBillingData === 'function') {
      var billing = window.eudrBillingData();
      if (!billing) {
        try {
          await apiDiscoveryReady;
          var billingRes = await apiFetch('/api/eudr/billing');
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

      // EUDR compliance mode (#600)
      var eudrCheckbox = document.getElementById('app-eudr-mode');
      if (eudrCheckbox && eudrCheckbox.checked) {
        tokenBody.eudr_mode = true;
      }

      var tokenRes;
      try {
        tokenRes = await apiFetch('/api/upload/token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(tokenBody)
        });
      } catch (tokenFetchErr) {
        // 401 is handled centrally by apiFetch (clears session, shows re-login prompt).
        if (tokenFetchErr.status === 401) {
          resetAnalysisProgress();
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
      clearCacheKey('history');
      clearCacheKey('billing');
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
      selectAnalysisRun(data.instance_id, { resume: true });
      setAnalysisStatus('Analysis queued. The app will walk through each stage as the pipeline advances.', 'info');
      loadBillingStatus();
    } catch (err) {
      console.error('queueAnalysis failed:', err);
      setAnalysisStatus('Could not queue analysis request.', 'error');
      resetAnalysisProgress();
    } finally {
      button.disabled = false;
      button.textContent = analysisDraftSummary && !analysisDraftSummary.error ? 'Confirm & Queue' : 'Queue Analysis';
    }
  }

  async function manageBilling() {
    // If billing is gated for this user, redirect to express interest
    if (latestBillingStatus && latestBillingStatus.billing_gated) {
      window.location.href = 'mailto:hello@canopex.io';
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

    // Show EUDR toggle only for paid tiers
    var eudrToggle = document.getElementById('app-eudr-toggle');
    if (eudrToggle) {
      var paidTiers = ['starter', 'pro', 'team', 'enterprise'];
      eudrToggle.hidden = !paidTiers.includes(data.tier);
    }
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
      clearCacheKey('billing');
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

    // Render cached billing data instantly while fetching fresh data
    const cached = readCache('billing');
    if (cached) applyBillingStatus(cached);

    try {
      const res = await apiFetch('/api/billing/status');
      const data = await res.json();
      writeCache('billing', data, CACHE_TTL_BILLING);
      applyBillingStatus(data);
    } catch {
      // Only show error state if we had no cached data to show
      if (!cached) {
        document.getElementById('app-tier').textContent = 'Unknown';
        document.getElementById('app-subscription-status').textContent = 'Unavailable';
        document.getElementById('app-runs-remaining').textContent = '—';
        document.getElementById('app-billing-note').textContent = 'Could not load billing state';
        document.getElementById('app-manage-billing-btn').style.display = 'none';
        updateCapabilityFields({});
        setHeroRunSummary('Ready to queue', 'Billing is unavailable, but analysis can still be launched locally.');
      }
    }
  }

  async function loadAnalysisHistory(options) {
    await apiDiscoveryReady;
    if (!currentAccount && authEnabled()) return;

    var historyScope = EUDR_LOCKED ? 'org' : 'user';
    var historyCacheKey = historyScope === 'org' ? 'history-org' : 'history';

    // Render cached history instantly while fetching fresh data
    const cached = readCache(historyCacheKey);
    if (cached && !analysisHistoryLoaded) {
      analysisHistoryLoaded = true;
      applyAnalysisHistory(cached, options || {});
      applyFirstRunLayout();
    }

    try {
      const res = await apiFetch('/api/analysis/history?limit=6&scope=' + encodeURIComponent(historyScope));
      const data = await res.json();
      writeCache(historyCacheKey, data, CACHE_TTL_HISTORY);
      analysisHistoryLoaded = true;
      applyAnalysisHistory(data, options || {});
      applyFirstRunLayout();
    } catch {
      analysisHistoryLoaded = true;
      if (!cached && !analysisHistoryRuns.length && !latestAnalysisRun) {
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
        window.history.replaceState({}, '', nextUrl || APP_BASE);
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
        // Acquire HMAC session token for principal verification (#534).
        // Waits for API base discovery so the request goes to the right host.
        (apiDiscoveryReady || Promise.resolve()).then(function() {
          return apiFetch('/api/auth/session', { method: 'POST' });
        }).then(function(resp) { return resp.json(); }).then(function(data) {
          if (data && data.token) _sessionToken = data.token;
        }).catch(function() { /* session token unavailable — backend may not enforce HMAC */ });
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
  if (EUDR_LOCKED) {
    workspaceRole = 'eudr';
    workspacePreference = 'report';
  } else {
    workspaceRole = readStoredUiValue(WORKSPACE_ROLE_STORAGE_KEY) || workspaceRole;
    workspacePreference = readStoredUiValue(WORKSPACE_PREFERENCE_STORAGE_KEY) || workspacePreference;
  }
  renderWorkspaceGuidance();

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

  // Bind click handlers — guarded for elements that only exist on some pages.
  function bindClick(id, handler) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('click', handler);
  }
  bindClick('auth-login-btn', login);
  bindClick('auth-logout-btn', logout);
  bindClick('app-sign-in-btn', login);
  bindClick('app-analysis-sign-in-btn', login);
  bindClick('app-manage-billing-btn', manageBilling);
  bindClick('app-apply-tier-emulation-btn', saveTierEmulation);
  bindClick('app-guided-primary-btn', function() {
    revealWorkflowTarget(this.getAttribute('data-target') || currentPreferenceConfig().primaryTarget);
  });
  bindClick('app-guided-secondary-btn', function() {
    revealWorkflowTarget(this.getAttribute('data-target') || currentPreferenceConfig().secondaryTarget);
  });
  bindClick('app-analysis-submit-btn', queueAnalysis);
  bindClick('app-run-link', function(event) {
    const href = this.href;
    if (!href) return;
    if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') {
      return; // Let normal navigation proceed
    }
    const fullUrl = new URL(href, window.location.origin).href;
    event.preventDefault();
    const el = document.getElementById('app-run-link');
    try {
      navigator.clipboard.writeText(fullUrl).then(function() {
        if (el._copyTimer) clearTimeout(el._copyTimer);
        const prev = el.textContent;
        el.textContent = 'Link copied!';
        el._copyTimer = setTimeout(function() {
          if (el.textContent === 'Link copied!') el.textContent = prev;
          el._copyTimer = null;
        }, 1500);
      }).catch(function() {
        window.location.href = href;
      });
    } catch (_) {
      window.location.href = href;
    }
  });
  document.querySelectorAll('[data-export-format]').forEach(function(button) {
    button.addEventListener('click', function(event) {
      event.stopPropagation();
      downloadRunExport(button.getAttribute('data-export-format'));
    });
  });

  // Bind remaining controls — guarded so pages that omit elements don't crash.
  var kmlInput = document.getElementById('app-analysis-kml');
  if (kmlInput) kmlInput.addEventListener('input', function() { updateAnalysisPreflight(this.value); });
  var fileInput = document.getElementById('app-analysis-file');
  if (fileInput) fileInput.addEventListener('change', function() { if (this.files && this.files[0]) loadAnalysisFile(this.files[0]); });

  // Input tab switching (KML / CSV)
  document.querySelectorAll('[data-input-tab]').forEach(function(tab) {
    tab.addEventListener('click', function() { switchInputTab(this.getAttribute('data-input-tab')); });
  });
  bindClick('app-csv-convert-btn', convertCSVToKml);

  // Evidence surface controls
  bindClick('app-map-play-btn', toggleEvidencePlay);
  var frameSlider = document.getElementById('app-map-frame-slider');
  if (frameSlider) frameSlider.addEventListener('input', function() { showEvidenceFrame(parseInt(this.value, 10)); });
  bindClick('app-map-btn-rgb', function() {
    evidenceLayerMode = 'rgb';
    document.getElementById('app-map-btn-rgb').classList.add('active');
    document.getElementById('app-map-btn-ndvi').classList.remove('active');
    showEvidenceFrame(evidenceFrameIndex);
  });
  bindClick('app-map-btn-ndvi', function() {
    evidenceLayerMode = 'ndvi';
    document.getElementById('app-map-btn-ndvi').classList.add('active');
    document.getElementById('app-map-btn-rgb').classList.remove('active');
    showEvidenceFrame(evidenceFrameIndex);
  });
  bindClick('app-evidence-ai-btn', requestAiAnalysis);
  bindClick('app-evidence-eudr-btn', requestEudrAssessment);

  // Expanded map viewer controls
  bindClick('app-map-expand-btn', expandEvidenceMap);
  bindClick('app-map-collapse-btn', collapseEvidenceMap);
  bindClick('app-map-btn-compare', toggleCompareView);  // #671 before/after comparison
  var expandedBackdrop = document.getElementById('app-map-expanded-backdrop');
  if (expandedBackdrop) expandedBackdrop.addEventListener('click', function(e) { if (e.target === this) collapseEvidenceMap(); });
  bindClick('app-map-expanded-play-btn', toggleEvidencePlay);
  var expandedSlider = document.getElementById('app-map-expanded-slider');
  if (expandedSlider) expandedSlider.addEventListener('input', function() { showEvidenceFrame(parseInt(this.value, 10)); });
  bindClick('app-map-expanded-btn-rgb', function() {
    evidenceLayerMode = 'rgb';
    document.getElementById('app-map-expanded-btn-rgb').classList.add('active');
    document.getElementById('app-map-expanded-btn-ndvi').classList.remove('active');
    document.getElementById('app-map-btn-rgb').classList.add('active');
    document.getElementById('app-map-btn-ndvi').classList.remove('active');
    showEvidenceFrame(evidenceFrameIndex);
  });
  bindClick('app-map-expanded-btn-ndvi', function() {
    evidenceLayerMode = 'ndvi';
    document.getElementById('app-map-expanded-btn-ndvi').classList.add('active');
    document.getElementById('app-map-expanded-btn-rgb').classList.remove('active');
    document.getElementById('app-map-btn-ndvi').classList.add('active');
    document.getElementById('app-map-btn-rgb').classList.remove('active');
    showEvidenceFrame(evidenceFrameIndex);
  });
})();
