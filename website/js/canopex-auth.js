/**
 * canopex-auth.js
 *
 * Single source of truth for CIAM (Entra External ID) browser auth via MSAL.js.
 *
 * This module replaces the parallel MSAL setups that previously lived in
 * landing.js (marketing page) and app-msal.js (app shell). Both consumers
 * now go through `window.CanopexCiam` so:
 *   - There is exactly one PublicClientApplication per page.
  *   - `redirectUri` is always the origin root ('/'). MSAL's
  *     navigateToLoginRequestUrl (default: true) saves the originating page
  *     and navigates back to it after auth completes. Only the root URI needs
  *     to be registered in CIAM — no per-page URI registration required.
 *   - Scope construction, token preference, error semantics and the
 *     `authRedirectTriggered` marker are defined once.
 *
 * Requires `window.msal` (MSAL.js browser bundle) loaded before this file.
 *
 * Public API (window.CanopexCiam):
 *   getCiamConfig()            — read injected `<script id="canopex-ciam-config">`
 *   authEnabled()              — true when MSAL + CIAM config are present
 *   ensureMsalReady()          — Promise<PublicClientApplication|null>
 *   getAccount()               — cached MSAL AccountInfo or null
 *   getCurrentUser()           — normalised {userId,name,identityProvider} or null
 *   login()                    — start loginRedirect
 *   logout(opts)               — start logoutRedirect (opts.onBeforeLogout cb)
 *   getToken()                 — Promise<string> CIAM access token (throws
 *                                CanopexAuthRedirectError if redirect started)
 *   onAccountChange(cb)        — subscribe to account-state changes
 *   buildRedirectError(msg, cause)
 */
