(function() {
  'use strict';

  let currentAccount = null;

  function createApiClient() {
    if (window.CanopexApiClient && typeof window.CanopexApiClient.createClient === 'function') {
      return window.CanopexApiClient.createClient({
        statusBadgeId: 'status-badge',
      });
    }

    console.error('[canopex] Shared API client unavailable; falling back to same-origin API mode.');
    let fallbackApiBase = '';
    let fallbackPrincipal = null;
    let fallbackSessionToken = '';

    function runningOnLocalDevOrigin() {
      return window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    }

    function isLoopbackHost(hostname) {
      return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
    }

    function encodePrincipal(principal) {
      var jsonStr = JSON.stringify(principal);
      var bytes = new TextEncoder().encode(jsonStr);
      var binStr = Array.from(bytes, function(b) { return String.fromCharCode(b); }).join('');
      return btoa(binStr);
    }

    return {
      setClientPrincipal: function(principal) {
        fallbackPrincipal = principal || null;
      },
      setSessionToken: function(token) {
        fallbackSessionToken = token || '';
      },
      clearAuth: function() {
        fallbackPrincipal = null;
        fallbackSessionToken = '';
      },
      discoverApiBase: async function() {
        try {
          const cfgRes = await fetch('/api-config.json');
          if (cfgRes.ok) {
            const cfg = await cfgRes.json();
            if (cfg && cfg.apiBase) {
              const parsed = new URL(cfg.apiBase);
              if (!(isLoopbackHost(parsed.hostname) && !runningOnLocalDevOrigin())) {
                fallbackApiBase = cfg.apiBase.replace(/\/+$/, '');
              }
            }
          }
        } catch {
          /* local dev or config unavailable */
        }
        return fallbackApiBase;
      },
      fetch: async function(path, opts) {
        opts = opts || {};
        opts.headers = opts.headers || {};
        if (fallbackPrincipal) {
          opts.headers['X-MS-CLIENT-PRINCIPAL'] = encodePrincipal(fallbackPrincipal);
        }
        if (fallbackSessionToken) {
          opts.headers['X-Auth-Session'] = fallbackSessionToken;
        }
        if (!fallbackApiBase) {
          await this.discoverApiBase();
        }
        const url = fallbackApiBase ? fallbackApiBase + path : path;
        const response = await fetch(url, opts);
        if (!response.ok) {
          const body = await response.json().catch(function() { return {}; });
          const msg = body.error || ('API request failed: ' + response.status + ' ' + response.statusText);
          const err = new Error(msg);
          err.status = response.status;
          err.body = body;
          throw err;
        }
        return response;
      },
    };
  }

  const apiClient = createApiClient();

  function authEnabled() { return true; }

  async function initAuth() {
    try {
      const res = await fetch('/.auth/me');
      if (!res.ok) { updateAuthUI(); updateSampleReportGate(); return; }
      const data = await res.json();
      const principal = data && data.clientPrincipal;
      if (principal && principal.userId) {
        apiClient.setClientPrincipal(principal);
        currentAccount = {
          userId: principal.userId,
          name: principal.userDetails || principal.userId,
          identityProvider: principal.identityProvider,
          userRoles: principal.userRoles || []
        };
      }
    } catch (err) {
      console.warn('[canopex] SWA auth check failed:', err);
    }
    updateAuthUI();
    updateSampleReportGate();
  }

  function login() {
    window.location.href = '/.auth/login/aad';
  }

  function logout() {
    window.location.href = '/.auth/logout';
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
