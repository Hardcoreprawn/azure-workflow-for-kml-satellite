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
  var _msalInitPromise = null;

  // CIAM config — injected at deploy time into a JSON script element
  // (id="canopex-ciam-config", type="application/json") by the CI pipeline.
  // Falls back to nothing; authEnabled() returns false and the UI stays
  // in local-dev mode.
  function getCiamConfig() {
    try {
      var el = document.getElementById('canopex-ciam-config');
      if (!el) return { clientId: '', authority: '', tenantId: '', apiAudience: '' };
      var parsed = JSON.parse(el.textContent || '{}');
      return {
        clientId: parsed.clientId || '',
        authority: parsed.authority || '',
        tenantId: parsed.tenantId || '',
        apiAudience: parsed.apiAudience || '',
      };
    } catch (_) {
      return { clientId: '', authority: '', tenantId: '', apiAudience: '' };
    }
  }

  function buildApiScopes(ciam) {
    var audience = String((ciam && ciam.apiAudience) || '').trim();
    if (!audience) {
      return ['openid', 'profile'];
    }
    return ['openid', 'profile', audience + '/User.Read'];
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

  function applyCachedAccount(app) {
    var accounts = app.getAllAccounts();
    if (accounts && accounts.length > 0) {
      var account = accounts[0];
      if (_setAccount) {
        _setAccount({
          userId: account.localAccountId || account.homeAccountId || '',
          name: account.name || account.username || '',
          identityProvider: 'ciam',
          userRoles: [],
        });
      }
      return account;
    }
    return null;
  }

  function ensureMsalReady() {
    if (!authEnabled()) {
      return Promise.resolve(null);
    }

    var app = getMsalApp();
    if (!app) {
      return Promise.resolve(null);
    }

    if (!_msalInitPromise) {
      _msalInitPromise = app.initialize().then(function () {
        return app.handleRedirectPromise().catch(function (redirectErr) {
          console.warn('[CanopexAuth] handleRedirectPromise error:', redirectErr);
          return null;
        });
      }).then(function () {
        applyCachedAccount(app);
        return app;
      }).catch(function (initErr) {
        _msalInitPromise = null;
        throw initErr;
      });
    }

    return _msalInitPromise;
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

  // Token age telemetry (#757): timestamp of the last successful token acquisition.
  var _lastTokenAcquiredAt = null;

  function buildRedirectError(message, cause) {
    var err = new Error(message);
    err.name = 'CanopexAuthRedirectError';
    err.authRedirectTriggered = true;
    if (cause) {
      err.cause = cause;
    }
    return err;
  }

  /**
   * Return a valid CIAM token string, acquiring silently if possible.
   * Falls back to a redirect login if no cached token is available.
   * Logs token age to console for debugging (#757).
   * Throws if MSAL is not configured (authEnabled() === false).
   */
  async function getToken() {
    var app = await ensureMsalReady();
    if (!app) {
      throw new Error('[CanopexAuth] MSAL not configured — cannot get token');
    }

    var accounts = app.getAllAccounts();
    if (!accounts || accounts.length === 0) {
      // No cached account — trigger login.
      login();
      // Stop API callers from sending unauthenticated requests while redirecting.
      throw buildRedirectError('[CanopexAuth] Redirecting to login (no cached account)');
    }

    var account = accounts[0];
    var ciam = getCiamConfig();
    var request = {
      scopes: buildApiScopes(ciam),
      account: account,
    };

    try {
      var result = await app.acquireTokenSilent(request);
      _lastTokenAcquiredAt = new Date().toISOString();
      console.debug('[CanopexAuth] tokenAge: acquired at', _lastTokenAcquiredAt);
      if (ciam.apiAudience) {
        // API audience is registered — backend requires a CIAM access token.
        // Never use the ID token as a bearer credential.
        return result.accessToken || '';
      }
      // Local dev without a registered API scope: fall back to id token.
      return result.idToken || result.accessToken || '';
    } catch (silentErr) {
      // Silent acquisition failed (token expired, consent required, etc.).
      // Trigger a redirect so the user can re-authenticate.
      var errorCode = String((silentErr && silentErr.errorCode) || '');
      if (errorCode !== 'interaction_in_progress') {
        console.warn('[CanopexAuth] Silent token acquisition failed, redirecting:', silentErr);
        app.acquireTokenRedirect(request).catch(function (redirectErr) {
          console.error('[CanopexAuth] Redirect login failed:', redirectErr);
        });
      }
      // Stop API callers from sending unauthenticated requests while redirecting.
      throw buildRedirectError('[CanopexAuth] Redirecting to refresh session', silentErr);
    }
  }

  // ── login / logout ────────────────────────────────────────────

  function rememberPostLoginDestination() {
    try {
      sessionStorage.setItem(_postLoginDestinationKey || 'canopex-post-login', 'app');
    } catch (_) { /* ignore */ }
  }

  function login() {
    ensureMsalReady().then(function (app) {
      if (!app) {
        return;
      }
      rememberPostLoginDestination();
      return app.loginRedirect({ scopes: buildApiScopes(getCiamConfig()) });
    }).catch(function (err) {
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

    ensureMsalReady().then(function (app) {
      if (!app) {
        return;
      }
      var accounts = app.getAllAccounts();
      var account = accounts && accounts[0];
      return app.logoutRedirect({
        account: account || null,
        postLogoutRedirectUri: window.location.origin + '/',
      });
    }).catch(function (err) {
      console.error('[CanopexAuth] logoutRedirect failed:', err);
    }).catch(function (err) {
    });
  }

  // ── handleApiError ────────────────────────────────────────────

  /**
   * Handle a 401 from the backend (#757).
   *
   * Instead of logging the user out (which interrupts a demo), show a
   * non-blocking status toast and attempt a silent token re-acquisition.
   * Falls back to acquireTokenPopup so the user can re-auth in place.
   * Only logs out as a last resort when popup is blocked or fails.
   */
  function handleApiError(err) {
    if (!err || err.status !== 401 || !authEnabled()) {
      return;
    }

    console.warn('[CanopexAuth] 401 received — attempting transparent re-auth');
    if (_setAnalysisStatus) {
      _setAnalysisStatus('Session refreshing — signing you back in…', 'info');
    }

    ensureMsalReady().then(function (app) {
      if (!app) {
        return;
      }
      var accounts = app.getAllAccounts();
      var account = accounts && accounts[0];
      if (!account) {
        login();
        return;
      }
      var ciam = getCiamConfig();
      var request = { scopes: buildApiScopes(ciam), account: account };
      // Try popup first so the page doesn't navigate away mid-demo.
      return app.acquireTokenPopup(request).then(function (result) {
        _lastTokenAcquiredAt = new Date().toISOString();
        console.debug('[CanopexAuth] Re-auth via popup succeeded at', _lastTokenAcquiredAt);
        if (_setAnalysisStatus) {
          _setAnalysisStatus('', '');
        }
      });
    }).catch(function (popupErr) {
      // Popup blocked or failed — fall back to full redirect.
      console.warn('[CanopexAuth] Popup re-auth failed, falling back to redirect:', popupErr);
      if (_stopAnalysisPolling) {
        _stopAnalysisPolling();
      }
      login();
    });
  }

  // ── updateAuthUI ──────────────────────────────────────────────

  function renderLocalDevUI(elements) {
    var apiReady = _getApiReady ? _getApiReady() : Promise.resolve();
    if (elements.statusBadge) elements.statusBadge.style.display = 'inline';
    if (elements.loginBtn) elements.loginBtn.style.display = 'none';
    if (elements.logoutBtn) elements.logoutBtn.style.display = 'none';
    if (elements.userSpan) {
      elements.userSpan.textContent = 'Local dev';
      elements.userSpan.style.display = 'inline';
    }
    if (elements.gate) elements.gate.hidden = true;
    if (elements.dashboard) elements.dashboard.hidden = false;
    if (elements.localAuthGate) elements.localAuthGate.hidden = true;
    if (elements.localFormFields) elements.localFormFields.hidden = false;
    if (elements.userName) elements.userName.textContent = 'Local developer';
    if (elements.accountIdentifier) elements.accountIdentifier.textContent = 'Authentication disabled';
    if (elements.accountNote) elements.accountNote.textContent = 'Auth is disabled in this environment.';
    if (elements.billingBtn) elements.billingBtn.style.display = 'none';
    if (elements.tierEl) elements.tierEl.textContent = 'Local';
    if (elements.statusEl) elements.statusEl.textContent = 'disabled';
    if (elements.remainingEl) elements.remainingEl.textContent = 'n/a';
    if (elements.concEl) elements.concEl.textContent = 'n/a';
    if (elements.aiEl) elements.aiEl.textContent = 'n/a';
    if (elements.apiEl) elements.apiEl.textContent = 'n/a';
    if (elements.retEl) elements.retEl.textContent = 'n/a';
    if (elements.billingNoteEl) {
      elements.billingNoteEl.textContent = 'Billing is unavailable when auth is disabled';
    }
    if (elements.emulationCard) elements.emulationCard.hidden = true;
    apiReady.then(function () { if (_loadAnalysisHistory) _loadAnalysisHistory(); });
  }

  function renderSignedInUI(elements, currentAccount) {
    var apiReady = _getApiReady ? _getApiReady() : Promise.resolve();
    var displayName = currentAccount.name || currentAccount.userId || 'User';
    var identifier = currentAccount.userId || currentAccount.name || 'Signed in';
    var historyLoaded = _getAnalysisHistoryLoaded ? _getAnalysisHistoryLoaded() : false;
    var latestRun = _getLatestAnalysisRun ? _getLatestAnalysisRun() : null;

    if (elements.statusBadge) elements.statusBadge.style.display = 'inline';
    if (elements.userSpan) {
      elements.userSpan.textContent = displayName;
      elements.userSpan.style.display = 'inline';
    }
    if (elements.loginBtn) elements.loginBtn.style.display = 'none';
    if (elements.logoutBtn) elements.logoutBtn.style.display = 'inline';
    if (elements.gate) elements.gate.hidden = true;
    if (elements.dashboard) elements.dashboard.hidden = false;
    if (elements.userName) elements.userName.textContent = displayName;
    if (elements.accountIdentifier) elements.accountIdentifier.textContent = identifier;
    if (elements.accountNote) {
      elements.accountNote.textContent = 'This is your Canopex dashboard. Choose the analysis type and work preference that match the job at hand.';
    }
    if (elements.analysisAuthGate) elements.analysisAuthGate.hidden = true;
    if (elements.analysisFormFields) elements.analysisFormFields.hidden = false;
    if (elements.historyCard) elements.historyCard.hidden = false;

    if (!historyLoaded && !latestRun) {
      if (_setHeroRunSummary) _setHeroRunSummary('Checking recent runs', 'Loading your recent runs.');
      if (_updateHistorySummary) _updateHistorySummary(null);
      if (_renderAnalysisHistoryList) _renderAnalysisHistoryList();
    }

    apiReady.then(function () { if (_loadBillingStatus) _loadBillingStatus(); });
    apiReady.then(function () { if (_loadEudrUsage) _loadEudrUsage(); });
    apiReady.then(function () { if (_loadAnalysisHistory) _loadAnalysisHistory(); });
  }

  function renderSignedOutUI(elements) {
    if (elements.statusBadge) elements.statusBadge.style.display = 'none';
    if (elements.userSpan) elements.userSpan.style.display = 'none';
    if (elements.loginBtn) elements.loginBtn.style.display = 'inline';
    if (elements.logoutBtn) elements.logoutBtn.style.display = 'none';
    if (elements.gate) elements.gate.hidden = false;
    if (elements.dashboard) elements.dashboard.hidden = true;
    if (elements.billingBtn) elements.billingBtn.style.display = 'none';
    if (elements.unauthGate) elements.unauthGate.hidden = false;
    if (elements.unauthFormFields) elements.unauthFormFields.hidden = true;
    if (_clearAnalysisState) _clearAnalysisState();
    if (_stopAnalysisPolling) _stopAnalysisPolling();
    if (_resetAnalysisProgress) _resetAnalysisProgress();
    if (_renderAnalysisHistoryList) _renderAnalysisHistoryList();
    if (_updateAnalysisRun) _updateAnalysisRun(null);
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
    var elements = {
      statusBadge: document.getElementById('status-badge'),
      loginBtn: loginBtn,
      logoutBtn: logoutBtn,
      userSpan: userSpan,
      gate: gate,
      dashboard: dashboard,
      userName: userName,
      accountIdentifier: accountIdentifier,
      accountNote: accountNote,
      billingBtn: billingBtn,
      localAuthGate: document.getElementById('app-analysis-auth-gate'),
      localFormFields: document.getElementById('app-analysis-form-fields'),
      tierEl: document.getElementById('app-tier'),
      statusEl: document.getElementById('app-subscription-status'),
      remainingEl: document.getElementById('app-runs-remaining'),
      concEl: document.getElementById('app-concurrency'),
      aiEl: document.getElementById('app-ai-access'),
      apiEl: document.getElementById('app-api-access'),
      retEl: document.getElementById('app-retention'),
      billingNoteEl: document.getElementById('app-billing-note'),
      emulationCard: document.getElementById('app-tier-emulation-card'),
      analysisAuthGate: document.getElementById('app-analysis-auth-gate'),
      analysisFormFields: document.getElementById('app-analysis-form-fields'),
      historyCard: document.getElementById('app-history-card'),
      unauthGate: document.getElementById('app-analysis-auth-gate'),
      unauthFormFields: document.getElementById('app-analysis-form-fields'),
    };

    if (!authEnabled()) {
      renderLocalDevUI(elements);
      return;
    }

    var currentAccount = _getAccount ? _getAccount() : null;

    if (currentAccount) {
      renderSignedInUI(elements, currentAccount);
    } else {
      renderSignedOutUI(elements);
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

    try {
      await ensureMsalReady();
    } catch (initErr) {
      console.warn('[CanopexAuth] MSAL initialize failed:', initErr);
      updateAuthUI();
      return;
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
