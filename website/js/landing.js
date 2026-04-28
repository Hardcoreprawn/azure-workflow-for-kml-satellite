(function() {
  'use strict';

  let currentAccount = null;

  function createApiClient() {
    if (!window.CanopexApiClient || typeof window.CanopexApiClient.createClient !== 'function') {
      throw new Error('[canopex] canopex-api-client.js must be loaded before landing.js');
    }
    return window.CanopexApiClient.createClient({
      statusBadgeId: 'status-badge',
    });
  }

  const apiClient = createApiClient();

  function authEnabled() { return true; }

  function buildRedirectError(message, cause) {
    const err = new Error(message);
    err.name = 'CanopexAuthRedirectError';
    err.authRedirectTriggered = true;
    if (cause) err.cause = cause;
    return err;
  }

  // Returns the MSAL app instance, or null if CIAM is not configured.
  function getMsalApp() {
    if (!window.msal) return null;
    const el = document.getElementById('canopex-ciam-config');
    if (!el) return null;
    let cfg;
    try { cfg = JSON.parse(el.textContent || '{}'); } catch (_) { return null; }
    if (!cfg.clientId || !cfg.authority) return null;
    if (!getMsalApp._instance) {
      try {
        getMsalApp._instance = new window.msal.PublicClientApplication({
          auth: {
            clientId: cfg.clientId,
            authority: cfg.authority,
            redirectUri: window.location.origin + '/app/',
            postLogoutRedirectUri: window.location.origin + '/',
            knownAuthorities: [cfg.authority.replace(/https?:\/\//, '').split('/')[0]],
          },
          cache: { cacheLocation: 'localStorage', storeAuthStateInCookie: false },
        });
      } catch (err) {
        console.warn('[canopex] MSAL init failed:', err);
        return null;
      }
    }
    return getMsalApp._instance;
  }

  async function initAuth() {
    const app = getMsalApp();
    if (!app) {
      // CIAM not configured (local dev) — show unauthenticated UI.
      updateAuthUI();
      updateSampleReportGate();
      return;
    }
    try {
      await app.initialize();
      await app.handleRedirectPromise();
      const accounts = app.getAllAccounts();
      if (accounts && accounts.length > 0) {
        const account = accounts[0];
        currentAccount = {
          userId: account.localAccountId || account.homeAccountId || '',
          name: account.name || account.username || '',
          identityProvider: 'ciam',
          userRoles: [],
        };
        apiClient.setGetToken(async function () {
          const req = { scopes: ['openid', 'profile'], account: account };
          try {
            const result = await app.acquireTokenSilent(req);
            return result.idToken || result.accessToken || '';
          } catch (tokenErr) {
            const errorCode = String((tokenErr && tokenErr.errorCode) || '');
            if (errorCode !== 'interaction_in_progress') {
              app.acquireTokenRedirect(req).catch(function (redirectErr) {
                console.error('[canopex] acquireTokenRedirect failed:', redirectErr);
              });
            }
            throw buildRedirectError('[canopex] Redirecting to refresh session', tokenErr);
          }
        });
      }
    } catch (err) {
      console.warn('[canopex] MSAL auth check failed:', err);
    }
    updateAuthUI();
    updateSampleReportGate();
  }

  function login() {
    const app = getMsalApp();
    if (!app) return;
    app.loginRedirect({ scopes: ['openid', 'profile'] }).catch(function (err) {
      console.error('[canopex] loginRedirect failed:', err);
    });
  }

  function logout() {
    const app = getMsalApp();
    if (!app) return;
    const accounts = app.getAllAccounts();
    app.logoutRedirect({
      account: accounts && accounts[0] || null,
      postLogoutRedirectUri: window.location.origin + '/',
    }).catch(function (err) {
      console.error('[canopex] logoutRedirect failed:', err);
    });
  }

  function updateAuthUI() {
    const loginBtn = document.getElementById('auth-login-btn');
    const logoutBtn = document.getElementById('auth-logout-btn');
    const userSpan = document.getElementById('auth-user');
    const dashLink = document.getElementById('auth-dashboard-link');

    if (!authEnabled()) {
      if (loginBtn) loginBtn.style.display = 'none';
      if (logoutBtn) logoutBtn.style.display = 'none';
      if (userSpan) userSpan.style.display = 'none';
      if (dashLink) dashLink.style.display = 'none';
      return;
    }

    if (currentAccount) {
      const name = currentAccount.name || currentAccount.userId || 'User';
      if (userSpan) userSpan.textContent = name;
      if (userSpan) userSpan.style.display = 'inline';
      if (loginBtn) loginBtn.style.display = 'none';
      if (logoutBtn) logoutBtn.style.display = 'inline';
      if (dashLink) dashLink.style.display = 'inline';
    } else {
      if (userSpan) userSpan.style.display = 'none';
      if (loginBtn) loginBtn.style.display = 'inline';
      if (logoutBtn) logoutBtn.style.display = 'none';
      if (dashLink) dashLink.style.display = 'none';
    }
  }

  async function apiFetch(path, opts) {
    return apiClient.fetch(path, opts);
  }

  async function discoverApiBase() {
    return apiClient.discoverApiBase();
  }

  /* --- Sample Report Map (Planetary Computer S2 visual) --- */
  async function initSampleMap() {
    const mapEl = document.getElementById('sample-map');
    if (!mapEl || typeof L === 'undefined') return;

    // São Félix do Xingu, Pará — real PRODES d2021 deforestation polygon
    // from INPE/Terrabrasilis WFS (prodes-amazon-nb:yearly_deforestation_biome).
    // 0.379 km² clearing detected 2021, near Fresco River, state PA.
    // Coordinates sourced from official Brazilian government deforestation
    // monitoring — the same data EUDR regulators reference.
    const parcelCoords = [
      [-6.6624, -51.8461],
      [-6.6620, -51.8461],
      [-6.6618, -51.8461],
      [-6.6591, -51.8449],
      [-6.6613, -51.8394],
      [-6.6618, -51.8394],
      [-6.6618, -51.8400],
      [-6.6620, -51.8400],
      [-6.6628, -51.8400],
      [-6.6628, -51.8394],
      [-6.6634, -51.8394],
      [-6.6634, -51.8389],
      [-6.6639, -51.8389],
      [-6.6639, -51.8383],
      [-6.6644, -51.8383],
      [-6.6644, -51.8386],
      [-6.6647, -51.8386],
      [-6.6647, -51.8389],
      [-6.6653, -51.8389],
      [-6.6653, -51.8391],
      [-6.6655, -51.8391],
      [-6.6655, -51.8394],
      [-6.6658, -51.8394],
      [-6.6658, -51.8389],
      [-6.6661, -51.8389],
      [-6.6661, -51.8383],
      [-6.6662, -51.8383],
      [-6.6665, -51.8389],
      [-6.6671, -51.8387],
      [-6.6671, -51.8389],
      [-6.6674, -51.8389],
      [-6.6674, -51.8391],
      [-6.6673, -51.8391],
      [-6.6672, -51.8392],
      [-6.6671, -51.8415],
      [-6.6670, -51.8416],
      [-6.6664, -51.8417],
      [-6.6662, -51.8419],
      [-6.6660, -51.8419],
      [-6.6660, -51.8421],
      [-6.6654, -51.8425],
      [-6.6635, -51.8419],
      [-6.6624, -51.8461]
    ];
    const center = [-6.6647, -51.8404];

    const map = L.map(mapEl, {
      scrollWheelZoom: false,
      zoomControl: true,
      attributionControl: true
    }).setView(center, 14);

    // Register a PC mosaic for recent low-cloud S2 visual imagery
    const bbox = [-51.85, -6.68, -51.83, -6.65];
    const registerBody = {
      collections: ['sentinel-2-l2a'],
      'filter-lang': 'cql2-json',
      filter: {
        op: 'and',
        args: [
          { op: 's_intersects', args: [
            { property: 'geometry' },
            { type: 'Polygon', coordinates: [[
              [bbox[0], bbox[1]], [bbox[2], bbox[1]],
              [bbox[2], bbox[3]], [bbox[0], bbox[3]],
              [bbox[0], bbox[1]]
            ]]}
          ]},
          { op: '<=', args: [{ property: 'eo:cloud_cover' }, 10] },
          { op: '>=', args: [{ property: 'datetime' }, '2025-01-01T00:00:00Z'] }
        ]
      }
    };

    // Esri fallback base layer
    const esriLayer = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { attribution: 'Tiles &copy; Esri', maxZoom: 18 }
    );
    esriLayer.addTo(map);

    // Try to overlay PC Sentinel-2 visual tiles (cache searchid to avoid re-registration)
    try {
      const CACHE_KEY = 'canopex_mosaic_searchid';
      const CACHE_TTL_MS = 30 * 60 * 1000; // 30 minutes
      let searchid = null;

      const cached = sessionStorage.getItem(CACHE_KEY);
      if (cached) {
        const entry = JSON.parse(cached);
        if (entry.ts && Date.now() - entry.ts < CACHE_TTL_MS) {
          searchid = entry.id;
        }
      }

      if (!searchid) {
        const res = await fetch('https://planetarycomputer.microsoft.com/api/data/v1/mosaic/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(registerBody)
        });
        if (!res.ok) {
          console.warn('[canopex] PC mosaic register failed:', res.status, res.statusText);
          return;
        }
        const data = await res.json();
        if (!data || !data.searchid) return;
        searchid = data.searchid;
        sessionStorage.setItem(CACHE_KEY, JSON.stringify({ id: searchid, ts: Date.now() }));
      }

      const tileUrl = 'https://planetarycomputer.microsoft.com/api/data/v1/mosaic/tiles/' +
        encodeURIComponent(searchid) + '/WebMercatorQuad/{z}/{x}/{y}@2x' +
        '?collection=sentinel-2-l2a&assets=visual';
      const pcLayer = L.tileLayer(tileUrl, {
        tileSize: 512,
        zoomOffset: -1,
        maxNativeZoom: 14,
        maxZoom: 18,
        attribution: 'Sentinel-2 &copy; ESA / Copernicus via Planetary Computer'
      });
      map.removeLayer(esriLayer);
      pcLayer.addTo(map);
    } catch (err) {
      // Keep Esri fallback — log for diagnostics
      console.warn('[canopex] PC mosaic overlay failed, using Esri fallback:', err);
    }

    L.polygon(parcelCoords, {
      color: '#5eecc4',
      weight: 2,
      fillColor: '#5eecc4',
      fillOpacity: 0.15
    }).addTo(map);

    // Fix Leaflet tile rendering after container becomes visible
    setTimeout(function() { map.invalidateSize(); }, 200);
  }

  /* --- Sample Report PDF Gate --- */
  function updateSampleReportGate() {
    const btn = document.getElementById('btn-download-sample');
    const note = document.getElementById('sample-gated-note');
    if (!btn) return;

    if (currentAccount) {
      btn.textContent = 'Download Full PDF Report';
      if (note) note.style.display = 'none';
      btn.onclick = function() {
        // Placeholder — actual PDF export wired in Stage 2F (#605)
        alert('PDF report download coming soon. The assessment data shown above is representative of the full evidence package.');
      };
    } else {
      btn.textContent = 'Sign In to Download PDF';
      if (note) {
        note.textContent = 'Sign in to download the full PDF evidence report.';
        note.style.display = 'block';
      }
      btn.onclick = function() { login(); };
    }
  }

  /* --- Subscribe Button --- */
  function initSubscribe() {
    const btn = document.getElementById('btn-subscribe');
    if (!btn) return;

    btn.addEventListener('click', async function() {
      if (!currentAccount && authEnabled()) { login(); return; }
      try {
        const res = await apiFetch('/api/billing/checkout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tier: 'eudr_pro' })
        });
        const data = await res.json();
        if (data.checkout_url) { window.location.href = data.checkout_url; }
      } catch (e) {
        if (e && e.authRedirectTriggered) {
          return;
        }
        console.error('Checkout error:', e);
        if (e && e.status === 403) {
          alert('Your account is not yet enabled for billing. Please contact us at hello@canopex.io.');
          return;
        }
        alert((e && e.message) || 'Could not connect to billing. Please try again later.');
      }
    });
  }

  /* --- FAQ toggle --- */
  function initFAQ() {
    const faqList = document.getElementById('faq-list');
    if (!faqList) return;

    faqList.addEventListener('click', function(e) {
    const item = e.target.closest('.faq-item');
      if (item) item.classList.toggle('open');
    });
  }

  /* --- Auth event listeners --- */
  document.addEventListener('DOMContentLoaded', function() {
    const loginBtn = document.getElementById('auth-login-btn');
    const logoutBtn = document.getElementById('auth-logout-btn');

    if (loginBtn) loginBtn.addEventListener('click', login);
    if (logoutBtn) logoutBtn.addEventListener('click', logout);

    initFAQ();
    initSampleMap();
    initSubscribe();
  });

  /* Handle billing return query params */
  document.addEventListener('DOMContentLoaded', function() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('billing') === 'success') {
      setTimeout(function() { alert('Welcome to EUDR Pro! Your subscription is now active.'); }, 500);
      history.replaceState(null, '', window.location.pathname);
    } else if (params.get('billing') === 'cancel') {
      history.replaceState(null, '', window.location.pathname);
    }
  });

  /* Initialization */
  initAuth();
  discoverApiBase();
})();
