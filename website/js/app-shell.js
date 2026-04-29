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
  var runtimeModule = window.CanopexRuntime || {};
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

  /* ---- History UI — delegated to app-history-ui.js ---- */

  function normalizeAnalysisRun(run) {
    return appRuns.normalizeRun ? appRuns.normalizeRun(run) : null;
  }

  function sortAnalysisHistoryRuns(runs) {
    return appRuns.sortRuns ? appRuns.sortRuns(runs, parseStatusTimestamp) : [];
  }

  /* ------------------------------------------------------------------ */
  /*  First-run layout — toggle onboarding vs standard dashboard        */
  /* ------------------------------------------------------------------ */

  /* ------------------------------------------------------------------ */
  /*  Evidence surface — delegated to app-evidence-display.js           */
  /* ------------------------------------------------------------------ */

  /* ---- Parcel notes (#669) — delegated to app-evidence-panels.js ---- */

  /* ---- Human override (#672) — delegated to app-evidence-panels.js ---- */

  /* ------------------------------------------------------------------ */
  /*  END Evidence surface                                               */
  /* ------------------------------------------------------------------ */


  /* ---- Run lifecycle — delegated to app-run-lifecycle.js ---- */

  /* ---- Auth UI + bootstrap — delegated to app-msal.js ---- */

  function initModule(moduleRef, deps) {
    if (moduleRef && typeof moduleRef.init === 'function') {
      moduleRef.init(deps || {});
    }
  }

  apiDiscoveryReady = discoverApiBase();

  initModule(runtimeModule, {
    cachePrefix: CACHE_PREFIX,
    readScopedCache: coreState.readScopedCache,
    writeScopedCache: coreState.writeScopedCache,
    clearScopedCacheKey: coreState.clearScopedCacheKey,
    clearAllScopedCache: coreState.clearAllScopedCache,
  });

  // Initialise billing module before auth so loadBillingStatus works on first sign-in.
  initModule(billingModule, {
    apiFetch: apiFetch,
    getApiReady: function () { return apiDiscoveryReady; },
    getAccount: runtimeModule.getAccount,
    login: login,
    readCache: runtimeModule.readCache,
    writeCache: runtimeModule.writeCache,
    clearCacheKey: runtimeModule.clearCacheKey,
    onStatusChange: summaryUiModule.updateHeroSummary,
    onLoadError: function () {
      setHeroRunSummary('Ready to queue', 'Billing is unavailable, but analysis can still be launched locally.');
    }
  });

  initModule(eudrModule, {
    apiFetch: apiFetch,
    getApiReady: function () { return apiDiscoveryReady; },
    getAccount: runtimeModule.getAccount,
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
    getLatestBillingStatus: billingModule.getStatus,
  });

  initModule(preflightModule, {
    apiFetch: apiFetch,
    getApiReady: function () { return apiDiscoveryReady; },
    getWorkspaceRole: function () { return workspaceModule.getRole ? workspaceModule.getRole() : 'conservation'; },
    getActiveProfile: function () { return activeProfile; },
    getLatestBillingStatus: billingModule.getStatus,
    getWorkspaceRoleConfig: workspaceModule.currentRoleConfig,
    onPreflightUpdate: runtimeModule.setAnalysisDraftSummary,
  });

  initModule(workspaceModule, {
    readStoredValue: readStoredUiValue,
    storeValue: storeUiValue,
    setCoreState: function (key, value) {
      if (typeof coreState.set === 'function') coreState.set(key, value);
    },
    roleStorageKey: WORKSPACE_ROLE_STORAGE_KEY,
    preferenceStorageKey: WORKSPACE_PREFERENCE_STORAGE_KEY,
    onChange: summaryUiModule.renderWorkspaceGuidance,
  });

  initModule(appRuns, {
    apiFetch: apiFetch,
    getApiReady: function () { return apiDiscoveryReady; },
    getAccount: runtimeModule.getAccount,
    authEnabled: authEnabled,
    getActiveProfile: function () { return activeProfile; },
    readCache: runtimeModule.readCache,
    writeCache: runtimeModule.writeCache,
    historyCacheTtlMs: CACHE_TTL_HISTORY,
    getAnalysisHistoryLoaded: runtimeModule.getAnalysisHistoryLoaded,
    setAnalysisHistoryLoaded: runtimeModule.setAnalysisHistoryLoaded,
    getAnalysisHistoryRuns: runtimeModule.getAnalysisHistoryRuns,
    setAnalysisHistoryRuns: runtimeModule.setAnalysisHistoryRuns,
    getLatestAnalysisRun: runLifecycleModule.getLatestRun,
    setSelectedAnalysisRunId: runtimeModule.setSelectedAnalysisRunId,
    applyAnalysisHistory: historyUiModule.applyAnalysisHistory,
    applyFirstRunLayout: runLifecycleModule.applyFirstRunLayout,
    renderAnalysisHistoryList: historyUiModule.renderAnalysisHistoryList,
    updateHistorySummary: summaryUiModule.updateHistorySummary,
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
      getAccount: runtimeModule.getAccount,
      login: login,
      getActiveProfile: function () { return activeProfile; },
      getWorkspaceRole: function () { return workspaceModule.getRole ? workspaceModule.getRole() : 'conservation'; },
      getWorkspacePreference: function () { return workspaceModule.getPreference ? workspaceModule.getPreference() : 'investigate'; },
      getAnalysisDraftSummary: runtimeModule.getAnalysisDraftSummary,
      setAnalysisStatus: setAnalysisStatus,
      setHeroRunSummary: setHeroRunSummary,
      updateHistorySummary: summaryUiModule.updateHistorySummary,
      getCurrentRoleConfig: workspaceModule.currentRoleConfig,
      selectedRunPermalink: selectedRunPermalink,
      getAppBase: function () { return APP_BASE; },
      clearCacheKey: runtimeModule.clearCacheKey,
      getAnalysisHistoryLoaded: runtimeModule.getAnalysisHistoryLoaded,
      getAnalysisHistoryRuns: runtimeModule.getAnalysisHistoryRuns,
      setAnalysisHistoryRuns: runtimeModule.setAnalysisHistoryRuns,
      setAnalysisHistoryLoaded: runtimeModule.setAnalysisHistoryLoaded,
      selectAnalysisRun: historyUiModule.selectAnalysisRun,
      loadBillingStatus: billingModule.load,
      loadAnalysisHistory: appRuns.loadHistory,
      loadRunEvidence: evidenceDisplayModule.load,
      showEvidenceSurface: evidenceDisplayModule.showSurface,
      renderAnalysisHistoryList: historyUiModule.renderAnalysisHistoryList,
      applyFirstRunLayout: runLifecycleModule.applyFirstRunLayout,
      resetAnalysisProgress: progressModule.reset,
      setAnalysisProgressVisible: progressModule.setVisible,
      setAnalysisStep: progressModule.setStep,
      updateAnalysisStory: progressModule.updateStory,
      mapAnalysisPhase: progressModule.mapPhase,
      updateAnalysisPreflight: preflightModule.updateAnalysisPreflight,
    });

  initModule(historyUiModule, {
      getAnalysisHistoryLoaded: runtimeModule.getAnalysisHistoryLoaded,
      getAccount: runtimeModule.getAccount,
      getSelectedAnalysisRunId: runtimeModule.getSelectedAnalysisRunId,
      setSelectedAnalysisRunId: runtimeModule.setSelectedAnalysisRunId,
      getAnalysisHistoryRuns: runtimeModule.getAnalysisHistoryRuns,
      setAnalysisHistoryRuns: runtimeModule.setAnalysisHistoryRuns,
      getLatestAnalysisRun: runLifecycleModule.getLatestRun,
      setLatestPortfolioSummary: runtimeModule.setLatestPortfolioSummary,
      currentRoleConfig: workspaceModule.currentRoleConfig,
      displayAnalysisPhase: displayAnalysisPhase,
      formatCountLabel: formatCountLabel,
      formatHistoryTimestamp: formatHistoryTimestamp,
      providerLabel: providerLabel,
      readRunSelectionFromLocation: readRunSelectionFromLocation,
      updateRunSelectionLocation: updateRunSelectionLocation,
      stopAnalysisPolling: runLifecycleModule.stopAnalysisPolling,
      stopPlay: evidenceDisplayModule.stopPlay,
      updateAnalysisRun: runLifecycleModule.updateAnalysisRun,
      resetAnalysisProgress: progressModule.reset,
      setAnalysisProgressVisible: progressModule.setVisible,
      setAnalysisStep: progressModule.setStep,
      updateAnalysisStory: progressModule.updateStory,
      mapAnalysisPhase: progressModule.mapPhase,
      loadRunEvidence: evidenceDisplayModule.load,
      updateHistorySummary: summaryUiModule.updateHistorySummary,
      pollAnalysisRun: runLifecycleModule.pollAnalysisRun,
      normalizeAnalysisRun: normalizeAnalysisRun,
      sortAnalysisHistoryRuns: sortAnalysisHistoryRuns,
      parseStatusTimestamp: parseStatusTimestamp,
    });

  initModule(summaryUiModule, {
      currentRoleConfig: workspaceModule.currentRoleConfig,
      currentPreferenceConfig: workspaceModule.currentPreferenceConfig,
      setText: setText,
      getWorkspaceRole: function () { return workspaceModule.getRole ? workspaceModule.getRole() : 'conservation'; },
      getWorkspacePreference: function () { return workspaceModule.getPreference ? workspaceModule.getPreference() : 'investigate'; },
      getLatestAnalysisRun: runLifecycleModule.getLatestRun,
      getAnalysisHistoryLoaded: runtimeModule.getAnalysisHistoryLoaded,
      getAccount: runtimeModule.getAccount,
      getLatestBillingStatus: billingModule.getStatus,
      getAnalysisHistoryRuns: runtimeModule.getAnalysisHistoryRuns,
      getSelectedAnalysisRunId: runtimeModule.getSelectedAnalysisRunId,
      getLatestPortfolioSummary: runtimeModule.getLatestPortfolioSummary,
      setHeroRunSummary: setHeroRunSummary,
      renderAnalysisHistoryList: historyUiModule.renderAnalysisHistoryList,
      updateContentSummary: runLifecycleModule.updateContentSummary,
      updateAnalysisPreflight: preflightModule.updateAnalysisPreflight,
      capabilityHeadline: capabilityHeadline,
      formatRetention: formatRetention,
      displayAnalysisPhase: displayAnalysisPhase,
      summarizeRunTiming: summarizeRunTiming,
    });

  if (typeof authModule.init === 'function') {
    authModule.init({
      authEnabled: authEnabled,
      getApiReady: function () { return apiDiscoveryReady; },
      getAccount: runtimeModule.getAccount,
      setAccount: runtimeModule.setAccount,
      setGetToken: function (fn) { if (_apiClient) _apiClient.setGetToken(fn); },
      apiFetch: apiFetch,
      getAppBase: function () { return APP_BASE; },
      loadAnalysisHistory: appRuns.loadHistory,
      loadBillingStatus: billingModule.load,
      loadEudrUsage: eudrModule.loadUsage,
      setHeroRunSummary: setHeroRunSummary,
      updateHistorySummary: summaryUiModule.updateHistorySummary,
      renderAnalysisHistoryList: historyUiModule.renderAnalysisHistoryList,
      stopAnalysisPolling: runLifecycleModule.stopAnalysisPolling,
      resetAnalysisProgress: progressModule.reset,
      updateAnalysisRun: runLifecycleModule.updateAnalysisRun,
      getAnalysisHistoryLoaded: runtimeModule.getAnalysisHistoryLoaded,
      getLatestAnalysisRun: runLifecycleModule.getLatestRun,
      clearAllCache: runtimeModule.clearAllCache,
      clearClientAuth: function () { if (_apiClient) _apiClient.clearAuth(); },
      postLoginDestinationKey: POST_LOGIN_DESTINATION_KEY,
      setAnalysisStatus: setAnalysisStatus,
      clearAnalysisState: runtimeModule.clearAnalysisState,
    });
  }

  if (typeof authModule.initAuth === 'function') authModule.initAuth();
  if (workspaceModule.bootstrap) {
    workspaceModule.bootstrap(activeProfile, EUDR_LOCKED);
  }
  if (typeof summaryUiModule.renderWorkspaceGuidance === 'function') summaryUiModule.renderWorkspaceGuidance();

  // All DOM event bindings — delegated to app-bindings.js
  if (typeof bindingsModule.init === 'function') {
    bindingsModule.init({
      // auth
      login: login,
      logout: logout,
      manageBilling: billingModule.manage,
      saveTierEmulation: billingModule.saveEmulation,
      // workspace guidance
      setWorkspaceRole: workspaceModule.setRole,
      setWorkspacePreference: workspaceModule.setPreference,
      revealWorkflowTarget: summaryUiModule.revealWorkflowTarget,
      currentPreferenceConfig: workspaceModule.currentPreferenceConfig,
      // analysis
      queueAnalysis: runLifecycleModule.queueAnalysis,
      downloadRunExport: runLifecycleModule.downloadRunExport,
      updateAnalysisPreflight: preflightModule.updateAnalysisPreflight,
      loadAnalysisFile: preflightModule.loadAnalysisFile,
      switchInputTab: preflightModule.switchInputTab,
      convertCSVToKml: preflightModule.convertCSVToKml,
      // evidence surface
      toggleEvidencePlay: evidenceDisplayModule.togglePlay,
      showEvidenceFrame: evidenceDisplayModule.showFrame,
      setEvidenceLayerMode: evidenceDisplayModule.setLayerMode,
      requestAiAnalysis: evidenceDisplayModule.requestAi,
      requestEudrAssessment: evidenceDisplayModule.requestEudr,
      expandEvidenceMap: evidenceDisplayModule.expand,
      collapseEvidenceMap: evidenceDisplayModule.collapse,
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
