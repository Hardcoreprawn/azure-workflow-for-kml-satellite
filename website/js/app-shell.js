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
  var workspaceModule = window.CanopexWorkspace || {};
  var _apiClient = window.CanopexApiClient ? window.CanopexApiClient.createClient() : null;

  const POST_LOGIN_DESTINATION_KEY = 'canopex-post-login';
  const WORKSPACE_ROLE_STORAGE_KEY = 'canopex-workspace-role';
  const WORKSPACE_PREFERENCE_STORAGE_KEY = 'canopex-workspace-preference';

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
      if (typeof authModule.handleApiError === 'function') {
        authModule.handleApiError(err);
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
    return workspaceModule.currentRoleConfig ? workspaceModule.currentRoleConfig() : {};
  }

  function currentPreferenceConfig() {
    return workspaceModule.currentPreferenceConfig ? workspaceModule.currentPreferenceConfig() : {};
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
    if (workspaceModule.setRole) workspaceModule.setRole(roleKey, options);
  }

  function setWorkspacePreference(preferenceKey, options) {
    if (workspaceModule.setPreference) workspaceModule.setPreference(preferenceKey, options);
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

  /* ---- Parcel notes (#669) — delegated to app-evidence-panels.js ---- */

  /* ---- Human override (#672) — delegated to app-evidence-panels.js ---- */

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
    getWorkspaceRole: function () { return workspaceModule.getRole ? workspaceModule.getRole() : 'conservation'; },
    getLatestBillingStatus: function () { return latestBillingStatus; },
  });

  initModule(preflightModule, {
    apiFetch: apiFetch,
    getApiReady: function () { return apiDiscoveryReady; },
    getWorkspaceRole: function () { return workspaceModule.getRole ? workspaceModule.getRole() : 'conservation'; },
    getActiveProfile: function () { return activeProfile; },
    getLatestBillingStatus: function () { return latestBillingStatus; },
    getWorkspaceRoleConfig: function () { return currentRoleConfig(); },
    onPreflightUpdate: function (preflight) { analysisDraftSummary = preflight; },
  });

  initModule(workspaceModule, {
    readStoredValue: readStoredUiValue,
    storeValue: storeUiValue,
    setCoreState: function (key, value) {
      if (typeof coreState.set === 'function') coreState.set(key, value);
    },
    roleStorageKey: WORKSPACE_ROLE_STORAGE_KEY,
    preferenceStorageKey: WORKSPACE_PREFERENCE_STORAGE_KEY,
    onChange: renderWorkspaceGuidance,
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
      getWorkspaceRole: function () { return workspaceModule.getRole ? workspaceModule.getRole() : 'conservation'; },
      getWorkspacePreference: function () { return workspaceModule.getPreference ? workspaceModule.getPreference() : 'investigate'; },
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
      loadBillingStatus: billingModule.load,
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
      getWorkspaceRole: function () { return workspaceModule.getRole ? workspaceModule.getRole() : 'conservation'; },
      getWorkspacePreference: function () { return workspaceModule.getPreference ? workspaceModule.getPreference() : 'investigate'; },
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
      loadBillingStatus: billingModule.load,
      loadEudrUsage: eudrModule.loadUsage,
      setHeroRunSummary: setHeroRunSummary,
      updateHistorySummary: updateHistorySummary,
      renderAnalysisHistoryList: renderAnalysisHistoryList,
      stopAnalysisPolling: stopAnalysisPolling,
      resetAnalysisProgress: resetAnalysisProgress,
      updateAnalysisRun: updateAnalysisRun,
      getAnalysisHistoryLoaded: function () { return analysisHistoryLoaded; },
      getLatestAnalysisRun: function () { return latestAnalysisRun; },
      clearAllCache: clearAllCache,
      clearClientAuth: function () { if (_apiClient) _apiClient.clearAuth(); },
      postLoginDestinationKey: POST_LOGIN_DESTINATION_KEY,
      setAnalysisStatus: setAnalysisStatus,
      clearAnalysisState: function () {
        analysisHistoryRuns = [];
        analysisHistoryLoaded = false;
        selectedAnalysisRunId = null;
      },
    });
  }

  initAuth();
  if (workspaceModule.bootstrap) {
    workspaceModule.bootstrap(activeProfile, EUDR_LOCKED);
  }
  renderWorkspaceGuidance();

  // All DOM event bindings — delegated to app-bindings.js
  if (typeof bindingsModule.init === 'function') {
    bindingsModule.init({
      // auth
      login: login,
      logout: logout,
      manageBilling: billingModule.manage,
      saveTierEmulation: billingModule.saveEmulation,
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
      toggleEvidencePlay: evidenceDisplayModule.togglePlay,
      showEvidenceFrame: evidenceDisplayModule.showFrame,
      setEvidenceLayerMode: evidenceDisplayModule.setLayerMode,
      requestAiAnalysis: evidenceDisplayModule.requestAi,
      requestEudrAssessment: evidenceDisplayModule.requestEudr,
      expandEvidenceMap: expandEvidenceMap,
      collapseEvidenceMap: collapseEvidenceMap,
      toggleCompareView: evidenceDisplayModule.toggleCompare,
      getOverrideContext: function () {
        return evidenceDisplayModule.getOverrideContext ? evidenceDisplayModule.getOverrideContext() : {};
      },
      // parcel notes / override
      showNoteEditor: evidencePanelsModule.showNoteEditor,
      hideNoteEditor: evidencePanelsModule.hideNoteEditor,
      saveParcelNote: evidencePanelsModule.saveParcelNote,
      openOverrideModal: evidencePanelsModule.openOverrideModal,
      closeOverrideModal: evidencePanelsModule.closeOverrideModal,
      confirmOverride: evidencePanelsModule.confirmOverride,
      revertOverride: evidencePanelsModule.revertOverride,
      onOverrideReasonInput: evidencePanelsModule.onOverrideReasonInput,
      // API access for export
      apiFetch: apiFetch,
    });
  }
})();
