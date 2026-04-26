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
  var runLifecycleModule = window.CanopexRunLifecycle || {};
  var historyUiModule = window.CanopexHistoryUi || {};
  var summaryUiModule = window.CanopexSummaryUi || {};
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

  function readCache(key) {
    return coreState.readScopedCache
      ? coreState.readScopedCache(CACHE_PREFIX, currentAccount && currentAccount.userId, key)
      : null;
  }

  function writeCache(key, data, ttlMs) {
    if (coreState.writeScopedCache) {
      coreState.writeScopedCache(CACHE_PREFIX, currentAccount && currentAccount.userId, key, data, ttlMs);
    }
  }

  function clearCacheKey(key) {
    if (coreState.clearScopedCacheKey) {
      coreState.clearScopedCacheKey(CACHE_PREFIX, currentAccount && currentAccount.userId, key);
    }
  }

  function clearAllCache() {
    if (coreState.clearAllScopedCache) {
      coreState.clearAllScopedCache(CACHE_PREFIX);
    }
  }

  function authEnabled() {
    return typeof authModule.authEnabled === 'function' ? authModule.authEnabled() : true;
  }

  async function discoverApiBase() {
    if (_apiClient) return _apiClient.discoverApiBase();
  }

  function login() {
    if (typeof authModule.login === 'function') return authModule.login();
  }

  function logout() {
    if (typeof authModule.logout === 'function') return authModule.logout();
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
    if (typeof coreDom.setAnalysisStatus === 'function') {
      return coreDom.setAnalysisStatus(message, tone);
    }
  }

  function setHeroRunSummary(title, note) {
    if (typeof coreDom.setHeroRunSummary === 'function') {
      return coreDom.setHeroRunSummary(title, note);
    }
  }

  function readRunSelectionFromLocation() {
    return appRuns.readRunSelectionFromLocation
      ? appRuns.readRunSelectionFromLocation()
      : { instanceId: '' };
  }

  function selectedRunPermalink(instanceId) {
    return appRuns.selectedRunPermalink
      ? appRuns.selectedRunPermalink(instanceId, APP_BASE)
      : APP_BASE;
  }

  function updateRunSelectionLocation(instanceId) {
    if (appRuns.updateRunSelectionLocation) {
      appRuns.updateRunSelectionLocation(instanceId, APP_BASE);
    }
  }

  function readStoredUiValue(key) {
    return coreState.readStoredValue ? coreState.readStoredValue(key) : null;
  }

  function storeUiValue(key, value) {
    if (coreState.storeValue) coreState.storeValue(key, value);
  }

  function currentRoleConfig() {
    return WORKSPACE_ROLES[workspaceRole] || WORKSPACE_ROLES.conservation;
  }

  function currentPreferenceConfig() {
    return WORKSPACE_PREFERENCES[workspacePreference] || WORKSPACE_PREFERENCES.investigate;
  }

  function actionLabelForTarget(target) {
    if (typeof summaryUiModule.actionLabelForTarget === 'function') {
      return summaryUiModule.actionLabelForTarget(target);
    }
    var role = currentRoleConfig();
    return target === 'history' ? role.reviewLabel : target === 'content' ? role.deliverableLabel : role.runLabel;
  }

  function revealWorkflowTarget(target) {
    if (typeof summaryUiModule.revealWorkflowTarget === 'function') {
      return summaryUiModule.revealWorkflowTarget(target);
    }
  }

  function renderWorkspaceGuidance() {
    if (typeof summaryUiModule.renderWorkspaceGuidance === 'function') {
      return summaryUiModule.renderWorkspaceGuidance();
    }
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
    if (typeof summaryUiModule.updateHeroSummary === 'function') {
      return summaryUiModule.updateHeroSummary(data);
    }
  }

  function updateHistorySummary(data) {
    if (typeof summaryUiModule.updateHistorySummary === 'function') {
      return summaryUiModule.updateHistorySummary(data);
    }
  }

  function renderPortfolioSummary() {
    if (typeof summaryUiModule.renderPortfolioSummary === 'function') {
      return summaryUiModule.renderPortfolioSummary();
    }
  }

  /* ---- History UI — delegated to app-history-ui.js ---- */

  function normalizeAnalysisRun(run) {
    return appRuns.normalizeRun ? appRuns.normalizeRun(run) : null;
  }

  function sortAnalysisHistoryRuns(runs) {
    return appRuns.sortRuns ? appRuns.sortRuns(runs, parseStatusTimestamp) : [];
  }

  function renderAnalysisHistoryList() {
    if (typeof historyUiModule.renderAnalysisHistoryList === 'function') return historyUiModule.renderAnalysisHistoryList();
  }

  function upsertAnalysisHistoryRun(run) {
    if (!appRuns.upsertRun) return;
    analysisHistoryRuns = appRuns.upsertRun(analysisHistoryRuns, run, parseStatusTimestamp);
    renderAnalysisHistoryList();
    applyFirstRunLayout();
  }

  function selectAnalysisRun(instanceId, options) {
    if (typeof historyUiModule.selectAnalysisRun === 'function') return historyUiModule.selectAnalysisRun(instanceId, options);
  }

  function applyAnalysisHistory(payload, options) {
    if (typeof historyUiModule.applyAnalysisHistory === 'function') return historyUiModule.applyAnalysisHistory(payload, options);
  }

  /* ------------------------------------------------------------------ */
  /*  First-run layout — toggle onboarding vs standard dashboard        */
  /* ------------------------------------------------------------------ */

  function applyFirstRunLayout() {
    if (typeof runLifecycleModule.applyFirstRunLayout === 'function') return runLifecycleModule.applyFirstRunLayout();
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


  /* ---- Run lifecycle — delegated to app-run-lifecycle.js ---- */

  function updateContentSummary(data) {
    if (typeof runLifecycleModule.updateContentSummary === 'function') return runLifecycleModule.updateContentSummary(data);
  }
  function updateRunDetail(data) {
    if (typeof runLifecycleModule.updateRunDetail === 'function') return runLifecycleModule.updateRunDetail(data);
  }
  async function downloadRunExport(format) {
    if (typeof runLifecycleModule.downloadRunExport === 'function') return runLifecycleModule.downloadRunExport(format);
  }
  function updateAnalysisRun(data) {
    if (typeof runLifecycleModule.updateAnalysisRun === 'function') return runLifecycleModule.updateAnalysisRun(data);
  }
  function stopAnalysisPolling() {
    if (typeof runLifecycleModule.stopAnalysisPolling === 'function') return runLifecycleModule.stopAnalysisPolling();
  }
  async function pollAnalysisRun(instanceId) {
    if (typeof runLifecycleModule.pollAnalysisRun === 'function') return runLifecycleModule.pollAnalysisRun(instanceId);
  }
  async function queueAnalysis() {
    if (typeof runLifecycleModule.queueAnalysis === 'function') return runLifecycleModule.queueAnalysis();
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
    if (typeof appRuns.loadHistory === 'function') return appRuns.loadHistory(options);
  }

  /* ---- Auth UI + bootstrap — delegated to app-auth.js ---- */

  function updateAuthUI() {
    if (typeof authModule.updateAuthUI === 'function') return authModule.updateAuthUI();
  }

  function initAuth() {
    if (typeof authModule.initAuth === 'function') return authModule.initAuth();
  }

  function initModule(moduleRef, deps) {
    if (moduleRef && typeof moduleRef.init === 'function') {
      moduleRef.init(deps || {});
    }
  }

  apiDiscoveryReady = discoverApiBase();

  // Initialise billing module before auth so loadBillingStatus works on first sign-in.
  initModule(billingModule, {
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

  initModule(eudrModule, {
    apiFetch: apiFetch,
    getApiReady: function () { return apiDiscoveryReady; },
    getAccount: function () { return currentAccount; },
  });

  initModule(evidencePanelsModule, {
    apiFetch: apiFetch,
    getApiReady: function () { return apiDiscoveryReady; },
    getManifest: function () { return evidenceDisplayModule.getManifest ? evidenceDisplayModule.getManifest() : null; },
    getInstanceId: function () { return evidenceDisplayModule.getInstanceId ? evidenceDisplayModule.getInstanceId() : null; },
  });

  initModule(evidenceDisplayModule, {
    apiFetch: apiFetch,
    getApiReady: function () { return apiDiscoveryReady; },
    getWorkspaceRole: function () { return workspaceRole; },
    getLatestBillingStatus: function () { return latestBillingStatus; },
  });

  initModule(preflightModule, {
    apiFetch: apiFetch,
    getApiReady: function () { return apiDiscoveryReady; },
    getWorkspaceRole: function () { return workspaceRole; },
    getActiveProfile: function () { return activeProfile; },
    getLatestBillingStatus: function () { return latestBillingStatus; },
    getWorkspaceRoleConfig: function () { return currentRoleConfig(); },
    onPreflightUpdate: function (preflight) { analysisDraftSummary = preflight; },
  });

  initModule(appRuns, {
    apiFetch: apiFetch,
    getApiReady: function () { return apiDiscoveryReady; },
    getAccount: function () { return currentAccount; },
    authEnabled: authEnabled,
    getActiveProfile: function () { return activeProfile; },
    readCache: readCache,
    writeCache: writeCache,
    historyCacheTtlMs: CACHE_TTL_HISTORY,
    getAnalysisHistoryLoaded: function () { return analysisHistoryLoaded; },
    setAnalysisHistoryLoaded: function (value) { analysisHistoryLoaded = value; },
    getAnalysisHistoryRuns: function () { return analysisHistoryRuns; },
    setAnalysisHistoryRuns: function (runs) { analysisHistoryRuns = runs; },
    getLatestAnalysisRun: function () { return latestAnalysisRun; },
    setSelectedAnalysisRunId: function (id) { selectedAnalysisRunId = id; },
    applyAnalysisHistory: applyAnalysisHistory,
    applyFirstRunLayout: applyFirstRunLayout,
    renderAnalysisHistoryList: renderAnalysisHistoryList,
    updateHistorySummary: updateHistorySummary,
  });

  initModule(progressModule, {
    setAnalysisStatus: setAnalysisStatus,
    getActiveProfile: function () { return activeProfile; },
    getAnalysisPhases: function () { return ANALYSIS_PHASES; },
    getAnalysisPhaseDetails: function () { return ANALYSIS_PHASE_DETAILS; },
    summarizeRunTiming: summarizeRunTiming,
  });

  initModule(runLifecycleModule, {
      apiFetch: apiFetch,
      getApiReady: function () { return apiDiscoveryReady; },
      getAccount: function () { return currentAccount; },
      login: login,
      getActiveProfile: function () { return activeProfile; },
      getWorkspaceRole: function () { return workspaceRole; },
      getWorkspacePreference: function () { return workspacePreference; },
      getAnalysisDraftSummary: function () { return analysisDraftSummary; },
      setLatestAnalysisRun: function (d) { latestAnalysisRun = d; },
      setAnalysisStatus: setAnalysisStatus,
      setHeroRunSummary: setHeroRunSummary,
      updateHistorySummary: updateHistorySummary,
      getCurrentRoleConfig: currentRoleConfig,
      selectedRunPermalink: selectedRunPermalink,
      getAppBase: function () { return APP_BASE; },
      clearCacheKey: clearCacheKey,
      getAnalysisHistoryLoaded: function () { return analysisHistoryLoaded; },
      getAnalysisHistoryRuns: function () { return analysisHistoryRuns; },
      setAnalysisHistoryLoaded: function (v) { analysisHistoryLoaded = v; },
      upsertAnalysisHistoryRun: upsertAnalysisHistoryRun,
      selectAnalysisRun: selectAnalysisRun,
      loadBillingStatus: loadBillingStatus,
      loadAnalysisHistory: loadAnalysisHistory,
      loadRunEvidence: loadRunEvidence,
      showEvidenceSurface: showEvidenceSurface,
      resetAnalysisProgress: resetAnalysisProgress,
      setAnalysisProgressVisible: setAnalysisProgressVisible,
      setAnalysisStep: setAnalysisStep,
      updateAnalysisStory: updateAnalysisStory,
      mapAnalysisPhase: mapAnalysisPhase,
      updateAnalysisPreflight: updateAnalysisPreflight,
    });

  initModule(historyUiModule, {
      getAnalysisHistoryLoaded: function () { return analysisHistoryLoaded; },
      getAccount: function () { return currentAccount; },
      getSelectedAnalysisRunId: function () { return selectedAnalysisRunId; },
      setSelectedAnalysisRunId: function (id) { selectedAnalysisRunId = id; },
      getAnalysisHistoryRuns: function () { return analysisHistoryRuns; },
      setAnalysisHistoryRuns: function (runs) { analysisHistoryRuns = runs; },
      getLatestAnalysisRun: function () { return latestAnalysisRun; },
      setLatestPortfolioSummary: function (summary) { latestPortfolioSummary = summary; },
      currentRoleConfig: currentRoleConfig,
      displayAnalysisPhase: displayAnalysisPhase,
      formatCountLabel: formatCountLabel,
      formatHistoryTimestamp: formatHistoryTimestamp,
      providerLabel: providerLabel,
      readRunSelectionFromLocation: readRunSelectionFromLocation,
      updateRunSelectionLocation: updateRunSelectionLocation,
      stopAnalysisPolling: stopAnalysisPolling,
      stopPlay: function () { if (typeof evidenceDisplayModule.stopPlay === 'function') evidenceDisplayModule.stopPlay(); },
      updateAnalysisRun: updateAnalysisRun,
      resetAnalysisProgress: resetAnalysisProgress,
      setAnalysisProgressVisible: setAnalysisProgressVisible,
      setAnalysisStep: setAnalysisStep,
      updateAnalysisStory: updateAnalysisStory,
      mapAnalysisPhase: mapAnalysisPhase,
      loadRunEvidence: loadRunEvidence,
      updateHistorySummary: updateHistorySummary,
      pollAnalysisRun: pollAnalysisRun,
      normalizeAnalysisRun: normalizeAnalysisRun,
      sortAnalysisHistoryRuns: sortAnalysisHistoryRuns,
      parseStatusTimestamp: parseStatusTimestamp,
    });

  initModule(summaryUiModule, {
      currentRoleConfig: currentRoleConfig,
      currentPreferenceConfig: currentPreferenceConfig,
      setText: setText,
      getWorkspaceRole: function () { return workspaceRole; },
      getWorkspacePreference: function () { return workspacePreference; },
      getLatestAnalysisRun: function () { return latestAnalysisRun; },
      getAnalysisHistoryLoaded: function () { return analysisHistoryLoaded; },
      getAccount: function () { return currentAccount; },
      getLatestBillingStatus: function () { return latestBillingStatus; },
      getAnalysisHistoryRuns: function () { return analysisHistoryRuns; },
      getSelectedAnalysisRunId: function () { return selectedAnalysisRunId; },
      getLatestPortfolioSummary: function () { return latestPortfolioSummary; },
      setHeroRunSummary: setHeroRunSummary,
      renderAnalysisHistoryList: renderAnalysisHistoryList,
      updateContentSummary: updateContentSummary,
      updateAnalysisPreflight: updateAnalysisPreflight,
      capabilityHeadline: capabilityHeadline,
      formatRetention: formatRetention,
      displayAnalysisPhase: displayAnalysisPhase,
      summarizeRunTiming: summarizeRunTiming,
    });

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
      clearAllCache: clearAllCache,
      postLoginDestinationKey: POST_LOGIN_DESTINATION_KEY,
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
