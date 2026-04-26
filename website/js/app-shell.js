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
  var parseCSVCoordinates = CanopexGeo.parseCSVCoordinates;

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

  var coreDom = window.CanopexCoreDom || {};
  var coreState = window.CanopexCoreState || {};
  var appProfiles = window.CanopexAppProfiles || {};
  var appRuns = window.CanopexAppRuns || {};
  var evidenceMapModule = window.CanopexEvidenceMap || {};
  var eudrModule = window.CanopexEudr || {};
  var billingModule = window.CanopexBilling || {};
  var evidencePanelsModule = window.CanopexEvidencePanels || {};
  var preflightModule = window.CanopexAnalysisPreflight || {};
  var progressModule = window.CanopexAnalysisProgress || {};
  var evidenceDisplayModule = window.CanopexEvidenceDisplay || {};
  var authModule = window.CanopexAuth || {};
  var bindingsModule = window.CanopexBindings || {};
  var _apiClient = window.CanopexApiClient ? window.CanopexApiClient.createClient() : null;

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

  const activeProfile = (typeof appProfiles.resolveActiveProfile === 'function')
    ? appProfiles.resolveActiveProfile()
    : {
      id: document.body.hasAttribute('data-eudr-app') ? 'eudr' : 'default',
      basePath: document.body.hasAttribute('data-eudr-app') ? '/eudr/' : '/app/',
      historyScope: document.body.hasAttribute('data-eudr-app') ? 'org' : 'user',
      lockedWorkspace: document.body.hasAttribute('data-eudr-app'),
      defaultRole: document.body.hasAttribute('data-eudr-app') ? 'eudr' : 'conservation',
      defaultPreference: document.body.hasAttribute('data-eudr-app') ? 'report' : 'investigate',
      enableParcelCostEstimate: document.body.hasAttribute('data-eudr-app'),
      requiresEudrBillingGate: document.body.hasAttribute('data-eudr-app'),
      phaseDetails: null,
    };

  // Resolved app lock state from profile contract.
  const EUDR_LOCKED = !!activeProfile.lockedWorkspace;

  // Base path for the current app entry (/eudr/ or /app/).
  const APP_BASE = activeProfile.basePath || (EUDR_LOCKED ? '/eudr/' : '/app/');

  // Null-safe DOM text setter — used when elements may not exist
  // on all pages (e.g. settings panel absent on EUDR app).
  function setText(id, value) {
    if (typeof coreDom.setText === 'function') {
      coreDom.setText(id, value);
      return;
    }
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function createApiClient() {
    if (!window.CanopexApiClient || typeof window.CanopexApiClient.createClient !== 'function') {
      throw new Error('[canopex] canopex-api-client.js must be loaded before app-shell.js');
    }
    return window.CanopexApiClient.createClient({
      statusBadgeId: 'status-badge',
    });
  }

  let apiDiscoveryReady = null;
  const apiClient = createApiClient();

  // Container Apps FA: API calls go cross-origin to the Function App
  // hostname discovered from /api-config.json (injected at deploy time).
  // Auth state managed by CanopexApiClient (canopex-api-client.js).
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

  async function discoverApiBase() {
    if (_apiClient) return _apiClient.discoverApiBase();
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
    try {
      return await _apiClient.fetch(path, opts);
    } catch (err) {
      if (err.status === 401 && authEnabled()) {
        // Session expired — clear local auth state and prompt re-login.
        currentAccount = null;
        _apiClient.clearAuth();
        updateAuthUI();
        setAnalysisStatus('Your session has expired. Please sign in again.', 'error');
        stopAnalysisPolling();
      }
      throw err;
    }
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
    if (typeof coreState.readStoredValue === 'function') {
      return coreState.readStoredValue(key);
    }
    try { return localStorage.getItem(key); } catch { return null; }
  }

  function storeUiValue(key, value) {
    if (typeof coreState.storeValue === 'function') {
      coreState.storeValue(key, value);
      return;
    }
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
    if (typeof coreState.set === 'function') coreState.set('workspaceRole', roleKey);
    if (!options || options.persist !== false) storeUiValue(WORKSPACE_ROLE_STORAGE_KEY, roleKey);
    renderWorkspaceGuidance();
  }

  function setWorkspacePreference(preferenceKey, options) {
    if (!WORKSPACE_PREFERENCES[preferenceKey]) return;
    workspacePreference = preferenceKey;
    if (typeof coreState.set === 'function') coreState.set('workspacePreference', preferenceKey);
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

    // Show the summary export button when org scope is active (#674)
    var exportRow = document.getElementById('app-summary-export-row');
    if (exportRow) exportRow.hidden = false;
  }

  function normalizeAnalysisRun(run) {
    if (typeof appRuns.normalizeRun === 'function') {
      return appRuns.normalizeRun(run);
    }
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
    if (typeof appRuns.sortRuns === 'function') {
      return appRuns.sortRuns(runs, parseStatusTimestamp);
    }
    return (runs || [])
      .map(normalizeAnalysisRun)
      .filter(Boolean)
      .sort(function(a, b) {
        return historyRunSortValue(b) - historyRunSortValue(a);
      });
  }

  function historyRunIsActive(run) {
    if (typeof appRuns.isRunActive === 'function') {
      return appRuns.isRunActive(run);
    }
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
    if (typeof appRuns.upsertRun === 'function') {
      analysisHistoryRuns = appRuns.upsertRun(analysisHistoryRuns, run, parseStatusTimestamp);
      renderAnalysisHistoryList();
      applyFirstRunLayout();
      return;
    }

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
    if (typeof evidenceDisplayModule.stopPlay === 'function') evidenceDisplayModule.stopPlay();
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

    if (typeof appRuns.applyHistoryPayload === 'function') {
      var applied = appRuns.applyHistoryPayload(
        payload,
        options,
        selectedAnalysisRunId,
        latestAnalysisRun,
        locationSelection.instanceId,
        parseStatusTimestamp
      );

      latestPortfolioSummary = applied.portfolioSummary;
      analysisHistoryRuns = applied.runs;

      if (!applied.selectedId) {
        selectedAnalysisRunId = null;
        updateRunSelectionLocation('');
        stopAnalysisPolling();
        resetAnalysisProgress();
        renderAnalysisHistoryList();
        updateAnalysisRun(null);
        updateHistorySummary(null);
        return;
      }

      var selectedRun = analysisHistoryRuns.find(function(run) { return run.instanceId === applied.selectedId; });
      selectAnalysisRun(applied.selectedId, { resume: historyRunIsActive(selectedRun) });
      return;
    }

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
  /*  Evidence surface — delegated to app-evidence-display.js           */
  /* ------------------------------------------------------------------ */

  function loadRunEvidence(instanceId) {
    if (typeof evidenceDisplayModule.load === 'function') return evidenceDisplayModule.load(instanceId);
  }

  function clearEvidencePanels() {
    if (typeof evidenceDisplayModule.clear === 'function') return evidenceDisplayModule.clear();
  }

  function showEvidenceSurface(visible) {
    if (typeof evidenceDisplayModule.showSurface === 'function') return evidenceDisplayModule.showSurface(visible);
  }

  function expandEvidenceMap() {
    if (typeof evidenceDisplayModule.expand === 'function') return evidenceDisplayModule.expand();
  }

  function collapseEvidenceMap() {
    if (typeof evidenceDisplayModule.collapse === 'function') return evidenceDisplayModule.collapse();
  }

  function showEvidenceFrame(idx) {
    if (typeof evidenceDisplayModule.showFrame === 'function') return evidenceDisplayModule.showFrame(idx);
  }

  function setEvidenceLayerMode(mode) {
    if (typeof evidenceDisplayModule.setLayerMode === 'function') return evidenceDisplayModule.setLayerMode(mode);
  }

  function toggleCompareView() {
    if (typeof evidenceDisplayModule.toggleCompare === 'function') return evidenceDisplayModule.toggleCompare();
  }

  function toggleEvidencePlay() {
    if (typeof evidenceDisplayModule.togglePlay === 'function') return evidenceDisplayModule.togglePlay();
  }

  function requestAiAnalysis() {
    if (typeof evidenceDisplayModule.requestAi === 'function') return evidenceDisplayModule.requestAi();
  }

  function requestEudrAssessment() {
    if (typeof evidenceDisplayModule.requestEudr === 'function') return evidenceDisplayModule.requestEudr();
  }

  /* ---- Parcel notes (#669) — delegated to app-evidence-panels.js ---- */

  var currentNoteParcelKey = null;

  function parcelKeyForIndex(idx) {
    if (typeof evidencePanelsModule.parcelKeyForIndex === 'function') return evidencePanelsModule.parcelKeyForIndex(idx);
    return String(idx);
  }

  function renderParcelNotes(parcelKey) {
    if (typeof evidencePanelsModule.renderParcelNotes === 'function') return evidencePanelsModule.renderParcelNotes(parcelKey);
  }

  function showNoteEditor() {
    if (typeof evidencePanelsModule.showNoteEditor === 'function') return evidencePanelsModule.showNoteEditor();
  }

  function hideNoteEditor() {
    if (typeof evidencePanelsModule.hideNoteEditor === 'function') return evidencePanelsModule.hideNoteEditor();
  }

  async function saveParcelNote() {
    if (typeof evidencePanelsModule.saveParcelNote === 'function') return evidencePanelsModule.saveParcelNote();
  }

  /* ---- Human override (#672) — delegated to app-evidence-panels.js ---- */

  var currentOverrideParcelKey = null;
  var currentOverrideAoiData = null;

  function renderParcelOverride(parcelKey, aoiData) {
    if (typeof evidencePanelsModule.renderParcelOverride === 'function') return evidencePanelsModule.renderParcelOverride(parcelKey, aoiData);
  }

  function openOverrideModal(parcelKey, aoiData) {
    if (typeof evidencePanelsModule.openOverrideModal === 'function') return evidencePanelsModule.openOverrideModal(parcelKey, aoiData);
  }

  function closeOverrideModal() {
    if (typeof evidencePanelsModule.closeOverrideModal === 'function') return evidencePanelsModule.closeOverrideModal();
  }

  function onOverrideReasonInput() {
    if (typeof evidencePanelsModule.onOverrideReasonInput === 'function') return evidencePanelsModule.onOverrideReasonInput();
  }

  async function confirmOverride() {
    if (typeof evidencePanelsModule.confirmOverride === 'function') return evidencePanelsModule.confirmOverride();
  }

  async function revertOverride() {
    if (typeof evidencePanelsModule.revertOverride === 'function') return evidencePanelsModule.revertOverride();
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
    var phaseCopy = (activeProfile.contentPhaseCopy && activeProfile.contentPhaseCopy[phase]) || {};

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
      imageryNoteEl.textContent = phaseCopy.imageryNote || 'NAIP and Sentinel-2 discovery is in progress so the run can pick the right source imagery.';
      enrichmentEl.textContent = 'Queued behind acquisition';
      enrichmentNoteEl.textContent = 'Context layers are staged after the imagery stack is selected.';
      exportsEl.textContent = 'Awaiting artefacts';
      exportsNoteEl.textContent = phaseCopy.exportsNote || 'There is nothing to export until imagery is actually acquired.';
      return;
    }

    if (phase === 'fulfilment') {
      imageryEl.textContent = 'Clipping and reprojection';
      imageryNoteEl.textContent = phaseCopy.imageryNote || 'The pipeline is producing imagery assets for your analysis.';
      enrichmentEl.textContent = 'Preparing next';
      enrichmentNoteEl.textContent = phaseCopy.enrichmentNote || 'NDVI and weather context will follow immediately after fulfilment finishes.';
      exportsEl.textContent = 'Outputs staging next';
      exportsNoteEl.textContent = phaseCopy.exportsNote || 'The run is close enough that saved outputs should feel tangible, not hypothetical.';
      return;
    }

    imageryEl.textContent = 'Imagery stack stabilizing';
    imageryNoteEl.textContent = phaseCopy.imageryNote || 'Core imagery is in place and the workspace is adding the last supporting layers.';
    enrichmentEl.textContent = 'Context packaging';
    enrichmentNoteEl.textContent = phaseCopy.enrichmentNote || 'NDVI, weather, and derived context are being assembled for the run detail experience.';
    exportsEl.textContent = 'Preparing results view';
    exportsNoteEl.textContent = phaseCopy.exportsNote || 'Saved outputs, exports, and revisit paths will be available shortly.';
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

  /* ---- Analysis progress UI — delegated to app-analysis-progress.js ---- */

  function resetAnalysisProgress() {
    if (typeof progressModule.reset === 'function') return progressModule.reset();
  }

  function setAnalysisProgressVisible(visible) {
    if (typeof progressModule.setVisible === 'function') return progressModule.setVisible(visible);
  }

  function setAnalysisStep(phase, state) {
    if (typeof progressModule.setStep === 'function') return progressModule.setStep(phase, state);
  }

  function mapAnalysisPhase(customStatus, runtimeStatus) {
    if (typeof progressModule.mapPhase === 'function') return progressModule.mapPhase(customStatus, runtimeStatus);
    if (typeof appRuns.mapPhase === 'function') return appRuns.mapPhase(customStatus, runtimeStatus, ANALYSIS_PHASES);
    if (runtimeStatus === 'Completed') return 'complete';
    if (customStatus && customStatus.phase && ANALYSIS_PHASES.indexOf(customStatus.phase) > -1) return customStatus.phase;
    return 'submit';
  }

  function updateAnalysisStory(phase, runtimeStatus, data) {
    if (typeof progressModule.updateStory === 'function') return progressModule.updateStory(phase, runtimeStatus, data);
  }

  /* ---- Analysis preflight + file input — delegated to app-analysis-preflight.js ---- */

  function buildPreflightWarnings(preflight) {
    if (typeof preflightModule.buildAnalysisPreflight === 'function') {
      // Warnings are generated inside updateAnalysisPreflight; expose for queueAnalysis use.
    }
    // Fallback: basic check only — real logic is in the module.
    return [{ tone: 'info', text: 'No warnings. This will queue as one tracked analysis run.' }];
  }

  function updateAnalysisPreflight(text) {
    if (typeof preflightModule.updateAnalysisPreflight === 'function') return preflightModule.updateAnalysisPreflight(text);
    return null;
  }

  function loadAnalysisFile(file) {
    if (typeof preflightModule.loadAnalysisFile === 'function') return preflightModule.loadAnalysisFile(file);
  }

  function switchInputTab(tabName) {
    if (typeof preflightModule.switchInputTab === 'function') return preflightModule.switchInputTab(tabName);
  }

  async function convertCSVToKml() {
    if (typeof preflightModule.convertCSVToKml === 'function') return preflightModule.convertCSVToKml();
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
    if (activeProfile.requiresEudrBillingGate && typeof window.eudrBillingData === 'function') {
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
    if (typeof billingModule.manage === 'function') return billingModule.manage();
    // fallback: redirect to interest mailto
    window.location.href = 'mailto:hello@canopex.io';
  }

  // updateCapabilityFields and renderTierEmulation are internal to app-billing.js

  function applyBillingStatus(data) {
    if (typeof billingModule.apply === 'function') return billingModule.apply(data);
    // fallback: update shell state only
    latestBillingStatus = data;
    updateHeroSummary(data);
  }

  async function saveTierEmulation() {
    if (typeof billingModule.saveEmulation === 'function') return billingModule.saveEmulation();
  }

  async function loadBillingStatus() {
    if (typeof billingModule.load === 'function') return billingModule.load();
  }

  /* ---- EUDR usage dashboard (#670) ---- */

  async function loadEudrUsage() {
    if (typeof eudrModule.loadUsage === 'function') return eudrModule.loadUsage();
    // fallback: silently skip when module not loaded
  }

  async function loadAnalysisHistory(options) {
    await apiDiscoveryReady;
    if (!currentAccount && authEnabled()) return;

    var historyScope = activeProfile.historyScope || 'user';
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

  /* ---- Auth UI + bootstrap — delegated to app-auth.js ---- */

  function updateAuthUI() {
    if (typeof authModule.updateAuthUI === 'function') return authModule.updateAuthUI();
  }

  function initAuth() {
    if (typeof authModule.initAuth === 'function') return authModule.initAuth();
  }

  apiDiscoveryReady = discoverApiBase();

  // Initialise billing module before auth so loadBillingStatus works on first sign-in.
  if (typeof billingModule.init === 'function') {
    billingModule.init({
      apiFetch: apiFetch,
      getApiReady: function () { return apiDiscoveryReady; },
      getAccount: function () { return currentAccount; },
      login: login,
      readCache: readCache,
      writeCache: writeCache,
      clearCacheKey: clearCacheKey,
      onStatusChange: function (data) {
        latestBillingStatus = data;
        updateHeroSummary(data);
      },
      onLoadError: function () {
        setHeroRunSummary('Ready to queue', 'Billing is unavailable, but analysis can still be launched locally.');
      }
    });
  }

  if (typeof eudrModule.init === 'function') {
    eudrModule.init({
      apiFetch: apiFetch,
      getApiReady: function () { return apiDiscoveryReady; },
      getAccount: function () { return currentAccount; },
    });
  }

  if (typeof evidencePanelsModule.init === 'function') {
    evidencePanelsModule.init({
      apiFetch: apiFetch,
      getApiReady: function () { return apiDiscoveryReady; },
      getManifest: function () { return evidenceDisplayModule.getManifest ? evidenceDisplayModule.getManifest() : null; },
      getInstanceId: function () { return evidenceDisplayModule.getInstanceId ? evidenceDisplayModule.getInstanceId() : null; },
    });
  }

  if (typeof evidenceDisplayModule.init === 'function') {
    evidenceDisplayModule.init({
      apiFetch: apiFetch,
      getApiReady: function () { return apiDiscoveryReady; },
      getWorkspaceRole: function () { return workspaceRole; },
      getLatestBillingStatus: function () { return latestBillingStatus; },
    });
  }

  if (typeof preflightModule.init === 'function') {
    preflightModule.init({
      apiFetch: apiFetch,
      getApiReady: function () { return apiDiscoveryReady; },
      getWorkspaceRole: function () { return workspaceRole; },
      getActiveProfile: function () { return activeProfile; },
      getLatestBillingStatus: function () { return latestBillingStatus; },
      getWorkspaceRoleConfig: function () { return currentRoleConfig(); },
      onPreflightUpdate: function (preflight) { analysisDraftSummary = preflight; },
    });
  }

  if (typeof progressModule.init === 'function') {
    progressModule.init({
      setAnalysisStatus: setAnalysisStatus,
      getActiveProfile: function () { return activeProfile; },
      getAnalysisPhases: function () { return ANALYSIS_PHASES; },
      getAnalysisPhaseDetails: function () { return ANALYSIS_PHASE_DETAILS; },
      summarizeRunTiming: summarizeRunTiming,
    });
  }

  if (typeof authModule.init === 'function') {
    authModule.init({
      authEnabled: authEnabled,
      getApiReady: function () { return apiDiscoveryReady; },
      getAccount: function () { return currentAccount; },
      setAccount: function (account) { currentAccount = account; },
      setClientPrincipal: function (p) { if (_apiClient) _apiClient.setClientPrincipal(p); },
      setSessionToken: function (t) { if (_apiClient) _apiClient.setSessionToken(t); },
      apiFetch: apiFetch,
      getAppBase: function () { return APP_BASE; },
      loadAnalysisHistory: loadAnalysisHistory,
      loadBillingStatus: loadBillingStatus,
      loadEudrUsage: loadEudrUsage,
      setHeroRunSummary: setHeroRunSummary,
      updateHistorySummary: updateHistorySummary,
      renderAnalysisHistoryList: renderAnalysisHistoryList,
      stopAnalysisPolling: stopAnalysisPolling,
      resetAnalysisProgress: resetAnalysisProgress,
      updateAnalysisRun: updateAnalysisRun,
      getAnalysisHistoryLoaded: function () { return analysisHistoryLoaded; },
      getLatestAnalysisRun: function () { return latestAnalysisRun; },
      clearAnalysisState: function () {
        analysisHistoryRuns = [];
        analysisHistoryLoaded = false;
        selectedAnalysisRunId = null;
      },
    });
  }

  initAuth();
  if (EUDR_LOCKED) {
    workspaceRole = activeProfile.defaultRole || 'eudr';
    workspacePreference = activeProfile.defaultPreference || 'report';
  } else {
    workspaceRole = readStoredUiValue(WORKSPACE_ROLE_STORAGE_KEY) || workspaceRole;
    workspacePreference = readStoredUiValue(WORKSPACE_PREFERENCE_STORAGE_KEY) || workspacePreference;
  }
  if (typeof coreState.set === 'function') {
    coreState.set('workspaceRole', workspaceRole);
    coreState.set('workspacePreference', workspacePreference);
  }
  renderWorkspaceGuidance();

  // All DOM event bindings — delegated to app-bindings.js
  if (typeof bindingsModule.init === 'function') {
    bindingsModule.init({
      // auth
      login: login,
      logout: logout,
      manageBilling: manageBilling,
      saveTierEmulation: saveTierEmulation,
      // workspace guidance
      setWorkspaceRole: setWorkspaceRole,
      setWorkspacePreference: setWorkspacePreference,
      revealWorkflowTarget: revealWorkflowTarget,
      currentPreferenceConfig: currentPreferenceConfig,
      // analysis
      queueAnalysis: queueAnalysis,
      downloadRunExport: downloadRunExport,
      updateAnalysisPreflight: updateAnalysisPreflight,
      loadAnalysisFile: loadAnalysisFile,
      switchInputTab: switchInputTab,
      convertCSVToKml: convertCSVToKml,
      // evidence surface
      toggleEvidencePlay: toggleEvidencePlay,
      showEvidenceFrame: showEvidenceFrame,
      setEvidenceLayerMode: setEvidenceLayerMode,
      requestAiAnalysis: requestAiAnalysis,
      requestEudrAssessment: requestEudrAssessment,
      expandEvidenceMap: expandEvidenceMap,
      collapseEvidenceMap: collapseEvidenceMap,
      toggleCompareView: toggleCompareView,
      getOverrideContext: function () {
        return evidenceDisplayModule.getOverrideContext ? evidenceDisplayModule.getOverrideContext() : {};
      },
      // parcel notes / override
      showNoteEditor: showNoteEditor,
      hideNoteEditor: hideNoteEditor,
      saveParcelNote: saveParcelNote,
      openOverrideModal: openOverrideModal,
      closeOverrideModal: closeOverrideModal,
      confirmOverride: confirmOverride,
      revertOverride: revertOverride,
      onOverrideReasonInput: onOverrideReasonInput,
      // API access for export
      apiFetch: apiFetch,
    });
  }
})();
