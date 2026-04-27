/**
 * app-msal.js
 *
 * MSAL.js browser wrapper for Entra External ID (CIAM) authentication.
 * Replaces the legacy SWA /.auth/* + X-MS-CLIENT-PRINCIPAL forwarding flow.
 *
 * Requires MSAL.js browser bundle loaded before this file (window.msal).
 * CIAM config is injected via window.CanopexConfig (from api-config.json
 * or a <script> block — see index.html and deploy pipeline).
 *
 * Exposes: window.CanopexAuth (same contract as the legacy app-auth.js so
 * app-shell.js wiring is unchanged).
 *
 * Contract:
 *   init(deps)     — call once at boot; registers deps from app-shell.js
 *   initAuth()     — handle redirect response + check for cached account
 *   login()        — start MSAL redirect login
 *   logout()       — clear MSAL session + local state
 *   getToken()     — return a valid CIAM access/id token string (async)
 *   updateAuthUI() — sync DOM to current account state
 *   authEnabled()  — return true when CIAM config is present
 *   handleApiError(err) — clear auth state on 401
 */
(function () {
  'use strict';

  // ── Injected deps (wired by app-shell.js) ────────────────────
  var _getApiReady = null;
  var _getAccount = null;
  var _setAccount = null;
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
  var _clearClientAuth = null;
  var _setAnalysisStatus = null;
  var _setGetToken = null; // wire getToken into the API client

  // ── MSAL state ───────────────────────────────────────────────
  var _msalApp = null;

  // CIAM config — injected at deploy time into a JSON script element
  // (id="canopex-ciam-config", type="application/json") by the CI pipeline.
  // Falls back to nothing; authEnabled() returns false and the UI stays
  // in local-dev mode.
  function getCiamConfig() {
    try {
      var el = document.getElementById('canopex-ciam-config');
      if (!el) return { clientId: '', authority: '', tenantId: '' };
      var parsed = JSON.parse(el.textContent || '{}');
      return {
        clientId: parsed.clientId || '',
        authority: parsed.authority || '',
        tenantId: parsed.tenantId || '',
      };
    } catch (_) {
      return { clientId: '', authority: '', tenantId: '' };
    }
  }

  function authEnabled() {
    var cfg = getCiamConfig();
    return !!(cfg.clientId && cfg.authority);
  }

  // Build MSAL config from the injected CIAM config.
  function buildMsalConfig(ciam) {
    return {
      auth: {
        clientId: ciam.clientId,
        // ciamlogin.com authority — correct for Entra External ID.
        authority: ciam.authority,
        // Redirect back to the app page, not the root.
        redirectUri: window.location.origin + '/app/',
        postLogoutRedirectUri: window.location.origin + '/',
        // CIAM tenants require this to be set explicitly.
        knownAuthorities: [ciam.authority.replace(/https?:\/\//, '').split('/')[0]],
      },
      cache: {
        cacheLocation: 'localStorage',
        storeAuthStateInCookie: false,
      },
    };
  }

  function getMsalApp() {
    if (_msalApp) {
      return _msalApp;
    }
    if (!window.msal) {
      console.warn('[CanopexAuth] MSAL.js not loaded');
      return null;
    }
    var ciam = getCiamConfig();
    if (!ciam.clientId || !ciam.authority) {
      return null;
    }
    try {
      _msalApp = new window.msal.PublicClientApplication(buildMsalConfig(ciam));
      return _msalApp;
    } catch (err) {
      console.warn('[CanopexAuth] MSAL init failed:', err);
      return null;
    }
  }

  // ── Dep injection ─────────────────────────────────────────────

  function init(deps) {
    _getApiReady = deps.getApiReady;
    _getAccount = deps.getAccount;
    _setAccount = deps.setAccount;
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
    _clearClientAuth = deps.clearClientAuth;
    _setAnalysisStatus = deps.setAnalysisStatus;
    // New dep: wire getToken into the API client so apiFetch can call it.
    _setGetToken = deps.setGetToken;
    if (_setGetToken) {
      _setGetToken(getToken);
    }
  }

  // ── getToken ──────────────────────────────────────────────────

  /**
   * Return a valid CIAM token string, acquiring silently if possible.
   * Falls back to a redirect login if no cached token is available.
   * Throws if MSAL is not configured (authEnabled() === false).
   */
  async function getToken() {
    var app = getMsalApp();
    if (!app) {
      throw new Error('[CanopexAuth] MSAL not configured — cannot get token');
    }

    var accounts = app.getAllAccounts();
    if (!accounts || accounts.length === 0) {
      // No cached account — trigger login.
      login();
      // Return empty; the redirect will restart the page.
      return '';
    }

    var account = accounts[0];
    var request = {
      scopes: ['openid', 'profile'],
      account: account,
    };

    try {
      var result = await app.acquireTokenSilent(request);
      // Prefer the id token for CIAM — the backend validates it against the
      // CIAM JWKS. The access token may have a Graph audience which the
      // backend rejects.
      return result.idToken || result.accessToken || '';
    } catch (silentErr) {
      // Silent acquisition failed (token expired, consent required, etc.).
      // Trigger a redirect so the user can re-authenticate.
      console.warn('[CanopexAuth] Silent token acquisition failed, redirecting:', silentErr);
      app.acquireTokenRedirect(request).catch(function (redirectErr) {
        console.error('[CanopexAuth] Redirect login failed:', redirectErr);
      });
      return '';
    }
  }

  // ── login / logout ────────────────────────────────────────────

  function rememberPostLoginDestination() {
    try {
      sessionStorage.setItem(_postLoginDestinationKey || 'canopex-post-login', 'app');
    } catch (_) { /* ignore */ }
  }

  function login() {
    var app = getMsalApp();
    if (!app) {
      // No CIAM config — nothing to do in dev mode.
      return;
    }
    rememberPostLoginDestination();
    app.loginRedirect({ scopes: ['openid', 'profile'] }).catch(function (err) {
      console.error('[CanopexAuth] loginRedirect failed:', err);
    });
  }

  function logout() {
    if (_clearAllCache) {
      _clearAllCache();
    }
    try {
      sessionStorage.removeItem(_postLoginDestinationKey || 'canopex-post-login');
    } catch (_) { /* ignore */ }

    var app = getMsalApp();
    if (!app) {
      return;
    }
    var accounts = app.getAllAccounts();
    var account = accounts && accounts[0];
    app.logoutRedirect({
      account: account || null,
      postLogoutRedirectUri: window.location.origin + '/',
    }).catch(function (err) {
      console.error('[CanopexAuth] logoutRedirect failed:', err);
    });
  }

  // ── handleApiError ────────────────────────────────────────────

  function handleApiError(err) {
    if (!err || err.status !== 401 || !authEnabled()) {
      return;
    }
    if (_setAccount) {
      _setAccount(null);
    }
    if (_clearClientAuth) {
      _clearClientAuth();
    }
    updateAuthUI();
    if (_setAnalysisStatus) {
      _setAnalysisStatus('Your session has expired. Please sign in again.', 'error');
    }
    if (_stopAnalysisPolling) {
      _stopAnalysisPolling();
    }
  }

  // ── updateAuthUI ──────────────────────────────────────────────

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
      // Local dev — show dev UI, bypass auth gate.
      if (loginBtn) loginBtn.style.display = 'none';
      if (logoutBtn) logoutBtn.style.display = 'none';
      if (userSpan) { userSpan.textContent = 'Local dev'; userSpan.style.display = 'inline'; }
      if (gate) gate.hidden = true;
      if (dashboard) dashboard.hidden = false;
      var localAuthGate = document.getElementById('app-analysis-auth-gate');
      var localFormFields = document.getElementById('app-analysis-form-fields');
      if (localAuthGate) localAuthGate.hidden = true;
      if (localFormFields) localFormFields.hidden = false;
      if (userName) userName.textContent = 'Local developer';
      if (accountIdentifier) accountIdentifier.textContent = 'Authentication disabled';
      if (accountNote) accountNote.textContent = 'Auth is disabled in this environment.';
      if (billingBtn) billingBtn.style.display = 'none';
      var tierEl = document.getElementById('app-tier');
      var statusEl = document.getElementById('app-subscription-status');
      var remainingEl = document.getElementById('app-runs-remaining');
      var concEl = document.getElementById('app-concurrency');
      var aiEl = document.getElementById('app-ai-access');
      var apiEl = document.getElementById('app-api-access');
      var retEl = document.getElementById('app-retention');
      var billingNoteEl = document.getElementById('app-billing-note');
      var emulationCard = document.getElementById('app-tier-emulation-card');
      if (tierEl) tierEl.textContent = 'Local';
      if (statusEl) statusEl.textContent = 'disabled';
      if (remainingEl) remainingEl.textContent = 'n/a';
      if (concEl) concEl.textContent = 'n/a';
      if (aiEl) aiEl.textContent = 'n/a';
      if (apiEl) apiEl.textContent = 'n/a';
      if (retEl) retEl.textContent = 'n/a';
      if (billingNoteEl) billingNoteEl.textContent = 'Billing is unavailable when auth is disabled';
      if (emulationCard) emulationCard.hidden = true;
      var apiReady = _getApiReady ? _getApiReady() : Promise.resolve();
      apiReady.then(function () { if (_loadAnalysisHistory) _loadAnalysisHistory(); });
      return;
    }

    var currentAccount = _getAccount ? _getAccount() : null;
    var apiReady = _getApiReady ? _getApiReady() : Promise.resolve();

    if (currentAccount) {
      var displayName = currentAccount.name || currentAccount.userId || 'User';
      var identifier = currentAccount.userId || currentAccount.name || 'Signed in';
      if (userSpan) { userSpan.textContent = displayName; userSpan.style.display = 'inline'; }
      if (loginBtn) loginBtn.style.display = 'none';
      if (logoutBtn) logoutBtn.style.display = 'inline';
      if (gate) gate.hidden = true;
      if (dashboard) dashboard.hidden = false;
      if (userName) userName.textContent = displayName;
      if (accountIdentifier) accountIdentifier.textContent = identifier;
      if (accountNote) accountNote.textContent = 'This is your Canopex dashboard. Choose the analysis type and work preference that match the job at hand.';
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
      if (userSpan) userSpan.style.display = 'none';
      if (loginBtn) loginBtn.style.display = 'inline';
      if (logoutBtn) logoutBtn.style.display = 'none';
      if (gate) gate.hidden = false;
      if (dashboard) dashboard.hidden = true;
      if (billingBtn) billingBtn.style.display = 'none';
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

  // ── initAuth ──────────────────────────────────────────────────

  /**
   * Called once at page boot.
   * Handles the MSAL redirect response (if we just came back from login),
   * then checks for a cached account and sets the auth state.
   */
  async function initAuth() {
    // Strip legacy ?mode=demo from URL if present.
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.get('mode') === 'demo') {
        url.searchParams.delete('mode');
        const nextUrl = url.pathname + (url.search || '') + (url.hash || '');
        const appBase = _getAppBase ? _getAppBase() : '/app/';
        window.history.replaceState({}, '', nextUrl || appBase);
      }
    } catch (_) { /* ignore */ }

    if (!authEnabled()) {
      // CIAM not configured (local dev) — show dev mode immediately.
      updateAuthUI();
      return;
    }

    var app = getMsalApp();
    if (!app) {
      updateAuthUI();
      return;
    }

    // Initialize MSAL — this must be called before any other MSAL API.
    // It also handles the redirect response if we just returned from login.
    try {
      await app.initialize();
    } catch (initErr) {
      console.warn('[CanopexAuth] MSAL initialize failed:', initErr);
      updateAuthUI();
      return;
    }

    // Handle the redirect response (sets account in MSAL cache).
    try {
      await app.handleRedirectPromise();
    } catch (redirectErr) {
      // User cancelled or redirect errored — not fatal, just log.
      console.warn('[CanopexAuth] handleRedirectPromise error:', redirectErr);
    }

    // Check for a cached account after redirect handling.
    var accounts = app.getAllAccounts();
    if (accounts && accounts.length > 0) {
      var account = accounts[0];
      if (_setAccount) {
        _setAccount({
          // Use MSAL's stable local account id as userId for consistency.
          userId: account.localAccountId || account.homeAccountId || '',
          name: account.name || account.username || '',
          identityProvider: 'ciam',
          userRoles: [],
        });
      }
    }

    updateAuthUI();
  }

  // ── Public API ────────────────────────────────────────────────

  window.CanopexAuth = {
    authEnabled: authEnabled,
    handleApiError: handleApiError,
    init: init,
    login: login,
    logout: logout,
    getToken: getToken,
    updateAuthUI: updateAuthUI,
    initAuth: initAuth,
  };
})();
