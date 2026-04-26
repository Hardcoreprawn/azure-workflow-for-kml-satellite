(function () {
  'use strict';

  let deps = {};
  const state = {
    account: null,
    latestPortfolioSummary: null,
    analysisHistoryRuns: [],
    analysisHistoryLoaded: false,
    selectedAnalysisRunId: null,
    analysisDraftSummary: null,
  };

  function init(nextDeps) {
    deps = nextDeps || {};
  }

  function getAccount() {
    return state.account;
  }

  function setAccount(account) {
    state.account = account || null;
    return state.account;
  }

  function getLatestPortfolioSummary() {
    return state.latestPortfolioSummary;
  }

  function setLatestPortfolioSummary(summary) {
    state.latestPortfolioSummary = summary || null;
    return state.latestPortfolioSummary;
  }

  function getAnalysisHistoryRuns() {
    return state.analysisHistoryRuns;
  }

  function setAnalysisHistoryRuns(runs) {
    state.analysisHistoryRuns = Array.isArray(runs) ? runs : [];
    return state.analysisHistoryRuns;
  }

  function getAnalysisHistoryLoaded() {
    return state.analysisHistoryLoaded;
  }

  function setAnalysisHistoryLoaded(value) {
    state.analysisHistoryLoaded = !!value;
    return state.analysisHistoryLoaded;
  }

  function getSelectedAnalysisRunId() {
    return state.selectedAnalysisRunId;
  }

  function setSelectedAnalysisRunId(instanceId) {
    state.selectedAnalysisRunId = instanceId || null;
    return state.selectedAnalysisRunId;
  }

  function getAnalysisDraftSummary() {
    return state.analysisDraftSummary;
  }

  function setAnalysisDraftSummary(summary) {
    state.analysisDraftSummary = summary || null;
    return state.analysisDraftSummary;
  }

  function readCache(key) {
    if (!deps.readScopedCache) return null;
    return deps.readScopedCache(deps.cachePrefix, state.account && state.account.userId, key);
  }

  function writeCache(key, data, ttlMs) {
    if (!deps.writeScopedCache) return false;
    return deps.writeScopedCache(deps.cachePrefix, state.account && state.account.userId, key, data, ttlMs);
  }

  function clearCacheKey(key) {
    if (!deps.clearScopedCacheKey) return false;
    return deps.clearScopedCacheKey(deps.cachePrefix, state.account && state.account.userId, key);
  }

  function clearAllCache() {
    if (!deps.clearAllScopedCache) return false;
    return deps.clearAllScopedCache(deps.cachePrefix);
  }

  function clearAnalysisState() {
    state.analysisHistoryRuns = [];
    state.analysisHistoryLoaded = false;
    state.selectedAnalysisRunId = null;
    state.latestPortfolioSummary = null;
  }

  window.CanopexRuntime = {
    init: init,
    getAccount: getAccount,
    setAccount: setAccount,
    getLatestPortfolioSummary: getLatestPortfolioSummary,
    setLatestPortfolioSummary: setLatestPortfolioSummary,
    getAnalysisHistoryRuns: getAnalysisHistoryRuns,
    setAnalysisHistoryRuns: setAnalysisHistoryRuns,
    getAnalysisHistoryLoaded: getAnalysisHistoryLoaded,
    setAnalysisHistoryLoaded: setAnalysisHistoryLoaded,
    getSelectedAnalysisRunId: getSelectedAnalysisRunId,
    setSelectedAnalysisRunId: setSelectedAnalysisRunId,
    getAnalysisDraftSummary: getAnalysisDraftSummary,
    setAnalysisDraftSummary: setAnalysisDraftSummary,
    readCache: readCache,
    writeCache: writeCache,
    clearCacheKey: clearCacheKey,
    clearAllCache: clearAllCache,
    clearAnalysisState: clearAnalysisState,
  };
})();
