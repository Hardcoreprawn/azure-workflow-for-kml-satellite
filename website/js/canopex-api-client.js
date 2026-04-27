(function() {
  'use strict';

  const DEFAULTS = {
    statusBadgeId: 'status-badge',
    serviceStatusCacheKey: 'canopex:service-status:v1',
    serviceStatusTtlMs: 2 * 60 * 1000,
    apiConfigPath: '/api-config.json',
    apiConfigTimeoutMs: 900,
    apiHealthTimeoutMs: 1200
  };

  function runningOnLocalDevOrigin() {
    return window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  }

  function isLoopbackApiBase(value) {
    if (!value || typeof value !== 'string') return false;
    try {
      const parsed = new URL(value);
      const host = parsed.hostname;
      return host === 'localhost' || host === '127.0.0.1' || host === '::1';
    } catch {
      return false;
    }
  }

  function readCachedServiceStatus(config) {
    try {
      const raw = localStorage.getItem(config.serviceStatusCacheKey);
      if (!raw) return '';
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return '';
      if (parsed.status !== 'online' && parsed.status !== 'offline') return '';
      if (!parsed.ts || Date.now() - parsed.ts > config.serviceStatusTtlMs) return '';
      return parsed.status;
    } catch {
      return '';
    }
  }

  function writeCachedServiceStatus(config, status) {
    try {
      localStorage.setItem(config.serviceStatusCacheKey, JSON.stringify({ status: status, ts: Date.now() }));
    } catch {
      /* localStorage unavailable */
    }
  }

  function applyServiceStatus(config, status) {
    const badge = document.getElementById(config.statusBadgeId);
    if (!badge) return;
    if (status === 'online') {
      badge.textContent = 'Online';
      badge.className = 'online';
      return;
    }
    badge.textContent = 'Unavailable';
    badge.className = 'offline';
  }

  async function fetchWithTimeout(url, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(function() {
      controller.abort();
    }, timeoutMs);
    try {
      return await fetch(url, { signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
  }

  async function resolveConfiguredBase(config) {
    try {
      const cfgRes = await fetchWithTimeout(config.apiConfigPath, config.apiConfigTimeoutMs);
      if (!cfgRes.ok) return '';
      const cfg = await cfgRes.json();
      if (!cfg || !cfg.apiBase) return '';
      return String(cfg.apiBase).replace(/\/+$/, '');
    } catch {
      return '';
    }
  }

  async function probeApiBase(config, base) {
    const healthUrl = base ? (base + '/api/health') : '/api/health';
    const res = await fetchWithTimeout(healthUrl, config.apiHealthTimeoutMs);
    if (!res.ok) {
      throw new Error('Health probe failed: ' + res.status);
    }
  }

  function createClient(options) {
    const config = Object.assign({}, DEFAULTS, options || {});
    let apiBase = '';
    // getToken is injected by app-shell.js after the MSAL module wires in.
    // It returns a Promise<string> (the CIAM id/access token).
    let _getToken = null;

    function clearAuth() {
      _getToken = null;
    }

    function setGetToken(fn) {
      _getToken = (typeof fn === 'function') ? fn : null;
    }

    function getApiBase() {
      return apiBase;
    }

    async function discoverApiBase() {
      const cachedStatus = readCachedServiceStatus(config);
      if (cachedStatus) {
        applyServiceStatus(config, cachedStatus);
      }

      const configuredBase = await resolveConfiguredBase(config);
      const candidates = [];
      if (configuredBase) {
        if (runningOnLocalDevOrigin() || !isLoopbackApiBase(configuredBase)) {
          candidates.push(configuredBase);
        }
      }
      candidates.push('');

      for (let i = 0; i < candidates.length; i += 1) {
        const candidate = candidates[i];
        try {
          await probeApiBase(config, candidate);
          apiBase = candidate;
          applyServiceStatus(config, 'online');
          writeCachedServiceStatus(config, 'online');
          return;
        } catch {
          /* try next candidate */
        }
      }

      if (!cachedStatus) {
        applyServiceStatus(config, 'offline');
      }
      writeCachedServiceStatus(config, 'offline');
    }

    async function apiFetch(path, opts) {
      const requestOpts = Object.assign({}, opts || {});
      requestOpts.headers = Object.assign({}, requestOpts.headers || {});

      if (_getToken) {
        try {
          const token = await _getToken();
          if (token) {
            requestOpts.headers['Authorization'] = 'Bearer ' + token;
          }
        } catch (tokenErr) {
          // Log but proceed — the backend will reject with 401 and the auth
          // error handler will redirect to login.
          console.warn('[CanopexApiClient] Failed to acquire token:', tokenErr);
        }
      }

      const url = apiBase ? apiBase + path : path;
      const resp = await fetch(url, requestOpts);
      if (!resp.ok) {
        const body = await resp.json().catch(function() { return {}; });
        const msg = body.error || ('API request failed: ' + resp.status + ' ' + resp.statusText);
        const err = new Error(msg);
        err.status = resp.status;
        err.body = body;
        throw err;
      }
      return resp;
    }

    return {
      discoverApiBase: discoverApiBase,
      fetch: apiFetch,
      setGetToken: setGetToken,
      clearAuth: clearAuth,
      getApiBase: getApiBase,
    };
  }

  window.CanopexApiClient = {
    createClient: createClient,
  };
})();