(function () {
  'use strict';

  var _msalApp = null;
  var _msalInitPromise = null;
  var _cachedAccount = null;
  var _lastTokenAcquiredAt = null;
  var _accountChangeListeners = [];

  function getCiamConfig() {
    try {
      var el = document.getElementById('canopex-ciam-config');
      if (!el) {
        return { clientId: '', authority: '', tenantId: '', apiAudience: '' };
      }
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

  function authEnabled() {
    var cfg = getCiamConfig();
    return !!(window.msal && cfg.clientId && cfg.authority);
  }

  // API scope construction. When apiAudience is configured we request
  // `<audience>/User.Read` so CIAM mints an access token for our API
  // (audience match is verified server-side). When apiAudience is empty
  // we only request OIDC scopes — the resulting calls will be unauthenticated
  // and getToken() will surface a visible misconfiguration error.
  function buildApiScopes(ciam) {
    var audience = String((ciam && ciam.apiAudience) || '').trim();
    if (!audience) {
      return ['openid', 'profile'];
    }
    return ['openid', 'profile', audience + '/User.Read'];
  }

  function buildRedirectError(message, cause) {
    var err = new Error(message);
    err.name = 'CanopexAuthRedirectError';
    err.authRedirectTriggered = true;
    if (cause) {
      err.cause = cause;
    }
    return err;
  }

  // Page-derived redirect URI. The page that started the login completes
  // the redirect handshake — this avoids cross-page MSAL state desync and
  // makes adding a new entrypoint zero-config.
  //
  // Normalisation: SWA's navigationFallback means both `/app` and `/app/`
  // resolve to the same page, but MSAL string-matches the redirect URI
  // exactly against what's registered in CIAM. Strip a trailing
  // `index.html`, then ensure non-file directory paths end in `/` so
  // operators only need to register the canonical (slash-terminated)
  // form once per page.
  // Always redirect to the origin root. MSAL's navigateToLoginRequestUrl
  // (true by default) saves the originating page URL before login and
  // navigates back to it after the redirect completes at '/'. This means
  // only 'https://<domain>/' needs to be registered in CIAM — no per-page
  // URI registration, no TF_VAR_CIAM_DEPLOY_CLIENT_ID secret required.
  function buildMsalConfig(ciam) {
    return {
      auth: {
        clientId: ciam.clientId,
        authority: ciam.authority,
        redirectUri: window.location.origin + '/',
        postLogoutRedirectUri: window.location.origin + '/',
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
      console.warn('[CanopexCiam] MSAL.js not loaded');
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
      console.warn('[CanopexCiam] MSAL init failed:', err);
      return null;
    }
  }

  function notifyAccountChange() {
    for (var i = 0; i < _accountChangeListeners.length; i += 1) {
      try {
        _accountChangeListeners[i](_cachedAccount);
      } catch (cbErr) {
        console.warn('[CanopexCiam] onAccountChange listener threw:', cbErr);
      }
    }
  }

  function applyCachedAccount(app) {
    var accounts = app.getAllAccounts();
    var prev = _cachedAccount;
    if (accounts && accounts.length > 0) {
      _cachedAccount = accounts[0];
    } else {
      _cachedAccount = null;
    }
    if (prev !== _cachedAccount) {
      notifyAccountChange();
    }
    return _cachedAccount;
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
          // Surface to console.error AND to AppInsights so the failure is
          // visible server-side. handleRedirectPromise rejection means the
          // user came back from CIAM but the response was rejected (e.g.
          // issuer mismatch, state mismatch). Silent warns previously hid
          // an outage in production (PR #808).
          console.error('[CanopexCiam] handleRedirectPromise error:', redirectErr);
          reportAuthFailure('handleRedirectPromise', redirectErr);
          return null;
        });
      }).then(function () {
        applyCachedAccount(app);
        return app;
      }).catch(function (initErr) {
        _msalInitPromise = null;
        console.error('[CanopexCiam] MSAL init failed:', initErr);
        reportAuthFailure('msalInitialize', initErr);
        throw initErr;
      });
    }
    return _msalInitPromise;
  }

  function reportAuthFailure(phase, err) {
    try {
      // analytics.js exposes the AppInsights SDK on window.__ai once loaded.
      var ai = window.__ai;
      if (ai && typeof ai.trackException === 'function') {
        ai.trackException({
          exception: err instanceof Error ? err : new Error(String(err)),
          // Match the severity used by the global onerror/unhandledrejection
          // handlers in analytics.js so auth failures are filterable as
          // errors in AppInsights.
          severityLevel: 3,
          properties: {
            phase: phase,
            errorCode: (err && err.errorCode) || '',
            errorMessage: (err && err.errorMessage) || (err && err.message) || '',
            subError: (err && err.subError) || '',
          },
        });
      }
    } catch (_) {
      /* never let telemetry break auth */
    }
  }

  function getAccount() {
    return _cachedAccount;
  }

  function getCurrentUser() {
    if (!_cachedAccount) return null;
    return {
      userId: _cachedAccount.localAccountId || _cachedAccount.homeAccountId || '',
      name: _cachedAccount.name || _cachedAccount.username || '',
      identityProvider: 'ciam',
      userRoles: [],
    };
  }

  function login() {
    return ensureMsalReady().then(function (app) {
      if (!app) return null;
      return app.loginRedirect({ scopes: buildApiScopes(getCiamConfig()) });
    }).catch(function (err) {
      console.error('[CanopexCiam] loginRedirect failed:', err);
      reportAuthFailure('loginRedirect', err);
      return null;
    });
  }

  function logout(opts) {
    var options = opts || {};
    return ensureMsalReady().then(function (app) {
      if (typeof options.onBeforeLogout === 'function') {
        try { options.onBeforeLogout(); } catch (_) { /* ignore */ }
      }
      if (!app) return null;
      var account = app.getAllAccounts()[0] || null;
      return app.logoutRedirect({
        account: account,
        postLogoutRedirectUri: window.location.origin + '/',
      });
    }).catch(function (err) {
      console.error('[CanopexCiam] logoutRedirect failed:', err);
      reportAuthFailure('logoutRedirect', err);
      return null;
    });
  }

  /**
   * Acquire a CIAM API access token, redirecting if interactive auth is needed.
   *
   * Throws a CanopexAuthRedirectError (with `authRedirectTriggered=true`) when
   * a redirect login has been initiated — callers should catch this and avoid
   * issuing the unauthenticated request.
   *
   * Throws a regular Error when auth is misconfigured (apiAudience missing).
   * This is preferred over silently returning '' — empty tokens were the
   * cause of intermittent 401 floods we saw in production.
   */
  async function getToken() {
    var app = await ensureMsalReady();
    if (!app) {
      throw new Error('[CanopexCiam] MSAL not configured — cannot get token');
    }

    var ciam = getCiamConfig();
    if (!ciam.apiAudience) {
      // Misconfiguration. Raise loudly instead of returning '' so the caller
      // sees a real error and the operator notices.
      throw new Error(
        '[CanopexCiam] apiAudience is not configured — backend will reject ' +
        'every request. Check CIAM_API_AUDIENCE deploy secret.'
      );
    }

    var accounts = app.getAllAccounts();
    if (!accounts || accounts.length === 0) {
      login();
      throw buildRedirectError('[CanopexCiam] Redirecting to login (no cached account)');
    }

    var account = accounts[0];
    var request = { scopes: buildApiScopes(ciam), account: account };

    try {
      var result = await app.acquireTokenSilent(request);
      _lastTokenAcquiredAt = new Date().toISOString();
      console.debug('[CanopexCiam] tokenAge: acquired at', _lastTokenAcquiredAt);
      return result.accessToken || '';
    } catch (silentErr) {
      var errorCode = String((silentErr && silentErr.errorCode) || '');
      if (errorCode !== 'interaction_in_progress') {
        console.warn('[CanopexCiam] Silent token acquisition failed, redirecting:', silentErr);
        app.acquireTokenRedirect(request).catch(function (redirectErr) {
          console.error('[CanopexCiam] Redirect login failed:', redirectErr);
        });
      }
      throw buildRedirectError('[CanopexCiam] Redirecting to refresh session', silentErr);
    }
  }

  // Internal hook for handleApiError flows — try popup re-auth without
  // navigating away from the current page (so an in-flight demo survives a
  // 401). Falls back to a full redirect login if the popup is blocked.
  async function reauthInPlace() {
    var app = await ensureMsalReady();
    if (!app) return null;
    var account = app.getAllAccounts()[0];
    if (!account) {
      login();
      return null;
    }
    var ciam = getCiamConfig();
    var request = { scopes: buildApiScopes(ciam), account: account };
    var result = await app.acquireTokenPopup(request);
    _lastTokenAcquiredAt = new Date().toISOString();
    console.debug('[CanopexCiam] Re-auth via popup succeeded at', _lastTokenAcquiredAt);
    return result;
  }

  function onAccountChange(cb) {
    if (typeof cb === 'function') {
      _accountChangeListeners.push(cb);
    }
    return function unsubscribe() {
      _accountChangeListeners = _accountChangeListeners.filter(function (fn) {
        return fn !== cb;
      });
    };
  }

  function getLastTokenAcquiredAt() {
    return _lastTokenAcquiredAt;
  }

  window.CanopexCiam = {
    getCiamConfig: getCiamConfig,
    buildApiScopes: buildApiScopes,
    authEnabled: authEnabled,
    ensureMsalReady: ensureMsalReady,
    getAccount: getAccount,
    getCurrentUser: getCurrentUser,
    login: login,
    logout: logout,
    getToken: getToken,
    reauthInPlace: reauthInPlace,
    onAccountChange: onAccountChange,
    buildRedirectError: buildRedirectError,
    getLastTokenAcquiredAt: getLastTokenAcquiredAt,
  };
})();
