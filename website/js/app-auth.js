/**
 * app-auth.js
 *
 * SWA built-in auth bootstrap: /.auth/me check, updateAuthUI DOM updates,
 * and HMAC session token acquisition (#534). Extracted from app-shell.js.
 *
 * Exposes window.CanopexAuth = { init, updateAuthUI, initAuth }
 */
(function () {
  'use strict';

  // ── Injected deps ────────────────────────────────────────────
  var _authEnabled = null;
  var _getApiReady = null;
  var _getAccount = null;
  var _setAccount = null;
  var _setClientPrincipal = null;
  var _setSessionToken = null;
  var _apiFetch = null;
  var _getAppBase = null;
  var _loadAnalysisHistory = null;
  var _loadBillingStatus = null;
  var _loadEudrUsage = null;
  var _setHeroRunSummary = null;
  var _updateHistorySummary = null;
  var _renderAnalysisHistoryList = null;
  var _stopAnalysisPolling = null;
  var _resetAnalysisProgress = null;
  var _updateAnalysisRun = null;
  var _getAnalysisHistoryLoaded = null;
  var _getLatestAnalysisRun = null;
  var _clearAnalysisState = null;
  var _clearAllCache = null;
  var _postLoginDestinationKey = null;

  function init(deps) {
    _authEnabled = deps.authEnabled;
    _getApiReady = deps.getApiReady;
    _getAccount = deps.getAccount;
    _setAccount = deps.setAccount;
    _setClientPrincipal = deps.setClientPrincipal;
    _setSessionToken = deps.setSessionToken;
    _apiFetch = deps.apiFetch;
    _getAppBase = deps.getAppBase;
    _loadAnalysisHistory = deps.loadAnalysisHistory;
    _loadBillingStatus = deps.loadBillingStatus;
    _loadEudrUsage = deps.loadEudrUsage;
    _setHeroRunSummary = deps.setHeroRunSummary;
    _updateHistorySummary = deps.updateHistorySummary;
    _renderAnalysisHistoryList = deps.renderAnalysisHistoryList;
    _stopAnalysisPolling = deps.stopAnalysisPolling;
    _resetAnalysisProgress = deps.resetAnalysisProgress;
    _updateAnalysisRun = deps.updateAnalysisRun;
    _getAnalysisHistoryLoaded = deps.getAnalysisHistoryLoaded;
    _getLatestAnalysisRun = deps.getLatestAnalysisRun;
    _clearAnalysisState = deps.clearAnalysisState;
    _clearAllCache = deps.clearAllCache;
    _postLoginDestinationKey = deps.postLoginDestinationKey || 'canopex-post-login';
  }

  function authEnabled() {
    return true;
  }

  function rememberPostLoginDestination() {
    try {
      sessionStorage.setItem(_postLoginDestinationKey, 'app');
    } catch (_) { /* ignore */ }
  }

  function login() {
    rememberPostLoginDestination();
    window.location.href = '/.auth/login/aad';
  }

  function logout() {
    if (_clearAllCache) _clearAllCache();
    try {
      sessionStorage.removeItem(_postLoginDestinationKey);
    } catch (_) { /* ignore */ }
    window.location.href = '/.auth/logout';
  }

  // ── updateAuthUI ─────────────────────────────────────────────

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

    var authOk = typeof _authEnabled === 'function' ? _authEnabled() : true;
    var currentAccount = _getAccount ? _getAccount() : null;
    var apiReady = _getApiReady ? _getApiReady() : Promise.resolve();

    if (!authOk) {
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
      apiReady.then(function () { if (_loadAnalysisHistory) _loadAnalysisHistory(); });
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
      var historyLoaded = _getAnalysisHistoryLoaded ? _getAnalysisHistoryLoaded() : false;
      var latestRun = _getLatestAnalysisRun ? _getLatestAnalysisRun() : null;
      if (!historyLoaded && !latestRun) {
        if (_setHeroRunSummary) _setHeroRunSummary('Checking recent runs', 'Loading your recent runs.');
        if (_updateHistorySummary) _updateHistorySummary(null);
        if (_renderAnalysisHistoryList) _renderAnalysisHistoryList();
      }
      apiReady.then(function () { if (_loadBillingStatus) _loadBillingStatus(); });
      apiReady.then(function () { if (_loadEudrUsage) _loadEudrUsage(); });
      apiReady.then(function () { if (_loadAnalysisHistory) _loadAnalysisHistory(); });
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
      if (_clearAnalysisState) _clearAnalysisState();
      if (_stopAnalysisPolling) _stopAnalysisPolling();
      if (_resetAnalysisProgress) _resetAnalysisProgress();
      if (_renderAnalysisHistoryList) _renderAnalysisHistoryList();
      if (_updateAnalysisRun) _updateAnalysisRun(null);
    }
  }

  // ── initAuth ─────────────────────────────────────────────────

  function initAuth() {
    // Strip legacy ?mode=demo from URL if present
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.get('mode') === 'demo') {
        url.searchParams.delete('mode');
        const nextUrl = url.pathname + (url.search || '') + (url.hash || '');
        const appBase = _getAppBase ? _getAppBase() : '/app/';
        window.history.replaceState({}, '', nextUrl || appBase);
      }
    } catch { /* ignore */ }

    // SWA built-in auth: fetch /.auth/me to check if the user is signed in.
    fetch('/.auth/me').then(function (resp) {
      if (!resp.ok) throw new Error('auth/me failed');
      return resp.json();
    }).then(function (payload) {
      var principal = payload && payload.clientPrincipal;
      if (principal && principal.userId) {
        if (_setClientPrincipal) _setClientPrincipal(principal); // store raw for X-MS-CLIENT-PRINCIPAL forwarding
        if (_setAccount) {
          _setAccount({
            userId: principal.userId,
            name: principal.userDetails || '',
            identityProvider: principal.identityProvider || 'aad',
            userRoles: principal.userRoles || [],
          });
        }
        // Acquire HMAC session token for principal verification (#534).
        // Waits for API base discovery so the request goes to the right host.
        var apiReady = _getApiReady ? _getApiReady() : Promise.resolve();
        (apiReady || Promise.resolve()).then(function () {
          return _apiFetch('/api/auth/session', { method: 'POST' });
        }).then(function (resp) { return resp.json(); }).then(function (data) {
          if (data && data.token && _setSessionToken) _setSessionToken(data.token);
        }).catch(function () { /* session token unavailable — backend may not enforce HMAC */ });
      }
      updateAuthUI();
    }).catch(function (err) {
      console.warn('SWA auth check failed:', err);
      // When running locally without SWA CLI, auth/me won't exist.
      // Fall back to unauthenticated state — updateAuthUI handles it.
      updateAuthUI();
    });
  }

  // ── Public API ────────────────────────────────────────────────

  window.CanopexAuth = {
    authEnabled: authEnabled,
    init: init,
    login: login,
    logout: logout,
    updateAuthUI: updateAuthUI,
    initAuth: initAuth,
  };
})();
